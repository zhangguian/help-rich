"""K 线图服务(D)

- MVP:首次请求 mock 生成 N 根日 K 线 + 落库(v0.2.1)
- v0.2.2:接 akshare/yahoo-finance2 真实数据源替换 mock
- 设计:缓存命中走 cache;miss 调 fetch_kline + 落库
"""
import logging
import math
import random
from datetime import date, timedelta
from decimal import Decimal

from app.db import async_session
from app.models.orm import KlineCache

logger = logging.getLogger(__name__)


def _mock_klines(stock_code: str, count: int = 60) -> list[dict]:
    """生成 mock 日 K 线(随机游走,基于代码哈希的"基础价")

    返回格式:
      [{date, open, high, low, close, volume}, ...]
    按日期升序。
    """
    # 用代码 hash 给每只股一个稳定的基础价(900-2000)
    base = 1000 + (hash(stock_code) % 1100)
    rng = random.Random(stock_code)  # 确定性 seed
    price = base
    today = date.today()
    rows = []
    for i in range(count):
        d = today - timedelta(days=count - 1 - i)
        # 日波动 ±3%
        change = rng.uniform(-0.03, 0.03)
        open_p = price
        close_p = max(0.01, price * (1 + change))
        high_p = max(open_p, close_p) * (1 + rng.uniform(0, 0.015))
        low_p = min(open_p, close_p) * (1 - rng.uniform(0, 0.015))
        volume = rng.randint(500_000, 5_000_000)
        rows.append({
            "trade_date": d,
            "open": f"{open_p:.3f}",
            "high": f"{high_p:.3f}",
            "low": f"{low_p:.3f}",
            "close": f"{close_p:.3f}",
            "volume": volume,
        })
        price = close_p
    return rows


async def fetch_klines(
    stock_code: str,
    period: str = "daily",
    count: int = 60,
) -> list[dict]:
    """获取 K 线(优先 cache,miss mock 生成)

    Args:
        stock_code: 6 位代码(可带后缀)
        period: daily / weekly / 60min(目前只支持 daily mock)
        count: 根数(默认 60 ≈ 3 个月日 K)

    Returns:
        [{date, open, high, low, close, volume}, ...] 升序
    """
    from sqlalchemy import select

    # 1. 查缓存
    async with async_session() as session:
        stmt = (
            select(KlineCache)
            .where(KlineCache.stock_code == stock_code, KlineCache.period == period)
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

    # 2. miss → mock 生成 + 落库
    rows = _mock_klines(stock_code, count)
    async with async_session() as session:
        for row in rows:
            session.add(
                KlineCache(
                    stock_code=stock_code,
                    trade_date=row["trade_date"],
                    period=period,
                    open_price=row["open"],
                    high_price=row["high"],
                    low_price=row["low"],
                    close_price=row["close"],
                    volume=row["volume"],
                    source="mock",
                )
            )
        await session.commit()
    logger.info("K 线 mock 生成并落库: %s %s (%d 根)", stock_code, period, len(rows))

    return [
        {
            "date": r["trade_date"].isoformat(),
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "volume": r["volume"],
        }
        for r in rows
    ]


__all__ = ["fetch_klines"]