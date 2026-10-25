"""计算器 IO 编排层

职责:把「拟交易复核」需要的外部数据拉齐,交给纯函数层
(`app.services.trade_review_service`)做判定。

**分层铁律**:
- 本层**只做 IO 编排**,不做任何判断(判定规则全在纯函数层)
- 纯函数层**零 IO**,可单测

降级原则(与 `/api/stock/{code}/decision` 一致):
- 持仓读失败 → 按空仓继续,并在 degraded 里如实标注
- 行情读失败 → 用 K 线最新收盘价兜底
- 市场环境读失败 → `MarketContext(degraded=["市场环境不可用"])`
- **只有 K 线完全不可用才抛 502**

缓存:只缓存「慢的三件」(K 线 / 指标 / 市场环境),TTL 60 秒;
**持仓与实时价每次现取** —— 否则刚录完一笔流水,计算器还拿着旧持仓算。
"""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from decimal import Decimal
from typing import Any

from app.core.instrument import resolve_instrument
from app.services.decision_service import DecisionContext, MarketContext, build_decision
from app.services.decision_context_service import (
    enrich_decision_context,
    load_decision_extras,
    parse_date,
)
from app.services.kline_service import KLineSourceUnavailable, fetch_klines
from app.services.market_context_service import get_market_context
from app.services.position_status import (
    kline_fallback_price as _kline_fallback_price,
)
from app.services.position_status import (
    resolve_position_status as _resolve_position_status,
)
from app.services.position_status import (
    sanitize_current_price as _sanitize_current_price,
)
from app.services.quote_service import QuoteService
from app.services.ta_service import compute_indicators
from app.services.trade_review_service import ProposedTrade, review_trade

logger = logging.getLogger(__name__)

# 与 api/stock.py 的决策端点保持一致(约 12 个月交易日)
KLINE_COUNT = 300

# 慢数据(K 线 / 指标 / 市场环境)的缓存时长
SLOW_CACHE_TTL_SECONDS = 60

_slow_cache: dict[str, tuple[float, tuple[list[dict], dict, MarketContext]]] = {}


class CalculatorDataUnavailable(RuntimeError):
    """K 线完全不可用 → API 层转 502"""


