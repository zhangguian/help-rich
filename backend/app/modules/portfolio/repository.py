"""交易流水仓储(P2.1 实施)"""
from datetime import date, time

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
        trade_time: time | None = None,
        stock_name: str | None = None,
        note: str | None = None,
        account_id: int | None = None,
    ) -> Transaction:
        """创建一条交易流水(默认落到默认账户,保持存量调用方无需改动)

        trade_time = None 表示时间未知(存量流水 / 截图导入 / 用户留空)。
        """
        from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

        async with async_session() as session:
            row = Transaction(
                account_id=account_id or DEFAULT_ACCOUNT_ID,
                stock_code=stock_code,
                stock_name=stock_name,
                action=action,
                shares=shares,
                price=price,
                trade_date=trade_date,
                trade_time=trade_time,
                note=note,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_by_id(self, tx_id: int) -> Transaction | None:
        async with async_session() as session:
            return await session.get(Transaction, tx_id)

    async def list_all(
        self,
        stock_code: str | None = None,
        limit: int = 50,
        offset: int = 0,
        account_id: int | None = None,
    ) -> tuple[list[Transaction], int]:
        """列出流水 + 总数(account_id=None 时只看默认账户,保持旧语义)

        排序:日期倒序 → 时间倒序(NULL 排最后)→ id 倒序。
        时间倒序让「同一天里最后成交的那笔」排在最前,与直觉一致。
        """
        from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

        scoped = account_id or DEFAULT_ACCOUNT_ID
        async with async_session() as session:
            stmt = (
                select(Transaction)
                .where(Transaction.account_id == scoped)
                .order_by(
                    Transaction.trade_date.desc(),
                    Transaction.trade_time.desc(),
                    Transaction.id.desc(),
                )
            )
            if stock_code:
                stmt = stmt.where(Transaction.stock_code == stock_code)
            count_stmt = select(Transaction).where(Transaction.account_id == scoped)
            if stock_code:
                count_stmt = count_stmt.where(Transaction.stock_code == stock_code)
            total = len((await session.execute(count_stmt)).scalars().all())
            stmt = stmt.limit(limit).offset(offset)
            items = list((await session.execute(stmt)).scalars().all())
            return items, total

    # 可改字段白名单。
    # ⚠️ 之前是「 hasattr(row, k) 就 setattr」—— 意味着连 `stock_code` /
    #    `trade_date` / `account_id` 都能被悄悄改掉(改标的等于把一笔流水
    #    搬到别的股票上,成本链会算错)。改成显式白名单,不在名单里的直接忽略。
    # `action` 现在**可以**改了(「买录成卖」是最常见的录错,以前只能删掉重录);
    # 改方向的安全网在 API 层:写入前先验算整条链是否自洽(见 api_transactions)。
    EDITABLE_FIELDS = frozenset(
        {"action", "shares", "price", "note", "trade_time"}
    )

    async def update(self, tx_id: int, **kwargs) -> Transaction | None:
        """更新流水(可改 action / shares / price / note / trade_time)。

        不能改 stock_code / trade_date —— 改标的等于把一笔流水搬到别的股票上,
        改日期会改变它在成本链里的落位,两者都必须走「删了重录」而不是静默改。
        """
        async with async_session() as session:
            row = await session.get(Transaction, tx_id)
            if row is None:
                return None
            for k, v in kwargs.items():
                if k not in self.EDITABLE_FIELDS:
                    continue
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

    async def delete_by_stock(self, stock_code: str) -> int:
        """删除某股票全部流水(持仓删除时联动,v0.4.0)"""
        from sqlalchemy import delete as sa_delete

        async with async_session() as session:
            result = await session.execute(
                sa_delete(Transaction).where(Transaction.stock_code == stock_code)
            )
            await session.commit()
            return result.rowcount or 0


transaction_repo = TransactionRepository()