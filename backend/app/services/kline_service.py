"""K 线图服务(guide §3.2 新浪备用)

- 数据源:guide §3.2 新浪 K 线 JSONP(`https://quotes.sina.cn/.../CN_MarketDataService.getKLineData`)
- 测试 ✅ 200(2026-08-01 实测)
- 其他数据源(guide §3.1 东财 push2his、§3.3 腾讯 web.ifzq)实测被公司网络封,跳过
- **完全真实数据**,无 mock;失败抛 KLineSourceUnavailable
"""
import json
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class KLineSourceUnavailable(Exception):
    """K 线数据源不可用(网络/接口变更/反爬)"""


def _to_sina_symbol(stock_code: str) -> str:
    """guide §1.1:600519.SH → sh600519"""
    code, _, market = stock_code.partition(".")
    market = market.lower() if market else "sh"
    market = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(market.upper(), market.lower())
    return f"{market}{code}"


def _to_sina_scale(period: str) -> int:
    """guide §1.3 scale 编码"""
    return {
        "1min": 1, "5min": 5, "15min": 15, "30min": 30, "60min": 60,
        "daily": 240, "weekly": 1200, "monthly": 1440,
    }.get(period, 240)


def _dedupe_asc(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 date 升序去重:避免 DB 重复行 / 新浪偶发同日多值污染客户端

    首个出现的胜出(后到的同名丢弃),保证行情/指标序列稳定。
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in sorted(rows, key=lambda x: x["date"]):
        d = r["date"]
        if d in seen:
            continue
        seen.add(d)
        out.append(r)
    return out


async def _fetch_sina_kline(
    stock_code: str, period: str, count: int, keep_time: bool = False
) -> list[dict[str, Any]]:
    """guide §3.2 新浪 K 线(JSONP,需剥壳)

    返回:[
      {date, open, high, low, close, volume, amount}
    ] 升序
    keep_time=True:日/时上保留完整秒级时间戳(如 "2026-07-30 14:57:00"),
    供分时图使用;否则分钟级降级为仅日期。
    """
    import time
    import random

    symbol = _to_sina_symbol(stock_code)
    scale = _to_sina_scale(period)
    callback = f"callback_{int(time.time() * 1000)}{random.randint(0, 999)}"
    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/{callback}/CN_MarketDataService.getKLineData"
    params = {
        "symbol": symbol,
        "scale": scale,
        "ma": "no",
        "datalen": count,
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn",
    }
    async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        text = resp.text

    # JSONP 剥壳:callback_xxx([...]);
    m = re.search(r"\((.*)\)\s*;?\s*$", text, re.DOTALL)
    if not m:
        raise KLineSourceUnavailable(f"新浪 K 线返回非 JSONP 格式: {text[:200]}")
    json_text = m.group(1)
    try:
        rows = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise KLineSourceUnavailable(f"新浪 K 线 JSON 解析失败: {e}") from e
    if not isinstance(rows, list) or not rows:
        raise KLineSourceUnavailable(
            f"新浪 K 线返回空(可能接口已变更 / {stock_code} 无 K 线)"
        )

    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        # 字段映射(guide §3.2:day/open/high/low/close/volume)
        day = r.get("day") or r.get("datalabel") or r.get("date")
        if not day:
            continue
        # 分钟级 day 是 "2026-07-30 09:30:00"-格式
        if not keep_time and " " in day:
            day = day.split(" ")[0]
        out.append({
            "date": day,
            "open": r.get("open", "0"),
            "high": r.get("high", "0"),
            "low": r.get("low", "0"),
            "close": r.get("close", "0"),
            "volume": int(r.get("volume", 0) or 0),
            "amount": r.get("amount", "0"),
        })
    return out


async def fetch_intraday(stock_code: str) -> dict[str, Any]:
    """当日分时数据(新浪 scale=1 分钟线聚合)

    分时接口返回分钟级原始 OHLCV,本函数聚合成分时点:
      - time: "HH:MM"
      - price: 该分钟收盘价(近似最新价)
      - avg_price: 自开盘累计成交额 / 累计成交量(均价线)
      - volume: 该分钟成交量
      - prev_close: 昨收(分时图黄色虚线基准)

    当日未开盘/停牌 → ? 返回空 items + prev_close=None;数据源异常抛 KLineSourceUnavailable。
    """
    # 1. 昨收:拉日K,最后一日不是分时当日→取最后一根;否则取前一根(盘中可能含当日)
    #    日K接口兜底,失败不阻断分时(prev_close=None 前端降级)
    prev_close: str | None = None
    try:
        daily = await _fetch_sina_kline(stock_code, "daily", 5)
    except KLineSourceUnavailable:
        daily = []

    # 2. 分时分钟线(保留 HH:MM:SS)
    try:
        rows = await _fetch_sina_kline(stock_code, "1min", 260, keep_time=True)
    except KLineSourceUnavailable:
        rows = []
    if not rows:
        # 数据源失败但可能只是分钟接口限流,抛异常由 API 统一 502
        raise KLineSourceUnavailable(f"新浪分时返回空数据: {stock_code}")

    # 3. 取最后一个交易日(rows 升序,末尾即最新)
    last_day = rows[-1]["date"].split(" ")[0]
    # 过滤出当天的分钟
    mins = [r for r in rows if r["date"].startswith(last_day + " ")]

    # 昨收:取最后一个不属于分时当日的日线 close(盘中日线可能已含今日)
    if daily:
        for d in reversed(daily):
            if not d["date"].startswith(last_day):
                prev_close = d["close"]
                break

    items: list[dict[str, Any]] = []
    cum_vol = 0
    cum_amt = 0.0
    for r in mins:
        try:
            vol = int(r["volume"])
            amt = float(r["amount"] or 0)
        except (ValueError, TypeError):
            vol, amt = 0, 0.0
        cum_vol += vol
        cum_amt += amt
        avg_price = round(cum_amt / cum_vol, 3) if cum_vol else None
        price = float(r["close"])
        items.append({
            "time": r["date"].split(" ")[1][:5],
            "price": price,
            "avg_price": avg_price,
            "volume": vol,
        })

    return {
        "stock_code": stock_code,
        "date": last_day,
        "prev_close": prev_close,
        "count": len(items),
        "items": items,
    }


async def fetch_klines(
    stock_code: str, period: str = "daily", count: int = 60
) -> list[dict[str, Any]]:
    """拉 K 线(guide §3.2 新浪;数据源失败抛 KLineSourceUnavailable,不兜底 mock)

    缓存层:DB 优先,miss 调真实接口,落库
    """
    from app.db import async_session
    from app.models.orm import KlineCache
    from sqlalchemy import select

    # 1. 缓存优先
    async with async_session() as session:
        stmt = (
            select(KlineCache)
            .where(
                KlineCache.stock_code == stock_code,
                KlineCache.period == period,
            )
            .order_by(KlineCache.trade_date.desc())
            .limit(count)
        )
        cached = list((await session.execute(stmt)).scalars().all())

    if len(cached) >= count:
        logger.debug("K 线缓存命中: %s %s (%d 根)", stock_code, period, len(cached))
        rows = [
            {
                "date": r.trade_date.isoformat(),
                "open": r.open_price,
                "high": r.high_price,
                "low": r.low_price,
                "close": r.close_price,
                "volume": r.volume,
            }
            for r in reversed(cached)
        ]
        return _dedupe_asc(rows)

    # 2. 真实接口(失败抛 KLineSourceUnavailable,无 mock)
    rows = await _fetch_sina_kline(stock_code, period, count)
    if not rows:
        raise KLineSourceUnavailable(f"新浪 K 线返回空数据: {stock_code}")
    rows = _dedupe_asc(rows)

    # 3. 落库
    async with async_session() as session:
        for r in rows:
            try:
                d = (
                    datetime.strptime(r["date"], "%Y-%m-%d").date()
                    if " " not in r["date"]
                    else datetime.strptime(r["date"], "%Y-%m-%d %H:%M").date()
                )
            except ValueError:
                continue
            session.add(
                KlineCache(
                    stock_code=stock_code,
                    trade_date=d,
                    period=period,
                    open_price=r["open"],
                    high_price=r["high"],
                    low_price=r["low"],
                    close_price=r["close"],
                    volume=r["volume"],
                    source="sina",
                )
            )
        await session.commit()
    logger.info("K 线新浪落库: %s %s (%d 根)", stock_code, period, len(rows))
    return rows


__all__ = ["fetch_klines", "fetch_intraday", "KLineSourceUnavailable"]