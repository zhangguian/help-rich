"""个股**逐日**资金流取数 + DB 缓存(behavior_signal_service 的数据源)。

**为什么要有缓存层**:
K 线本身走 `KlineCache`(DB 优先 → miss 才拉),所以 K 线端点很快。
资金流若无缓存 → 每开一次 K 线图都新增一次外网请求 → **拖慢主流程**。
故本模块与 `kline_service.fetch_klines` 同构:**DB 优先 → miss 拉真实接口 → 回填落库**。

**为什么按日期对齐**:
新浪逐日资金流接口返回**降序**(sort=opendate&asc=0),而日 K 是**升序**。
按索引 zip 会让两者**整体错位一天** —— 产生看似合理实则完全错误的信号。
故本模块只对外暴露 `align_by_date()`,强制调用方按日期字典取用。

**编码注意**:接口响应头虽为 `charset=gbk`,但服务端已把中文转义成 `\\uXXXX`,
故用 `resp.json()` 即得正确字符串;**不要**用 `resp.text` 再手动 decode(会乱码)。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.core.config import BEHAVIOR_FUND_FLOW_TIMEOUT_SEC

logger = logging.getLogger(__name__)

#: 新浪逐日资金流接口
SINA_FLOW_DAILY_URL = (
    "https://vip.stock.finance.sina.com.cn/"
    "quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs"
)

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn",
}


class FundFlowUnavailable(Exception):
    """资金流数据源不可用(网络/接口变更/反爬)"""


def _to_sina_symbol(stock_code: str) -> str:
    """600519.SH → sh600519(与 kline_service 同口径)。"""
    code, _, market = stock_code.partition(".")
    market = market.lower() if market else "sh"
    market = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(market.upper(), market.lower())
    return f"{market}{code}"


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _parse_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """新浪逐日资金流行 → 统一字段。"""
    if not isinstance(row, dict):
        return None
    opendate = str(row.get("opendate") or "").strip()
    if not opendate:
        return None
    return {
        "date": opendate,
        "net_amount": _f(row.get("netamount")),        # 主力净额(元)
        "r0_net": _f(row.get("r0_net")),                # 超大单净额(元)
        "r0x_ratio": _f(row.get("r0x_ratio")),          # 主力净占比(%)
        "r0_ratio": _f(row.get("r0_ratio")),            # 超大单占比(%)
        "turnover": _f(row.get("turnover")),            # 换手率(%)
        "change_ratio": _f(row.get("changeratio")),     # 涨跌幅(小数)
    }


async def _fetch_sina_flow_daily(
    stock_code: str, count: int
) -> list[dict[str, Any]]:
    """拉个股逐日资金流(真实接口,无 mock;失败抛 FundFlowUnavailable)。

    Returns: 解析后的行列表(**降序**,与接口一致)。
    """
    params = {
        "page": 1,
        "num": count,
        "sort": "opendate",
        "asc": 0,
        "daima": _to_sina_symbol(stock_code),
    }
    try:
        async with httpx.AsyncClient(
            trust_env=False, timeout=BEHAVIOR_FUND_FLOW_TIMEOUT_SEC
        ) as client:
            resp = await client.get(
                SINA_FLOW_DAILY_URL, params=params, headers=_HEADERS
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise FundFlowUnavailable(f"新浪逐日资金流请求失败: {e}") from e
    except ValueError as e:
        raise FundFlowUnavailable(f"新浪逐日资金流返回非 JSON: {e}") from e

    if not isinstance(data, list):
        raise FundFlowUnavailable(
            f"新浪逐日资金流返回非 list: {type(data).__name__}"
        )

    out: list[dict[str, Any]] = []
    for row in data:
        parsed = _parse_row(row)
        if parsed:
            out.append(parsed)
    return out


def _last_trading_day(now: datetime | None = None) -> date:
    """最近一个交易日(仅跳过周末;节假日不特殊处理,与 kline_service 同口径)。"""
    now = now or datetime.now()
    d = now.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _is_post_close(now: datetime | None = None) -> bool:
    """是否已收盘(与 kline_service 同口径:工作日 15:00 后 / 周末)。"""
    now = now or datetime.now()
    if now.weekday() >= 5:
        return True
    return now.hour >= 15


async def fetch_flow_daily(
    stock_code: str,
    count: int = 120,
    *,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """取个股逐日资金流(DB 优先 → miss 拉真实接口 → 回填落库)。

    Returns: 解析后的行列表,**按日期升序**(便于与日 K 对齐)。

    Raises:
        FundFlowUnavailable: 真实接口不可用且缓存也不足时抛出。
    """
    if use_cache:
        cached = await _load_cached(stock_code, count)
        if cached and not _needs_refresh(cached):
            return cached

    rows = await _fetch_sina_flow_daily(stock_code, count)
    if not rows:
        raise FundFlowUnavailable(f"新浪逐日资金流返回空数据: {stock_code}")

    # 接口是降序 → 统一转升序
    rows.sort(key=lambda r: r["date"])

    if use_cache:
        await _save_cached(stock_code, rows)
    return rows


async def _load_cached(stock_code: str, count: int) -> list[dict[str, Any]]:
    """从 DB 读已缓存的逐日资金流(升序)。"""
    from app.db import async_session
    from app.models.orm import FundFlowDailyCache
    from sqlalchemy import select

    async with async_session() as session:
        stmt = (
            select(FundFlowDailyCache)
            .where(FundFlowDailyCache.stock_code == stock_code)
            .order_by(FundFlowDailyCache.trade_date.desc())
            .limit(count)
        )
        rows = list((await session.execute(stmt)).scalars().all())

    out: list[dict[str, Any]] = []
    for r in reversed(rows):  # 反转成升序
        out.append(
            {
                "date": r.trade_date.isoformat(),
                "net_amount": _f(r.net_amount),
                "r0_net": _f(r.r0_net),
                "r0x_ratio": _f(r.r0x_ratio),
                "r0_ratio": _f(r.r0_ratio),
                "turnover": _f(r.turnover),
                "change_ratio": _f(r.change_ratio),
            }
        )
    return out


def _needs_refresh(cached: list[dict[str, Any]]) -> bool:
    """缓存是否需要重拉(收盘后当日数据会变 → 强制重拉;口径同 KlineCache)。"""
    if not cached:
        return True
    latest = cached[-1].get("date") or ""
    if not latest:
        return True
    try:
        latest_date = datetime.strptime(latest, "%Y-%m-%d").date()
    except ValueError:
        return True
    return bool(_is_post_close() and latest_date < _last_trading_day())


async def _save_cached(stock_code: str, rows: list[dict[str, Any]]) -> None:
    """回填落库(先按 stock_code 整段删除再重插,与 KlineCache 同策略)。"""
    from app.db import async_session
    from app.models.orm import FundFlowDailyCache
    from sqlalchemy import delete as sa_delete

    async with async_session() as session:
        await session.execute(
            sa_delete(FundFlowDailyCache).where(
                FundFlowDailyCache.stock_code == stock_code
            )
        )
        for r in rows:
            try:
                d = datetime.strptime(r["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            session.add(
                FundFlowDailyCache(
                    stock_code=stock_code,
                    trade_date=d,
                    net_amount=str(r.get("net_amount") or 0),
                    r0_net=str(r.get("r0_net") or 0),
                    r0x_ratio=(
                        None if r.get("r0x_ratio") is None else str(r["r0x_ratio"])
                    ),
                    r0_ratio=(None if r.get("r0_ratio") is None else str(r["r0_ratio"])),
                    turnover=(None if r.get("turnover") is None else str(r["turnover"])),
                    change_ratio=(
                        None if r.get("change_ratio") is None else str(r["change_ratio"])
                    ),
                    source="sina",
                )
            )
        await session.commit()


def align_by_date(
    flows: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """把逐日资金流列表转成 `{date: row}` 字典(**按日期对齐的唯一入口**)。

    ⚠️ 调用方**绝不要**按索引把资金流与 K 线 zip —— 两者排序方向相反,
    按索引对齐会整体错位一天(静默错误)。
    """
    out: dict[str, dict[str, Any]] = {}
    for r in flows or []:
        if not isinstance(r, dict):
            continue
        d = str(r.get("date") or "").strip()
        if not d:
            continue
        out[d] = r
    return out


__all__ = [
    "SINA_FLOW_DAILY_URL",
    "FundFlowUnavailable",
    "align_by_date",
    "fetch_flow_daily",
]
