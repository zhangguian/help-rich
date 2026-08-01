"""交易流水仓储(P2.1 实施)"""
from datetime import date
from typing import Optional

from sqlalchemy import select

from app.db import async_session
from app.models.orm import Transaction


class TransactionRepository:
    async def create(
        self,
        *,
        stock_code: str,
        action: str,
        shares: int,
        price: str,
        trade_date: date,
        stock_name: str | None = None,
        note: str | None = None,
    ) -> Transaction:
        """创建一条交易流水"""
        async with async_session() as session:
            row = Transaction(
                stock_code=stock_code,
                stock_name=stock_name,
                action=action,
                shares=shares,
                price=price,
                trade_date=trade_date,
                note=note,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_by_id(self, tx_id: int) -> Optional[Transaction]:
        async with async_session() as session:
            return await session.get(Transaction, tx_id)

    async def list_all(
        self,
        stock_code: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transaction], int]:
        """列出流水 + 总数"""
        async with async_session() as session:
            stmt = select(Transaction).order_by(Transaction.trade_date.desc())
            if stock_code:
                stmt = stmt.where(Transaction.stock_code == stock_code)
            count_stmt = select(Transaction)
            if stock_code:
                count_stmt = count_stmt.where(Transaction.stock_code == stock_code)
            total = len((await session.execute(count_stmt)).scalars().all())
            stmt = stmt.limit(limit).offset(offset)
            items = list((await session.execute(stmt)).scalars().all())
            return items, total

    async def update(self, tx_id: int, **kwargs) -> Optional[Transaction]:
        """更新流水(只能改 note / shares / price,不能改 stock_code / action)"""
        async with async_session() as session:
            row = await session.get(Transaction, tx_id)
            if row is None:
                return None
            for k, v in kwargs.items():
                if v is not None and hasattr(row, k):
                    setattr(row, k, v)
            await session.commit()
            await session.refresh(row)
            return row

    async def delete(self, tx_id: int) -> bool:
        async with async_session() as session:
            row = await session.get(Transaction, tx_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


transaction_repo = TransactionRepository()