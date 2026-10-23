"""三段式 Agent 调度器(阶段4 · 阶段 T2 改造)

时间窗(交易日):
- 08:30–08:59  → 盘前简报
- 11:30–11:59  → 盘中复盘(上午收盘)
- 14:00–14:29  → 盘中复盘(下午盘初)
- 16:00–16:59  → 盘后复盘提示

**幂等**:每个时间窗当天只跑一次。进程内用内存集合记录已触发的时间窗键;
即使重启,最坏情况是多跑一次(有幂等快照保护),不会重复轰炸。

**交易日判定**(阶段 T1):用 `core/trading_calendar`(上证指数真实日 K 的日期集合),
法定节假日不跑。数据源故障回落工作日时**仍然跑**,但记 warning,且产出里带
`estimated` 标记 —— 绝不静默假装是准确交易日。
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime

from app.core.logging import logger

# (kind, hour, minute, end_minute)
TIME_WINDOWS = [
    ("premarket", 8, 30, 59),
    ("intraday_am", 11, 30, 59),
    ("intraday_pm", 14, 0, 29),
    ("postmarket", 16, 0, 59),
]

SLOT_LABEL = {
    "premarket": "08:30",
    "intraday_am": "11:30",
    "intraday_pm": "14:00",
    "postmarket": "16:00",
}

# 盘中窗口 → 复盘档位(阶段 T2:盘中主产出改为「盘中复盘」)
REVIEW_SLOT = {
    "intraday_am": "11:30",
    "intraday_pm": "14:00",
}

_fired: set[str] = set()
# 「交易日判定含推算」的 warning 每天只打一次(调度器每 60s 醒一次,别刷屏)
_trading_warned_day: str | None = None


def _window_key(kind: str, now: datetime) -> str:
    return f"{now.date().isoformat()}:{kind}"


async def _is_trading_day(d: date) -> bool:
    """交易日判定(真实日 K 集合;数据源故障回落工作日 + warning)"""
    global _trading_warned_day

    from app.services.trading_calendar_service import ensure_trading_calendar
    from app.core.trading_calendar import is_trading_day, trading_days_hint

    await ensure_trading_calendar()
    hint = trading_days_hint()
    if hint.get("estimated") and _trading_warned_day != d.isoformat():
        _trading_warned_day = d.isoformat()
        logger.warning(
            f"[workflow] 交易日判定含推算(source={hint.get('source')}, "
            f"estimated=True): 今日按工作日处理,产出里会带 estimated 标记"
        )
    return is_trading_day(d)


async def due_windows(now: datetime) -> list[str]:
    """返回此刻应触发的、且当天尚未触发过的窗口 kind 列表。

    非交易日(含法定节假日)不触发。数据源故障回落工作日时仍会触发,但会记
    warning(见 `_is_trading_day`)。
    """
    if not await _is_trading_day(now.date()):
        return []
    out: list[str] = []
    for kind, hour, minute, end_minute in TIME_WINDOWS:
        if now.hour != hour or not (minute <= now.minute <= end_minute):
            continue
        key = _window_key(kind, now)
        if key in _fired:
            continue
        _fired.add(key)
        out.append(kind)
    return out


def reset_fired() -> None:
    """清空已触发记录(单测用)。"""
    _fired.clear()


async def _run_window(kind: str) -> None:
    if kind == "premarket":
        from app.modules.analysis.workflow import workflow_agent_service

        result = await workflow_agent_service.run_premarket()
        await workflow_agent_service.dispatch(result)
        logger.info(f"[workflow] {kind} 完成({SLOT_LABEL.get(kind, kind)})")
        return

    if kind in REVIEW_SLOT:
        from app.modules.analysis.intraday_review import (
            dispatch_intraday_review,
            run_intraday_review,
        )
        from app.services.trading_calendar_service import trading_day_meta

        slot = REVIEW_SLOT[kind]
        meta = await trading_day_meta()
        payload = await run_intraday_review(slot, trading_day=meta)
        await dispatch_intraday_review(payload)
        logger.info(
            f"[workflow] {kind} 完成({SLOT_LABEL.get(kind, kind)}): "
            f"动作 {len(payload.get('actions') or [])} 条"
        )
        return

    # postmarket:盘后由选股调度器 + 复盘模块覆盖,这里不重复跑
    return


async def start_workflow_scheduler(interval_sec: int = 60) -> None:
    """常驻调度循环。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # 测试环境不启动

    logger.info(f"[workflow] 三段式 Agent 调度器启动,间隔 {interval_sec}s")
    try:
        while True:
            now = datetime.now()
            for kind in await due_windows(now):
                await _run_window(kind)
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        logger.info("[workflow] 调度器已停止")
        raise


__all__ = [
    "REVIEW_SLOT",
    "SLOT_LABEL",
    "TIME_WINDOWS",
    "due_windows",
    "reset_fired",
    "start_workflow_scheduler",
]
