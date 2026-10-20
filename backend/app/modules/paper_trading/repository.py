"""模拟盘持久化(仓储层)。

严格隔离:本模块只碰 paper_* 表,**不导入** position_repo / transaction_repo。
(由 tests/test_architecture_boundaries.py 的显式禁止规则强制。)
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.orm import (
    PaperAccount,
    PaperEquitySnapshot,
    PaperOrder,
    PaperPosition,
)


class PaperTradingRepo:
    # ---------- 账户 ----------

    async def create_account(self, name: str, initial_capital: str) -> int:
        async with async_session() as s:
            row = PaperAccount(
                name=name, initial_capital=initial_capital, cash=initial_capital
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return row.id

    async def list_accounts(self) -> list[PaperAccount]:
        async with async_session() as s:
            stmt = select(PaperAccount).order_by(PaperAccount.id)
            return list((await s.execute(stmt)).scalars().all())

    async def get_account(self, account_id: int) -> PaperAccount | None:
        async with async_session() as s:
            return await s.get(PaperAccount, account_id)

    async def get_first_account(self) -> PaperAccount | None:
        async with async_session() as s:
            stmt = select(PaperAccount).order_by(PaperAccount.id).limit(1)
            return (await s.execute(stmt)).scalars().first()

    async def delete_account(self, account_id: int) -> bool:
        async with async_session() as s:
            row = await s.get(PaperAccount, account_id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True

    # ---------- 持仓 ----------

    async def list_positions(self, account_id: int) -> list[PaperPosition]:
        async with async_session() as s:
            stmt = select(PaperPosition).where(PaperPosition.account_id == account_id)
            return list((await s.execute(stmt)).scalars().all())

    async def get_position(
        self, account_id: int, stock_code: str
    ) -> PaperPosition | None:
        async with async_session() as s:
            stmt = select(PaperPosition).where(
                PaperPosition.account_id == account_id,
                PaperPosition.stock_code == stock_code,
            )
            return (await s.execute(stmt)).scalars().first()

    # ---------- 订单 ----------

    async def list_orders(
        self, account_id: int, limit: int = 50
    ) -> list[PaperOrder]:
        async with async_session() as s:
            stmt = (
                select(PaperOrder)
                .where(PaperOrder.account_id == account_id)
                .order_by(PaperOrder.trade_date.desc(), PaperOrder.id.desc())
                .limit(limit)
            )
            return list((await s.execute(stmt)).scalars().all())

    # ---------- 净值快照 ----------

    async def upsert_equity(
        self, account_id: int, snap_date: date, total: str, cash: str, mv: str
    ) -> None:
        from datetime import datetime

        async with async_session() as s:
            stmt = select(PaperEquitySnapshot).where(
                PaperEquitySnapshot.account_id == account_id,
                PaperEquitySnapshot.snapshot_date == snap_date,
            )
            row = (await s.execute(stmt)).scalars().first()
            if row is None:
                s.add(
                    PaperEquitySnapshot(
                        account_id=account_id,
                        snapshot_date=snap_date,
                        total_equity=total,
                        cash=cash,
                        market_value=mv,
                    )
                )
            else:
                row.total_equity = total
                row.cash = cash
                row.market_value = mv
                row.created_at = datetime.now()
            await s.commit()

    async def list_equity(self, account_id: int) -> list[PaperEquitySnapshot]:
        async with async_session() as s:
            stmt = (
                select(PaperEquitySnapshot)
                .where(PaperEquitySnapshot.account_id == account_id)
                .order_by(PaperEquitySnapshot.snapshot_date)
            )
            return list((await s.execute(stmt)).scalars().all())


paper_trading_repo = PaperTradingRepo()

__all__ = ["PaperTradingRepo", "paper_trading_repo"]