class _CashUnset:
    """哨兵:「本次请求没有指定可用资金」

    必须和 `None`(明确表示"没有可用资金")区分开 ——
    前者回落到账户已保存的值,后者就是"未填写"。
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "CASH_UNSET"


CASH_UNSET = _CashUnset()


async def _load_klines(code: str, count: int = KLINE_COUNT) -> list[dict]:
    try:
        return await fetch_klines(code, period="daily", count=count)
    except KLineSourceUnavailable as e:
        raise CalculatorDataUnavailable(str(e)) from e


async def _load_quote(code: str):
    """拉实时行情(失败返回 None,不阻断)"""
    try:
        qs = await QuoteService().get_quotes([code])
        return qs[0] if qs else None
    except Exception as e:  # noqa: BLE001
        logger.warning("计算器拉取行情失败(%s): %s", code, e)
        return None


async def _load_slow(code: str) -> tuple[list[dict], dict, MarketContext]:
    """K 线 + 指标 + 市场环境(慢,带 60s 缓存)"""
    now = time.monotonic()
    cached = _slow_cache.get(code)
    if cached is not None and now - cached[0] < SLOW_CACHE_TTL_SECONDS:
        return cached[1]

    klines = await _load_klines(code)
    indicators = compute_indicators(klines)

    quote = await _load_quote(code)
    change_pct = None
    if quote is not None and getattr(quote, "change_pct", None) is not None:
        try:
            change_pct = float(quote.change_pct)
        except (TypeError, ValueError):
            change_pct = None
    try:
        env = await get_market_context(code, stock_change_pct=change_pct)
    except Exception as e:  # noqa: BLE001
        logger.warning("计算器聚合市场环境失败(%s): %s", code, e)
        env = MarketContext(degraded=["市场环境不可用"])

    payload = (klines, indicators, env)
    _slow_cache[code] = (now, payload)
    return payload


async def build_decision_context(code: str) -> tuple[DecisionContext, Any]:
    """装配决策上下文(持仓与实时价现取)

    Returns:
        (DecisionContext, position)
    """
    from app.modules.portfolio.service import get_position

    klines, indicators, env = await _load_slow(code)

    quote = await _load_quote(code)
    current_price, _ = _sanitize_current_price(quote, klines)
    if current_price is None:
        current_price = _kline_fallback_price(klines)

    position_failed = False
    try:
        position = await get_position(code)
    except Exception as e:  # noqa: BLE001
        logger.warning("计算器读取持仓失败(%s): %s", code, e)
        position = None
        position_failed = True

    position_status, _ = _resolve_position_status(
        position, current_price, _kline_fallback_price(klines)
    )
    if position_failed:
        env = replace(env, degraded=[*env.degraded, "持仓读取失败,按空仓给出参考"])

    prev_close = None
    if quote is not None:
        try:
            prev_close = float(quote.prev_close) if quote.prev_close is not None else None
        except (TypeError, ValueError):
            prev_close = None
    if prev_close is None and len(klines) >= 2:
        try:
            prev_close = float(klines[-2]["close"])
        except (TypeError, ValueError):
            prev_close = None

    inst = resolve_instrument(code)
    ctx = DecisionContext(
        stock_code=code,
        stock_name=getattr(position, "stock_name", None) if position is not None else None,
        indicators=indicators,
        klines=klines,
        current_price=float(current_price) if current_price is not None else None,
        prev_close=prev_close,
        cost_basis=(
            float(position.avg_cost)
            if position is not None and position.shares and position.shares > 0
            else None
        ),
        shares=int(position.shares) if position is not None and position.shares else 0,
        position_status=position_status,
        env=env,
        # 品种属性:ETF 无涨跌停、跨境/黄金类 T+0 → 判定口径要分流
        instrument_kind=inst.kind,
        t0=inst.t0,
    )
    # v0.10:新增输入与决策卡共用同一装配口(费用档/现金/集中度/持有天数),
    # 否则决策卡与计算器 T 卡会给出两套口径。
    extras = await load_decision_extras(
        code, as_of=parse_date(klines[-1]["date"] if klines else None)
    )
    ctx = enrich_decision_context(ctx, extras)
    return ctx, position


async def review_proposed_trade(
    stock_code: str,
    action: str,
    tx_shares: int,
    tx_price: Decimal,
    cash_available: Decimal | None | _CashUnset = CASH_UNSET,
) -> dict:
    """拟交易复核:IO 编排 → 决策 → 纯函数判定

    Args:
        cash_available: 账户可用资金覆盖值。默认 `CASH_UNSET` = 用账户已保存的值;
            显式传 None = 明确"没有可用资金"(判定层据此给正T 的股数 = None)。
    """
    from app.modules.portfolio.service import get_cash_available, get_position

    ctx, position = await build_decision_context(stock_code)
    decision = build_decision(ctx)

    # 持仓读失败时 build_decision_context 已降级为 None,这里再兜一次
    if position is None:
        try:
            position = await get_position(stock_code)
        except Exception:  # noqa: BLE001
            position = None

    if cash_available is CASH_UNSET:
        try:
            cash_available = await get_cash_available()
        except Exception as e:  # noqa: BLE001
            logger.warning("计算器读取账户可用资金失败(%s): %s", stock_code, e)
            cash_available = None

    proposed = ProposedTrade(
        action=action,  # type: ignore[arg-type]
        shares=tx_shares,
        price=float(tx_price),
    )
    return review_trade(ctx, decision, proposed, position, cash_available)


__all__ = [
    "KLINE_COUNT",
    "SLOW_CACHE_TTL_SECONDS",
    "CalculatorDataUnavailable",
    "CASH_UNSET",
    "build_decision_context",
    "review_proposed_trade",
]
