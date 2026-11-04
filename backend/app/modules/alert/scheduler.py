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


def _to_float(value: object) -> float | None:
    """转 float;非有限值(NaN / ±inf)与转换失败一律当**无效**(None)。

    与 `services/intraday_advice._f` / `stock_pool.pool_logic._f` 同一口径:
    只滤 NaN 不滤 ±inf 会出**假触及** —— ±inf <= 阈值 恒成立。
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


async def _scan_once() -> int:
    """扫描一轮,返回触发条数。"""
    from app.modules.alert.repository import price_alert_repo
    from app.services.quote_service import get_quote_service

    alerts = await price_alert_repo.list_enabled_active()
    # 已停用的预警提醒也要拉行情 —— 判断「价格是否已离开预警区」需要现价,
    # 否则页面关着时预警就只响一次,再也不武装。
    codes = {a.stock_code for a in alerts}
    codes |= await price_alert_service.pre_alert_codes()
    if not codes:
        return 0

    # 复用进程级单例:每次 new 一个 QuoteService 会重建 httpx 连接池,
    # 连接既不复用、缓存也各算各的(2026-10-29 秒级盯盘改造时顺带修掉)。
    quote_svc = get_quote_service()
    contexts: dict[str, AlertContext] = {}
    try:
        # ⚠️ 必须走 **fresh 路径**(跳过 5 分钟缓存):
        # 价格提醒的价值全在"及时" —— 用缓存价判触达,最多会晚 5 分钟才响。
        quotes = await quote_svc.get_quotes_fresh(list(codes))
    except Exception as e:  # noqa: BLE001 — 行情失败就跳过本轮
        logger.warning(f"[price-alert] 行情拉取失败,本轮跳过: {e}")
        return 0

    # ⚠️ **必须过滤无效行情** —— 开盘瞬间(09:15 集合竞价)数据源会返回
    # `price=0.0, change_pct=-100.0` 这种占位值。若原样喂给求值器:
    # 「价格 <= X」类提醒会因 `0.0 <= X` 恒成立而**假触发**(09:15 已误响过 3 条)。
    # 项目口径「行情取不到 = null,不编数据」:无效价 = 该标的本轮**不评估**,
    # 与 `data/market_snapshot.py` 的 `price <= 0 → 跳过` 同源。
    invalid: list[str] = []
    for q in quotes:
        price = _to_float(q.current_price)
        if price is None or price <= 0:
            invalid.append(q.code)
            continue
        change_pct = _to_float(q.change_pct)
        # 涨跌幅缺失时按 None 处理(对应条件判 False),不拿 0 顶替
        contexts[q.code] = AlertContext(
            price=price,
            change_pct=change_pct,
            turnover=_to_float(q.turnover_pct),
        )
    if invalid:
        logger.warning(
            f"[price-alert] 行情无效(price<=0/非数字),本轮跳过 {len(invalid)} 只: "
            f"{','.join(invalid)}"
        )
    fired = await price_alert_service.scan(contexts)
    # 预警重新武装放在调度器里 —— 页面关着也能继续提醒
    rearmed = await price_alert_service.rearm_pre_alerts(contexts)
    if rearmed:
        logger.info(f"[price-alert] 预警重新武装 {rearmed} 条")
    return fired


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
