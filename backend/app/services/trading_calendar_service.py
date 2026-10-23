"""交易日历的真实数据源接线(services 层)

**为什么单独一层**:core 层不允许 import 业务层(架构守卫
`tests/test_architecture_boundaries.py::test_core_does_not_depend_on_business_layers`),
所以「上证指数真实日 K → 交易日集合」这一步放在这里,以**数据源回调**注入 core。

真源:上证指数 `000001.SH` 的真实日 K 日期集合 —— **有 K 线的日期 = 真实交易日**,
法定节假日自动正确(节假日不会有 K 线)。

降级:K 线拉不到 / 异常 → core 侧回落 `weekday() < 5`,并显式带出
`estimated=True` + `source="weekday_fallback"` + warning 日志。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.core.trading_calendar import (
    TradingCalendar,
    is_trading_day,
    load_trading_calendar,
    next_trading_day,
    trading_days_hint,
)
from app.services.kline_service import fetch_klines

INDEX_CODE = "000001.SH"
# 近 2 年日 K(约 480 个交易日):足够覆盖所有法定节假日(最长长假约 9 天)
INDEX_KLINE_COUNT = 500


async def _fetch_index_trading_days() -> list[str]:
    """取上证指数真实日 K 的日期集合(升序 ISO 日期字符串)"""
    klines = await fetch_klines(INDEX_CODE, period="daily", count=INDEX_KLINE_COUNT)
    return [str(k.get("date"))[:10] for k in (klines or []) if k.get("date")]


async def ensure_trading_calendar(force: bool = False) -> TradingCalendar:
    """确保交易日历已加载(进程内按日缓存);失败自动降级并标 estimated。"""
    return await load_trading_calendar(_fetch_index_trading_days, force=force)


async def trading_day_meta(target: date | None = None) -> dict[str, Any]:
    """当日交易日元信息(供产出物 / API 标注用)。

    - `is_trading_day`: `target` 是否交易日;
    - `trade_date_source`: `index_kline` | `weekday_fallback`;
    - `trading_day_estimated`: 判定是否含推算(数据源故障,或真实数据尚未覆盖到今天);
    - `trade_date`: 最近一个已确认的交易日。
    """
    await ensure_trading_calendar()
    hint = trading_days_hint()
    d = target or date.today()
    return {
        "is_trading_day": is_trading_day(d),
        "trade_date_source": hint.get("source"),
        "trading_day_estimated": bool(hint.get("estimated")),
        "trade_date": hint.get("trade_date"),
    }


__all__ = [
    "INDEX_CODE",
    "INDEX_KLINE_COUNT",
    "ensure_trading_calendar",
    "is_trading_day",
    "next_trading_day",
    "trading_day_meta",
    "trading_days_hint",
]
