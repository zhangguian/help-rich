"""账户仓储(阶段5)。

**默认账户约定**:系统恒有且仅有一个 `is_default=True` 的账户,id 恒为 1
(由迁移 e5f60718293a 建立)。所有未显式指定 account_id 的调用方一律落到默认账户,
这样存量 API / 前端调用**无需修改**即可继续工作 —— 这是本次改造不做破坏性变更的关键。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.db import async_session
from app.models.orm import Account

DEFAULT_ACCOUNT_ID = 1


class AccountRepo:
    async def list_all(self) -> list[Account]:
        async with async_session() as s:
            stmt = select(Account).order_by(Account.id)
            return list((await s.execute(stmt)).scalars().all())

    async def get(self, account_id: int) -> Account | None:
        async with async_session() as s:
            return await s.get(Account, account_id)

    async def get_default(self) -> Account | None:
        async with async_session() as s:
            stmt = select(Account).where(Account.is_default.is_(True)).limit(1)
            return (await s.execute(stmt)).scalars().first()

    async def ensure_default(self) -> int:
        """确保默认账户存在,返回其 id。幂等。"""
        async with async_session() as s:
            stmt = select(Account).where(Account.is_default.is_(True)).limit(1)
            row = (await s.execute(stmt)).scalars().first()
            if row is not None:
                return row.id
            s.add(Account(name="默认账户", kind="broker", is_default=True))
            await s.commit()
            return DEFAULT_ACCOUNT_ID

    async def create(
        self, name: str, kind: str = "broker", broker: str | None = None, note: str | None = None
    ) -> int:
        async with async_session() as s:
            row = Account(name=name, kind=kind, broker=broker, note=note, is_default=False)
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return row.id

    async def rename(self, account_id: int, name: str) -> bool:
        async with async_session() as s:
            row = await s.get(Account, account_id)
            if row is None or row.is_default:
                return False
            row.name = name
            await s.commit()
            return True

    async def delete(self, account_id: int) -> tuple[bool, str]:
        """删除账户。默认账户不可删;有持仓的账户不可删。"""
        async with async_session() as s:
            row = await s.get(Account, account_id)
            if row is None:
                return False, "账户不存在"
            if row.is_default:
                return False, "默认账户不可删除"

            from app.models.orm import Position, Transaction

            pos_n = (
                await s.execute(
                    select(Position.id).where(Position.account_id == account_id).limit(1)
                )
            ).scalars().first()
            if pos_n is not None:
                return False, "该账户下仍有持仓,请先清空持仓再删除"

            tx_n = (
                await s.execute(
                    select(Transaction.id).where(Transaction.account_id == account_id).limit(1)
                )
            ).scalars().first()
            if tx_n is not None:
                return False, "该账户下仍有交易流水,不可删除"

            await s.delete(row)
            await s.commit()
            return True, ""


    async def get_cash_available(self, account_id: int) -> Decimal | None:
        """账户可用资金(元)。None = 未填写。

        **未填写 ≠ 0** —— 这两个语义对用户完全不同(「没填」是待补充信息,
        「0 元」是已确认没钱)。判定层据此决定给不给数字。
        """
        async with async_session() as s:
            row = await s.get(Account, account_id)
            if row is None:
                return None
            raw = row.cash_available
            if raw is None:
                return None
            raw = raw.strip()
            if not raw:
                return None
            try:
                return Decimal(raw)
            except InvalidOperation:
                # 库里是脏数据(非数字) —— 当作未填写,不要编一个数字出来
                return None

    async def set_cash_available(self, account_id: int, value: Decimal | None) -> bool:
        """写账户可用资金。value=None = 清空(= 未填写)。

        返回 False = 账户不存在。
        """
        async with async_session() as s:
            row = await s.get(Account, account_id)
            if row is None:
                return False
            row.cash_available = (
                None if value is None else str(value.quantize(Decimal("0.01")))
            )
            await s.commit()
            return True


account_repo = AccountRepo()

__all__ = ["AccountRepo", "DEFAULT_ACCOUNT_ID", "account_repo"]
