"""模拟盘净值快照调度器(阶段3)。

每天收盘后(15:35)为每个模拟账户记一条净值快照,供净值曲线与绩效指标使用。
独立于选股/提醒调度器:即便那些关了,净值曲线也该继续记录。
"""
from __future__ import annotations

import asyncio

from app.core.logging import logger
from app.modules.paper_trading.repository import paper_trading_repo
from app.modules.paper_trading.service import paper_trading_service

# 收盘后 35 分钟(等日 K 定格)
SNAPSHOT_HOUR = 15
SNAPSHOT_MINUTE = 35


def _should_snapshot(now=None) -> bool:
    """交易日 15:35~23:59 之间每小时触发一次即可(幂等 upsert,重复写同一天无害)。"""
    from datetime import datetime

    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    return now.hour > SNAPSHOT_HOUR or (
        now.hour == SNAPSHOT_HOUR and now.minute >= SNAPSHOT_MINUTE
    )


async def _snapshot_all() -> int:
    accounts = await paper_trading_repo.list_accounts()
    count = 0
    for acc in accounts:
        try:
            await paper_trading_service.snapshot_equity(acc.id)
            count += 1
        except Exception as e:  # noqa: BLE001 — 单账户失败不影响其它
            logger.warning(f"[paper] 账户 {acc.id} 净值快照失败: {e}")
    return count


async def start_paper_scheduler(interval_sec: int = 1800) -> None:
    """常驻循环(默认 30 分钟检查一次是否到收盘快照时间)。"""
    logger.info(f"[paper] 净值快照调度器启动,间隔 {interval_sec}s")
    try:
        while True:
            if _should_snapshot():
                try:
                    n = await _snapshot_all()
                    if n:
                        logger.info(f"[paper] 已记录 {n} 个账户的净值快照")
                except Exception as e:  # noqa: BLE001 — 循环必须活着
                    logger.warning(f"[paper] 快照异常(继续): {e}")
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        logger.info("[paper] 调度器已停止")
        raise


__all__ = ["start_paper_scheduler"]
