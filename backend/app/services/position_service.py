"""持仓聚合 service(P2.3 实施)

从 transactions 实时聚合持仓(加权平均法):
  买入: shares += tx.shares; total_cost += tx.shares * tx.price
  卖出: shares -= tx.shares; total_cost -= tx.shares * current_avg_cost
        realized_pnl += tx.shares * (tx.price - current_avg_cost)

v2.1 §4.1.2
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from app.db import async_session
from app.models.orm import Transaction
from sqlalchemy import select


@dataclass
class Position:
    """单只股票的持仓汇总"""
    stock_code: str
    stock_name: Optional[str] = None
    shares: int = 0
    total_cost: Decimal = field(default_factory=lambda: Decimal("0"))
    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def avg_cost(self) -> Decimal:
        """加权平均成本"""
        if self.shares <= 0:
            return Decimal("0")
        # 保留 3 位小数(与中国券商对齐)
        return (self.total_cost / self.shares).quantize(Decimal("0.001"))

    @property
    def total_cost_fmt(self) -> str:
        return format(self.total_cost.quantize(Decimal("0.01")), ".2f")


def aggregate_positions(transactions: list[Transaction]) -> list[Position]:
    """纯函数:从流水列表聚合持仓

    按交易日期顺序处理(同一天内按 id 顺序,确保可复现)。
    """
    # 按 stock_code 分组
    by_code: dict[str, Position] = {}
    # 全局排序:trade_date 升序,id 升序
    sorted_tx = sorted(transactions, key=lambda t: (t.trade_date, t.id))

    for tx in sorted_tx:
        if tx.stock_code not in by_code:
            by_code[tx.stock_code] = Position(
                stock_code=tx.stock_code,
                stock_name=tx.stock_name,
            )
        pos = by_code[tx.stock_code]
        # 更新名称(以最新一条为准)
        if tx.stock_name:
            pos.stock_name = tx.stock_name

        price = Decimal(tx.price)
        if tx.action == "buy":
            pos.shares += tx.shares
            pos.total_cost += price * tx.shares
        elif tx.action == "sell":
            if tx.shares > pos.shares:
                # 卖出超过持仓(理论上 Pydantic 已校验,但双保险)
                raise ValueError(
                    f"卖出 {tx.shares} 股超过持仓 {pos.shares} 股 "
                    f"(stock={tx.stock_code}, tx_id={tx.id})"
                )
            realized_per_share = price - pos.avg_cost  # 用卖出前的成本
            pos.realized_pnl += realized_per_share * tx.shares
            pos.total_cost -= pos.avg_cost * tx.shares
            pos.shares -= tx.shares

    # 只返回仍有持仓的股票(shares > 0)
    return [p for p in by_code.values() if p.shares > 0]


async def get_all_positions() -> list[Position]:
    """异步:从 DB 加载所有流水 + 聚合"""
    async with async_session() as session:
        stmt = select(Transaction).order_by(Transaction.trade_date, Transaction.id)
        all_tx = list((await session.execute(stmt)).scalars().all())
    return aggregate_positions(all_tx)


async def get_position(stock_code: str) -> Optional[Position]:
    positions = await get_all_positions()
    for p in positions:
        if p.stock_code == stock_code:
            return p
    return None