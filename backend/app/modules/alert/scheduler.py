"""价格提醒调度器(阶段1)。

轮询所有启用规则 → 拉实时行情 → 求值 → 命中则推送。
默认 60s 一轮(与现有资金流调度器同频);非交易时段自动跳过,避免无谓请求。

单独成模块而不是塞进 quote 调度器:提醒是"独立可选能力"，
关掉不影响盯盘主流程。
"""
from __future__ import annotations

import asyncio

from app.core.logging import logger
from app.modules.alert.engine import AlertContext
from app.modules.alert.service import price_alert_service

INTERVAL_SEC = 60


def _is_trading_time() -> bool:
    """粗粒度交易时段判断:工作日 9:15-11:35 / 12:55-15:10。

    不含法定节假日日历(现有项目也没有),宁可多跑几轮也不漏提醒。
    """
    from datetime import datetime, time as dtime

    now = datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    t = now.time()
    return (
        dtime(9, 15) <= t <= dtime(11, 35)
        or dtime(12, 55) <= t <= dtime(15, 10)
    )


async def _scan_once() -> int:
    """扫描一轮,返回触发条数。"""
    from app.modules.alert.repository import price_alert_repo
    from app.services.quote_service import QuoteService

    alerts = await price_alert_repo.list_enabled_active()
    if not alerts:
        return 0

    codes = list({a.stock_code for a in alerts})
    quote_svc = QuoteService()
    contexts: dict[str, AlertContext] = {}
    try:
        quotes = await quote_svc.get_quotes(codes)
    except Exception as e:  # noqa: BLE001 — 行情失败就跳过本轮
        logger.warning(f"[price-alert] 行情拉取失败,本轮跳过: {e}")
        return 0

    for q in quotes:
        contexts[q.code] = AlertContext(
            price=float(q.current_price),
            change_pct=float(q.change_pct),
            turnover=float(q.turnover_pct) if q.turnover_pct is not None else None,
        )
    return await price_alert_service.scan(contexts)


async def start_price_alert_scheduler(interval_sec: int = INTERVAL_SEC) -> None:
    """常驻轮询循环。由 main.py lifespan 启动。"""
    logger.info(f"[price-alert] 调度器启动,间隔 {interval_sec}s")
    try:
        while True:
            if _is_trading_time():
                try:
                    fired = await _scan_once()
                    if fired:
                        logger.info(f"[price-alert] 本轮触发 {fired} 条")
                except Exception as e:  # noqa: BLE001 — 循环必须活着
                    logger.warning(f"[price-alert] 扫描异常(继续): {e}")
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        logger.info("[price-alert] 调度器已停止")
        raise


__all__ = ["start_price_alert_scheduler"]
