"""资金流服务(E)

- mock 数据生成:每只股票每分钟 1 条资金流入流出事件
- 真实数据源待接入(东财 / 新浪)

事件总线:`event_bus.publish({"event": "fund_flow", "stock_code": "...", ...})`
"""
import asyncio
import logging
import random
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.db_lock import safe_write
from app.db import async_session
from app.models.orm import FundFlow
from app.services.event_bus import event_bus

logger = logging.getLogger(__name__)

# 概率分布(mvp mock 随机权重)
CATEGORY_WEIGHTS = [
    ("small", 0.55, 50, 500),      # 中小单:50~500 万
    ("medium", 0.30, 500, 2000),   # 中单:500~2000 万
    ("large", 0.13, 2000, 10000),  # 大单:2000~10000 万
    ("super", 0.02, 10000, 50000), # 特大单:10000~50000 万
]


def _random_event(stock_code: str) -> FundFlow:
    """生成单条随机资金流事件"""
    rng = random.Random()
    pick = rng.choices(
        range(len(CATEGORY_WEIGHTS)),
        weights=[w[1] for w in CATEGORY_WEIGHTS],
        k=1,
    )[0]
    cat, _, low, high = CATEGORY_WEIGHTS[pick]
    amount = rng.uniform(low, high)
    direction = "in" if rng.random() < 0.55 else "out"
    return FundFlow(
        stock_code=stock_code,
        timestamp=datetime.now(),
        direction=direction,
        amount=f"{amount:.1f}",
        category=cat,
        source="mock",
    )


async def generate_one(stock_code: str) -> FundFlow:
    """生成并持久化单条 mock 资金流(并 publish 到 event_bus)"""
    flow = _random_event(stock_code)

    async def _do():
        async with async_session() as session:
            session.add(flow)
            await session.commit()
            await session.refresh(flow)

    await safe_write(_do)

    # 推 SSE(供前端实时滚动)
    await event_bus.publish({
        "event": "fund_flow",
        "stock_code": stock_code,
        "direction": flow.direction,
        "amount": flow.amount,
        "category": flow.category,
        "timestamp": flow.timestamp.isoformat(),
    })
    return flow


async def list_recent(stock_code: str, limit: int = 30) -> list[FundFlow]:
    """拉最近 N 条资金流(给前端初始列表用)"""
    from sqlalchemy import select

    async with async_session() as session:
        stmt = (
            select(FundFlow)
            .where(FundFlow.stock_code == stock_code)
            .order_by(FundFlow.timestamp.desc())
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())


async def start_mock_generator(stock_codes: list[str], interval_sec: float = 30) -> None:
    """后台任务:每 interval_sec 秒为每只 stock 生成 1 条资金流

    v0.2 MVP:由 lifespan 启动一次,后台不停运行。
    真实环境接东财/新浪后再替换。
    """
    if not stock_codes:
        logger.warning("资金流 mock 生成器:无 stock_codes,跳过")
        return
    logger.info(f"资金流 mock 生成器启动: {len(stock_codes)} 只股票, 间隔 {interval_sec}s")

    while True:
        try:
            for code in stock_codes:
                await generate_one(code)
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            logger.info("资金流 mock 生成器停止")
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("资金流 mock 生成器异常: %s", e)
            await asyncio.sleep(interval_sec)


__all__ = ["generate_one", "list_recent", "start_mock_generator", "FundFlow"]