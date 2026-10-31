"""盘中时段判断(纯逻辑层 · 零业务依赖)

**为什么放在 core**:同一份"现在是不是盘中"的口径要同时服务两处 ——
`modules/alert/scheduler.py`(价格提醒扫描)与 `services/quote_poller.py`(秒级盯盘轮询)。
core 是基础设施层,不 import 任何业务层;架构守卫允许 `services → core` 的依赖方向
(`tests/test_architecture_boundaries.py::test_layers_never_import_outward`)。

**口径**(与原 `modules/alert/scheduler.py::_is_trading_time` 完全一致,只是上提到 core):
- 工作日 9:15-11:35 / 12:55-15:10
- **不含法定节假日**:项目没有节假日日历,宁可多跑几轮也不漏提醒 / 不漏行情。

**与 `app/core/trading_calendar.py` 的分工**:
- `trading_calendar.py` 判的是"某**天**是不是交易日"(数据源驱动,有真实 K 线为证);
- 本模块判的是"此**刻**是否在盘中时段"(纯时钟,零 IO)。
两者互补,不重叠 —— 不要因为都有"trading"就合并。

**纯函数边界**:只吃 `datetime`,零 IO —— 单测不需要打桩网络,也不需要打桩时钟
(直接把 `now` 传进来即可)。
"""
from __future__ import annotations

from datetime import datetime, time as dtime

# 上午盘
MORNING_START = dtime(9, 15)
MORNING_END = dtime(11, 35)
# 下午盘
AFTERNOON_START = dtime(12, 55)
AFTERNOON_END = dtime(15, 10)


def is_trading_time(now: datetime | None = None) -> bool:
    """当前是否处于盘中时段(工作日 9:15-11:35 / 12:55-15:10)。

    Args:
        now: 传入即用传入值(单测可固定时刻);省略则取当前时间。

    Returns:
        True = 盘中;False = 周末 / 午休 / 盘前盘后。
    """
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    t = now.time()
    return (
        MORNING_START <= t <= MORNING_END
        or AFTERNOON_START <= t <= AFTERNOON_END
    )


__all__ = [
    "is_trading_time",
    "MORNING_START",
    "MORNING_END",
    "AFTERNOON_START",
    "AFTERNOON_END",
]
