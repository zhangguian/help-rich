"""多账户测试(阶段5)。

核心不变量:**同一只票在不同账户的持仓/流水必须互相隔离**。
一旦隔离失效,用户会看到 A 券商的持仓算进 B 券商的盈亏 —— 这类错误极难察觉。
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models.orm import Account, Position, Transaction
from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID, account_repo
from app.modules.portfolio import service as position_service


@pytest.fixture
async def second_account():
    """建一个非默认账户,测试结束连同其持仓/流水一起清掉。"""
    acct_id = await account_repo.create("测试账户B", kind="broker")
    yield acct_id
    async with async_session() as s:
        for model in (Position, Transaction):
            rows = list(
                (
                    await s.execute(
                        select(model).where(model.account_id == acct_id)
                    )
                )
                .scalars()
                .all()
            )
            for r in rows:
                await s.delete(r)
        acc = await s.get(Account, acct_id)
        if acc is not None:
            await s.delete(acc)
        await s.commit()


class TestAccountRepo:
    @pytest.mark.asyncio
    async def test_default_account_always_exists(self):
        acc = await account_repo.get_default()
        assert acc is not None
        assert acc.is_default is True
        assert acc.id == DEFAULT_ACCOUNT_ID

    @pytest.mark.asyncio
    async def test_create_and_list(self, second_account):
        rows = await account_repo.list_all()
        ids = [r.id for r in rows]
        assert second_account in ids
        assert DEFAULT_ACCOUNT_ID in ids

    @pytest.mark.asyncio
    async def test_default_account_cannot_be_deleted(self):
        ok, msg = await account_repo.delete(DEFAULT_ACCOUNT_ID)
        assert ok is False
        assert "默认" in msg

    @pytest.mark.asyncio
    async def test_default_account_cannot_be_renamed(self):
        assert await account_repo.rename(DEFAULT_ACCOUNT_ID, "改名了") is False

    @pytest.mark.asyncio
    async def test_empty_account_can_be_deleted(self, second_account):
        ok, msg = await account_repo.delete(second_account)
        assert ok is True, msg

    @pytest.mark.asyncio
    async def test_account_with_position_cannot_be_deleted(self, second_account):
        await position_service.upsert_position(
            "600000.SH", 100, Decimal("10.00"), "浦发银行", account_id=second_account
        )
        ok, msg = await account_repo.delete(second_account)
        assert ok is False
        assert "持仓" in msg


class TestPositionIsolation:
    @pytest.mark.asyncio
    async def test_same_stock_in_two_accounts(self, second_account):
        """核心场景:同一只票同时持在两个账户,互不干扰。"""
        await position_service.upsert_position(
            "600519.SH", 100, Decimal("1500.00"), "贵州茅台", account_id=DEFAULT_ACCOUNT_ID
        )
        await position_service.upsert_position(
            "600519.SH", 200, Decimal("1600.00"), "贵州茅台", account_id=second_account
        )

        p1 = await position_service.get_position("600519.SH", account_id=DEFAULT_ACCOUNT_ID)
        p2 = await position_service.get_position("600519.SH", account_id=second_account)

        assert p1 is not None and p1.shares == 100
        assert p2 is not None and p2.shares == 200
        assert float(p1.total_cost) == 150000.0
        assert float(p2.total_cost) == 320000.0

    @pytest.mark.asyncio
    async def test_get_all_scoped_by_account(self, second_account):
        await position_service.upsert_position(
            "600519.SH", 100, Decimal("1500.00"), account_id=DEFAULT_ACCOUNT_ID
        )
        await position_service.upsert_position(
            "000001.SZ", 300, Decimal("11.00"), account_id=second_account
        )

        d1 = await position_service.get_all_positions(DEFAULT_ACCOUNT_ID)
        d2 = await position_service.get_all_positions(second_account)

        assert [p.stock_code for p in d1] == ["600519.SH"]
        assert [p.stock_code for p in d2] == ["000001.SZ"]

    @pytest.mark.asyncio
    async def test_default_is_omitted_account_id(self):
        """不传 account_id 时默认只看默认账户(向后兼容)。"""
        await position_service.upsert_position("600519.SH", 100, Decimal("1500.00"))
        assert len(await position_service.get_all_positions()) == 1
        assert await position_service.get_position("600519.SH") is not None

    @pytest.mark.asyncio
    async def test_delete_only_affects_target_account(self, second_account):
        await position_service.upsert_position(
            "600519.SH", 100, Decimal("1500.00"), account_id=DEFAULT_ACCOUNT_ID
        )
        await position_service.upsert_position(
            "600519.SH", 200, Decimal("1600.00"), account_id=second_account
        )

        assert await position_service.delete_position(
            "600519.SH", account_id=second_account
        ) is True

        assert await position_service.get_position(
            "600519.SH", account_id=second_account
        ) is None
        # 默认账户的必须还在
        assert await position_service.get_position(
            "600519.SH", account_id=DEFAULT_ACCOUNT_ID
        ) is not None


class TestTransactionIsolation:
    @pytest.mark.asyncio
    async def test_transactions_scoped_by_account(self, second_account):
        from datetime import date

        from app.modules.portfolio.repository import transaction_repo

        await transaction_repo.create(
            stock_code="600519.SH", action="buy", shares=100, price="1500",
            trade_date=date.today(), account_id=DEFAULT_ACCOUNT_ID,
        )
        await transaction_repo.create(
            stock_code="600519.SH", action="buy", shares=200, price="1600",
            trade_date=date.today(), account_id=second_account,
        )

        d1, n1 = await transaction_repo.list_all(account_id=DEFAULT_ACCOUNT_ID)
        d2, n2 = await transaction_repo.list_all(account_id=second_account)

        assert n1 == 1 and d1[0].shares == 100
        assert n2 == 1 and d2[0].shares == 200

    @pytest.mark.asyncio
    async def test_default_transaction_lands_in_default_account(self):
        from datetime import date

        from app.modules.portfolio.repository import transaction_repo

        tx = await transaction_repo.create(
            stock_code="600519.SH", action="buy", shares=100,
            price="1500", trade_date=date.today(),
        )
        assert tx.account_id == DEFAULT_ACCOUNT_ID


class TestMigrationIntegrity:
    def test_position_unique_is_composite(self):
        """ORM 层必须声明 (account_id, stock_code) 组合唯一,不能是 stock_code 唯一。"""
        names = {c.name for c in Position.__table__.columns}
        assert "account_id" in names

        uniques = {tuple(sorted(c.columns.keys())) for c in Position.__table__.constraints
                   if c.__class__.__name__ == "UniqueConstraint"}
        assert ("account_id", "stock_code") in uniques, (
            f"缺少 (account_id, stock_code) 组合唯一,实际: {uniques}"
        )
        assert ("stock_code",) not in uniques, (
            "stock_code 仍是全局唯一,会阻止同一账户外的重复持仓"
        )

    def test_position_has_foreign_key_to_account(self):
        fks = [tuple(fk.target_fullname.split(".")) for fk in Position.__table__.foreign_keys]
        assert any(t[0] == "account" for t in fks), f"缺少指向 account 的外键: {fks}"

    @pytest.mark.asyncio
    async def test_same_code_allowed_across_accounts_in_db(self, second_account):
        """落到数据库层的最终验证。"""
        from sqlalchemy.exc import IntegrityError

        async with async_session() as s:
            s.add(Position(account_id=DEFAULT_ACCOUNT_ID, stock_code="600519.SH",
                           shares=100, total_cost="1000", realized_pnl="0"))
            await s.commit()
        async with async_session() as s:
            s.add(Position(account_id=second_account, stock_code="600519.SH",
                           shares=200, total_cost="2000", realized_pnl="0"))
            await s.commit()

        # 同账户内重复必须被拒
        async with async_session() as s:
            s.add(Position(account_id=DEFAULT_ACCOUNT_ID, stock_code="600519.SH",
                           shares=1, total_cost="10", realized_pnl="0"))
            with pytest.raises(IntegrityError):
                await s.commit()
