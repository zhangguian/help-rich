"""三段式 Agent 调度器(阶段4)。

时间窗(工作日):
- 08:30–08:59  → 盘前简报
- 11:30–11:59  → 盘中速览(上午收盘)
- 14:50–14:59  → 盘中速览(尾盘)
- 16:00–16:59  → 盘后复盘提示

**幂等**:每个时间窗当天只跑一次。进程内用内存集合记录已触发的时间窗键;
即使重启,最坏情况是多跑一次(有幂等快照保护),不会重复轰炸。
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
    ("intraday_pm", 14, 50, 59),
    ("postmarket", 16, 0, 59),
]

SLOT_LABEL = {
    "premarket": "08:30",
    "intraday_am": "11:30",
    "intraday_pm": "14:50",
    "postmarket": "16:00",
}

_fired: set[str] = set()


def _window_key(kind: str, now: datetime) -> str:
    return f"{now.date().isoformat()}:{kind}"


def due_windows(now: datetime) -> list[str]:
    """返回此刻应触发的、且当天尚未触发过的窗口 kind 列表。"""
    if now.weekday() >= 5:  # 周末不跑
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
    from app.modules.analysis.workflow import workflow_agent_service

    try:
        if kind == "premarket":
            result = await workflow_agent_service.run_premarket()
        elif kind == "intraday_am":
            result = await workflow_agent_service.run_intraday("11:30")
        elif kind == "intraday_pm":
            result = await workflow_agent_service.run_intraday("14:50")
        else:  # postmarket
            return  # 盘后由选股调度器 + 复盘模块覆盖,这里不重复跑
        await workflow_agent_service.dispatch(result)
        logger.info(f"[workflow] {kind} 完成({SLOT_LABEL.get(kind, kind)})")
    except Exception as e:  # noqa: BLE001 — 任何失败都不能杀死循环
        logger.warning(f"[workflow] {kind} 执行失败: {e}")


async def start_workflow_scheduler(interval_sec: int = 60) -> None:
    """常驻调度循环。"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # 测试环境不启动

    logger.info(f"[workflow] 三段式 Agent 调度器启动,间隔 {interval_sec}s")
    try:
        while True:
            now = datetime.now()
            for kind in due_windows(now):
                await _run_window(kind)
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        logger.info("[workflow] 调度器已停止")
        raise


__all__ = ["SLOT_LABEL", "TIME_WINDOWS", "due_windows", "reset_fired", "start_workflow_scheduler"]
