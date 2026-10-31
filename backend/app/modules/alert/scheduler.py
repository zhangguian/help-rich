"""价格提醒调度器(阶段1)。

轮询所有启用规则 → 拉实时行情 → 求值 → 命中则推送。
默认 60s 一轮(与现有资金流调度器同频);非交易时段自动跳过,避免无谓请求。

单独成模块而不是塞进 quote 调度器:提醒是"独立可选能力"，
关掉不影响盯盘主流程。
"""
from __future__ import annotations

import asyncio

from app.core.logging import logger
from app.core.trading_time import is_trading_time
from app.modules.alert.engine import AlertContext
from app.modules.alert.service import price_alert_service

INTERVAL_SEC = 60


def _is_trading_time() -> bool:
    """盘中时段判断。

    实现已上提到 `app/core/trading_time.py` —— 秒级盯盘轮询器
    (`app/services/quote_poller.py`)需要**同一份**口径,两处各写一份必然漂移。
    这里保留同名薄封装,避免改动本模块其余调用点。
    """
    return is_trading_time()


async def _scan_once() -> int:
    """扫描一轮,返回触发条数。"""
    from app.modules.alert.repository import price_alert_repo
    from app.services.quote_service import get_quote_service

    alerts = await price_alert_repo.list_enabled_active()
    if not alerts:
        return 0

    codes = list({a.stock_code for a in alerts})
    # 复用进程级单例:每次 new 一个 QuoteService 会重建 httpx 连接池,
    # 连接既不复用、缓存也各算各的(2026-10-29 秒级盯盘改造时顺带修掉)。
    quote_svc = get_quote_service()
    contexts: dict[str, AlertContext] = {}
    try:
        # ⚠️ 必须走 **fresh 路径**(跳过 5 分钟缓存):
        # 价格提醒的价值全在"及时" —— 用缓存价判触达,最多会晚 5 分钟才响。
        quotes = await quote_svc.get_quotes_fresh(codes)
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
