"""真实交易日历(纯逻辑层 · 零业务依赖)

**为什么放在 core 而不是 services**:core 是基础设施层,架构守卫
(`tests/test_architecture_boundaries.py::test_core_does_not_depend_on_business_layers`)
禁止 core 反向依赖 services / repositories / models / data。所以本模块
**不 import 任何业务层** —— 「上证指数日 K → 交易日集合」这一步由
`app/services/trading_calendar_service.py` 以**数据源回调**的形式注入。

**真源**:上证指数 `000001.SH` 的真实日 K 日期集合 —— **有 K 线的日期 = 真实交易日**,
法定节假日自动正确(节假日不会有 K 线)。

**降级**:数据源不可用 / 异常 → 回落 `weekday() < 5`,并把 `estimated=True` +
`source="weekday_fallback"` 显式带出去,同时打一条 warning 日志。
**绝不静默假装是准确交易日。**

**纯函数边界**:
- `is_trading_day_in(days, d)` / `next_trading_day_in(days, d)`:只吃「已准备好的
  交易日集合」,零 IO —— 单测不需要打桩网络。
- `is_trading_day(d)` / `next_trading_day(d)` / `trading_days_hint()`:读进程内
  已准备好的日历缓存,同样零 IO。
- 唯一的 IO 入口是 `load_trading_calendar(source)`。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.logging import logger

# 数据源可用 → 真实交易日集合
SOURCE_INDEX_KLINE = "index_kline"
# 数据源不可用 → 回落工作日推算
SOURCE_WEEKDAY_FALLBACK = "weekday_fallback"

# 数据源回调:返回 ISO 日期字符串(可迭代)
DaySource = Callable[[], Awaitable[Iterable[str]]]


def _is_weekday(d: date) -> bool:
    """工作日(不含法定节假日 —— 那是数据源失效时的降级口径)"""
    return d.weekday() < 5


def _next_weekday_after(d: date) -> date:
    """d 之后的第一个工作日(周末顺延;法定节假日无法感知,故为降级口径)"""
    cur = d + timedelta(days=1)
    while not _is_weekday(cur):
        cur += timedelta(days=1)
    return cur


def _prev_weekday_on_or_before(d: date) -> date:
    """d 当天或之前最近的工作日"""
    cur = d
    while not _is_weekday(cur):
        cur -= timedelta(days=1)
    return cur


# ============================ 纯函数核心 ============================

def is_trading_day_in(trading_days: Iterable[date], d: date) -> bool:
    """纯函数:给定**已准备好的**交易日集合,判定 `d` 是否交易日。零 IO。

    判定顺序:
    1. 集合为空(数据源故障)→ 回落工作日推算;
    2. `d` 在集合里 → True(有 K 线 = 真实交易日);
    3. `d` 早于集合最新日期 → False(集合覆盖到的历史里没有它 = 那天没有 K 线
       = 非交易日,**含法定节假日**);
    4. `d` 晚于集合最新日期 → 真实数据尚未覆盖到(盘中当日日 K 未定格)→
       回落工作日推算。
    """
    days = trading_days if isinstance(trading_days, frozenset) else frozenset(trading_days)
    if not days:
        return _is_weekday(d)
    if d in days:
        return True
    if d < max(days):
        return False
    return _is_weekday(d)


def next_trading_day_in(trading_days: Iterable[date], d: date) -> date:
    """纯函数:`d` **之后**的第一个交易日。零 IO。

    - 集合为空 → 工作日顺延;
    - 集合覆盖范围内 → 取集合里 `d` 之后的第一个日期;
    - 超出覆盖范围 → 工作日顺延。
    """
    days = trading_days if isinstance(trading_days, frozenset) else frozenset(trading_days)
    if not days:
        return _next_weekday_after(d)
    latest = max(days)
    cur = d + timedelta(days=1)
    while cur <= latest:
        if cur in days:
            return cur
        cur += timedelta(days=1)
    # 走完了真实覆盖范围(中间没有任何交易日)→ 工作日顺延
    return _next_weekday_after(cur - timedelta(days=1))


# ============================ 日历对象 ============================

@dataclass(frozen=True)
class TradingCalendar:
    """一份已准备好的交易日历(不可变快照)。"""

    source: str
    estimated: bool
    trading_days: frozenset[date]
    coverage_until: date | None
    loaded_on: date
    reason: str | None = None

    def is_trading_day(self, d: date) -> bool:
        return is_trading_day_in(self.trading_days, d)

    def next_trading_day(self, d: date) -> date:
        return next_trading_day_in(self.trading_days, d)

    def covers(self, d: date) -> bool:
        """真实数据是否覆盖到 `d`(含)。"""
        return self.coverage_until is not None and d <= self.coverage_until

    def last_confirmed_trade_date(self) -> date | None:
        """最近一个**已确认**的交易日(集合里最大日期)。"""
        return max(self.trading_days) if self.trading_days else None


# ============================ 进程内缓存 ============================

_calendar: TradingCalendar | None = None


def _parse_days(raw: Iterable[str] | None) -> frozenset[date]:
    out: set[date] = set()
    for item in raw or []:
        s = str(item or "")[:10]
        if not s:
            continue
        try:
            out.add(date.fromisoformat(s))
        except ValueError:
            continue
    return frozenset(out)


async def load_trading_calendar(
    source: DaySource | None = None, *, force: bool = False
) -> TradingCalendar:
    """**唯一的 IO 入口**:取真实交易日集合并按日缓存。

    - `source` 返回 ISO 日期字符串序列(真实日 K 的日期);
    - 失败 / 空集合 → 回落工作日推算,`estimated=True` + `source="weekday_fallback"`
      + 一条 warning 日志;
    - 同一天内重复调用直接命中缓存(`force=True` 可强制重取)。
    """
    global _calendar

    today = date.today()
    if _calendar is not None and not force and _calendar.loaded_on == today:
        return _calendar

    days: frozenset[date] = frozenset()
    reason: str | None = None
    if source is None:
        reason = "未注册交易日数据源"
    else:
        try:
            days = _parse_days(await source())
        except Exception as e:  # noqa: BLE001 — 任何失败都必须降级而不是崩
            reason = f"交易日数据源异常: {e}"
            days = frozenset()
        if not days and reason is None:
            reason = "交易日数据源返回空日期集合"

    if days:
        cal = TradingCalendar(
            source=SOURCE_INDEX_KLINE,
            estimated=False,
            trading_days=days,
            coverage_until=max(days),
            loaded_on=today,
            reason=None,
        )
        logger.info(
            f"[trading_calendar] 交易日历已加载: 真实交易日 {len(days)} 天, 覆盖至 {cal.coverage_until}"
        )
    else:
        cal = TradingCalendar(
            source=SOURCE_WEEKDAY_FALLBACK,
            estimated=True,
            trading_days=frozenset(),
            coverage_until=None,
            loaded_on=today,
            reason=reason,
        )
        logger.warning(
            f"[trading_calendar] 交易日数据源不可用,回落工作日推算(estimated=True): {reason}"
        )

    _calendar = cal
    return cal


def current_calendar() -> TradingCalendar:
    """当前进程内已准备好的日历(尚未加载 → 工作日降级,estimated=True)。"""
    if _calendar is not None:
        return _calendar
    return TradingCalendar(
        source=SOURCE_WEEKDAY_FALLBACK,
        estimated=True,
        trading_days=frozenset(),
        coverage_until=None,
        loaded_on=date.today(),
        reason="尚未加载交易日历",
    )


def is_trading_day(d: date) -> bool:
    """`d` 是否交易日(读已准备好的日历,零 IO)。"""
    return current_calendar().is_trading_day(d)


def next_trading_day(d: date) -> date:
    """`d` 之后的第一个交易日(读已准备好的日历,零 IO)。"""
    return current_calendar().next_trading_day(d)


def trading_days_hint() -> dict:
    """交易日历来源提示(零 IO)。

    - `source`: `index_kline`(真实日 K 集合) | `weekday_fallback`(数据源不可用)
    - `estimated`: 今天的判定是否**含推算** —— 数据源故障,或真实数据尚未覆盖到今天
      (盘中当日日 K 未定格)。为 True 时**不得**对外宣称「今天是交易日」这件事是准确的。
    - `trade_date`: 最近一个**已确认**的交易日(降级口径下为最近的工作日)。
    """
    cal = current_calendar()
    today = date.today()
    confirmed = cal.last_confirmed_trade_date()
    if confirmed is None:
        trade_date = _prev_weekday_on_or_before(today)
    else:
        trade_date = confirmed
    return {
        "source": cal.source,
        "estimated": bool(cal.estimated) or not cal.covers(today),
        "trade_date": trade_date.isoformat(),
    }


def reset_trading_calendar() -> None:
    """清空进程内缓存(单测用)。"""
    global _calendar
    _calendar = None


__all__ = [
    "DaySource",
    "SOURCE_INDEX_KLINE",
    "SOURCE_WEEKDAY_FALLBACK",
    "TradingCalendar",
    "current_calendar",
    "is_trading_day",
    "is_trading_day_in",
    "load_trading_calendar",
    "next_trading_day",
    "next_trading_day_in",
    "reset_trading_calendar",
    "trading_days_hint",
]
