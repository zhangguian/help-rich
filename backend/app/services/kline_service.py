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


async def _fetch_sina_kline(
    stock_code: str, period: str, count: int
) -> list[dict[str, Any]]:
    """guide §3.2 新浪 K 线(JSONP,需剥壳)

    返回:[
      {date, open, high, low, close, volume, turnover?}
    ] 升序
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
        # 分钟级 day 是 "2026-08-01 09:30" 格式
        if " " in day:
            day = day.split(" ")[0]
        out.append({
            "date": day,
            "open": r.get("open", "0"),
            "high": r.get("high", "0"),
            "low": r.get("low", "0"),
            "close": r.get("close", "0"),
            "volume": int(r.get("volume", 0) or 0),
        })
    return out


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
        return [
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

    # 2. 真实接口(失败抛 KLineSourceUnavailable,无 mock)
    rows = await _fetch_sina_kline(stock_code, period, count)
    if not rows:
        raise KLineSourceUnavailable(f"新浪 K 线返回空数据: {stock_code}")

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


__all__ = ["fetch_klines", "KLineSourceUnavailable"]