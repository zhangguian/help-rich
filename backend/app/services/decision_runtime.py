"""决策装配运行时(从 api 层下沉到 service 层)

**为什么下沉**:盘中信号模块(`app/modules/signal/`)需要复用**同一份**决策装配逻辑,
但架构守卫禁止 modules 依赖 `app.api.*`
(`tests/test_architecture_boundaries.py::test_modules_do_not_import_legacy_layered_api`)。
装配逻辑只有一份时,决策卡与桌面信号才**口径 100% 同源** —— 不会出现
"决策卡说 T 卖点 12.50、信号弹 12.20"这种两套说法打架。

**依赖注入**:外部依赖(K 线 / 行情 / 持仓 / 市场环境 / extras / 决策引擎)全部经
`DecisionDeps` 注入,默认走真实实现。`app/api/stock.py` 传入本模块的可 patch 点,
因此既有测试的 patch 目标(`app.api.stock.fetch_klines` 等)保持不变。

**降级纪律**:任一输入缺失 → 对应字段为 None 并写进 degraded,**绝不编数字**。
K 线或指标完全不可用 → 抛 `DecisionDataUnavailable`(api 层转 HTTP 502)。
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from app.core.instrument import resolve_instrument
from app.core.logging import logger
from app.services.decision_advice_service import build_fact_pack, compose_rule_advice
from app.services.decision_context_service import (
    DecisionExtras,
    enrich_decision_context,
    load_decision_extras,
    parse_date,
)
from app.services.decision_service import (
    DecisionContext,
    MarketContext,
    build_decision,
)
from app.services.kline_service import KLineSourceUnavailable, fetch_klines
from app.services.market_context_service import get_market_context
from app.services.position_status import (
    kline_fallback_price,
    resolve_position_status,
    sanitize_current_price,
)
from app.services.ta_service import compute_indicators

# 与决策卡一致:K 线取 300 根(约 12 个月交易日)
KLINE_COUNT = 300


class DecisionDataUnavailable(Exception):
    """决策装配所需的关键数据不可用(K 线拉取失败 / 指标计算失败)。

    api 层负责转成 HTTP 502;service 层不抛 HTTP 异常 —— 那是 api 层的职责。
    """


@dataclass(frozen=True)
class DecisionDeps:
    """决策装配的外部依赖(全部可注入,便于单测与架构隔离)。"""

    fetch_klines: Callable[..., Awaitable[list[dict]]]
    get_position: Callable[..., Awaitable[Any]]
    get_market_context: Callable[..., Awaitable[MarketContext | None]]
    load_decision_extras: Callable[..., Awaitable[DecisionExtras]]
    build_decision: Callable[[DecisionContext], dict]


def default_deps() -> DecisionDeps:
    """生产默认依赖(真实实现)。"""
    return DecisionDeps(
        fetch_klines=fetch_klines,
        get_position=_default_get_position,
        get_market_context=get_market_context,
        load_decision_extras=load_decision_extras,
        build_decision=build_decision,
    )


async def _default_get_position(code: str) -> Any:
    from app.modules.portfolio.service import get_position

    return await get_position(code)


async def _load_quote(code: str) -> Any:
    """拉实时行情(失败返回 None,不阻断分析)。

    与决策卡同款:走 `QuoteService.get_quotes`(带 5 分钟缓存)。
    """
    from app.services.quote_service import QuoteService

    try:
        qs = await QuoteService().get_quotes([code])
        return qs[0] if qs else None
    except Exception as e:  # noqa: BLE001 — 拿不到报价就降级,不阻断
        logger.warning("决策装配拉取行情失败({}): {}", code, e)
        return None


async def _load_klines(deps: DecisionDeps, code: str, count: int = KLINE_COUNT) -> list[dict]:
    """拉 K 线(失败抛 `DecisionDataUnavailable`)。"""
    try:
        return await deps.fetch_klines(code, period="daily", count=count)
    except KLineSourceUnavailable as e:
        raise DecisionDataUnavailable(str(e)) from e


async def build_decision_payload(
    code: str,
    *,
    klines: list[dict] | None = None,
    quote: Any = None,
    include_env: bool = False,
    need_extras: bool = True,
    quote_is_final: bool = False,
    deps: DecisionDeps | None = None,
) -> dict:
    """装配决策上下文并算出决策(零 LLM)。

    Args:
        code: 股票代码(6 位 + .SH/.SZ/.BJ)
        klines: 已取好的 K 线;None → 本函数去取
        quote: 已取好的实时报价;None → 本函数去取(除非 `quote_is_final`)
        include_env: 是否聚合市场环境(4~5 次外部 HTTP)。
            信号侧走 False(便宜),但 `t_plan` / `grid_plan` 判定**不读 env**,
            两者的触发价位口径与决策卡完全一致。
        need_extras: 是否加载费用档 / 现金 / 集中度 / 持有天数
            (影响 `grid_plan` 的资金模式与费用口径,信号侧保持 True 以同源)
        quote_is_final: True → `quote=None` 表示"确定没有报价",不再拉取
            (调用方已自己试过,别重复打数据源)
        deps: 外部依赖(默认走生产实现)

    Returns:
        {"decision": {...}, "klines": [...], "latest_kline_date": "YYYY-MM-DD"}
    """
    d = deps or default_deps()

    if klines is None and quote is None and not quote_is_final:
        # K 线与行情并发取(与改造前 api 层行为一致:一次往返)
        klines, quote = await asyncio.gather(
            _load_klines(d, code),
            _load_quote(code),
        )
    else:
        if klines is None:
            klines = await _load_klines(d, code)
        if quote is None and not quote_is_final:
            quote = await _load_quote(code)

    current_price, _ = sanitize_current_price(quote, klines)

    # 持仓读取降级:SQLite 在并发写(如选股落库)时可能抛 database is locked,
    # 不能让整张决策卡 500 —— 按空仓继续,并在 degraded 里如实标注。
    position_failed = False
    try:
        position = await d.get_position(code)
    except Exception as e:  # noqa: BLE001
        logger.warning("决策装配读取持仓失败({}): {}", code, e)
        position = None
        position_failed = True

    position_status, _ = resolve_position_status(
        position, current_price, kline_fallback_price(klines)
    )

    try:
        indicators = compute_indicators(klines)
    except Exception as e:  # noqa: BLE001
        raise DecisionDataUnavailable(f"K 线指标计算失败: {e}") from e

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

    change_pct = None
    if quote is not None and quote.change_pct is not None:
        try:
            change_pct = float(quote.change_pct)
        except (TypeError, ValueError):
            change_pct = None

    if include_env:
        try:
            env = await d.get_market_context(code, stock_change_pct=change_pct)
        except Exception as e:  # noqa: BLE001
            logger.warning("决策装配市场环境聚合失败({}): {}", code, e)
            env = None
        if env is None:
            env = MarketContext(degraded=["市场环境不可用"])
        if position_failed:
            env = replace(env, degraded=[*env.degraded, "持仓读取失败,按空仓给出建仓参考"])
    else:
        # 不取市场环境(省掉 4~5 次外部 HTTP):事实包只用确定性数字(价位/止损/仓位/网格),
        # 不需要市场环境;「大盘普跌时不要加仓」这条全局规则由决策卡自己承担。
        env = MarketContext(degraded=["市场环境未纳入事实包"])

    inst = resolve_instrument(code)
    ctx = DecisionContext(
        stock_code=code,
        stock_name=getattr(position, "stock_name", None) if position is not None else None,
        indicators=indicators,
        klines=klines,
        current_price=float(current_price) if current_price is not None else None,
        prev_close=prev_close,
        # 空仓时 Position.avg_cost 是 Decimal("0"),语义上不等于"有成本",给 None
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

    latest_kline_date = klines[-1]["date"] if klines else None

    if need_extras:
        extras = await d.load_decision_extras(code, as_of=parse_date(latest_kline_date))
        ctx = enrich_decision_context(ctx, extras)
    else:
        extras = DecisionExtras(degraded=["费用档/现金/集中度未纳入本次装配"])

    decision = d.build_decision(ctx)
    degraded = decision.setdefault("data_quality", {}).setdefault("degraded", [])
    for note in extras.degraded:
        if note not in degraded:
            degraded.append(note)

    # 规则白话兜底(零 LLM、零延迟):决策卡永不空白
    decision["advice"] = {
        **compose_rule_advice(build_fact_pack(decision, as_of=latest_kline_date)),
        "source": "rule",
    }

    return {
        "decision": decision,
        "klines": klines,
        "latest_kline_date": latest_kline_date,
    }


__all__ = [
    "DecisionDataUnavailable",
    "DecisionDeps",
    "KLINE_COUNT",
    "build_decision_payload",
    "default_deps",
]
