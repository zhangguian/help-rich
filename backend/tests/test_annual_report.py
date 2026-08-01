"""P6.1 年账单后端测试

- annual_report_service.get_annual_report(year):聚合胜率/Top5/净盈亏
- 边界:全年无交易 / 全胜 / 全败 / 跨年持仓
- API GET /api/annual-report/{year}
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.transaction_repo import transaction_repo
from app.services.annual_report_service import get_annual_report


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    from app.db import async_session
    from app.models.orm import Position, Transaction
    from sqlalchemy import delete

    async def _do():
        async with async_session() as session:
            await session.execute(delete(Transaction))
            await session.execute(delete(Position))
            await session.commit()

    asyncio.run(_do())
    yield


async def _seed_year_2026():
    """2026 年:600519 买入 1000@10 卖出 500@15(赚)+ 000001 买入 200@20 卖出 200@10(亏)"""
    await transaction_repo.create(
        stock_code="600519.SH", stock_name="A", action="buy",
        shares=1000, price="10.000", trade_date=date(2026, 3, 1),
    )
    await transaction_repo.create(
        stock_code="000001.SZ", stock_name="B", action="buy",
        shares=200, price="20.000", trade_date=date(2026, 5, 1),
    )
    await transaction_repo.create(
        stock_code="600519.SH", stock_name="A", action="sell",
        shares=500, price="15.000", trade_date=date(2026, 6, 1),
    )
    await transaction_repo.create(
        stock_code="000001.SZ", stock_name="B", action="sell",
        shares=200, price="10.000", trade_date=date(2026, 7, 1),
    )


class TestAnnualReportService:
    def test_no_trades(self):
        out = asyncio.run(get_annual_report(2026))
        assert out["year"] == 2026
        assert out["closed_count"] == 0
        assert out["win_rate"] == 0.0
        assert out["top5_profit"] == []
        assert out["top5_loss"] == []

    def test_basic_year(self):
        asyncio.run(_seed_year_2026())
        out = asyncio.run(get_annual_report(2026))
        # 600519 卖 500@15 - 成本 10 → realized = 2500
        # 000001 卖 200@10 - 成本 20 → realized = -2000
        assert out["closed_count"] == 2
        assert Decimal(out["net_pnl"]) == Decimal("500")  # 2500 - 2000
        assert Decimal(out["realized_profit"]) == Decimal("2500")
        assert Decimal(out["realized_loss"]) == Decimal("2000")
        assert out["win_rate"] == 0.5
        # Top5
        assert out["top5_profit"][0]["stock_code"] == "600519.SH"
        assert Decimal(out["top5_profit"][0]["realized_pnl"]) == Decimal("2500")
        assert out["top5_loss"][0]["stock_code"] == "000001.SZ"

    def test_year_filter_excludes_other_years(self):
        """2025 年买入 → 2026 年卖出:2025 不计,2026 计 realized"""
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="buy",
            shares=100, price="10.000", trade_date=date(2025, 1, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="sell",
            shares=100, price="20.000", trade_date=date(2026, 6, 1),
        ))
        out = asyncio.run(get_annual_report(2025))
        assert out["closed_count"] == 0  # 2025 只买不卖
        out = asyncio.run(get_annual_report(2026))
        assert out["closed_count"] == 1
        assert Decimal(out["net_pnl"]) == Decimal("1000")  # (20-10)*100

    def test_all_win(self):
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="buy",
            shares=100, price="10.000", trade_date=date(2026, 3, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="000001.SZ", stock_name="B", action="buy",
            shares=100, price="20.000", trade_date=date(2026, 4, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="sell",
            shares=100, price="15.000", trade_date=date(2026, 5, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="000001.SZ", stock_name="B", action="sell",
            shares=100, price="25.000", trade_date=date(2026, 6, 1),
        ))
        out = asyncio.run(get_annual_report(2026))
        assert out["win_rate"] == 1.0
        assert out["top5_loss"] == []

    def test_all_loss(self):
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="buy",
            shares=100, price="10.000", trade_date=date(2026, 3, 1),
        ))
        asyncio.run(transaction_repo.create(
            stock_code="600519.SH", stock_name="A", action="sell",
            shares=100, price="5.000", trade_date=date(2026, 5, 1),
        ))
        out = asyncio.run(get_annual_report(2026))
        assert out["win_rate"] == 0.0
        assert out["top5_profit"] == []

    def test_top5_limit(self):
        """超过 5 笔时只取前 5"""
        for i in range(7):
            asyncio.run(transaction_repo.create(
                stock_code=f"60000{i}.SH", stock_name=f"S{i}", action="buy",
                shares=100, price="10.000", trade_date=date(2026, 3, 1),
            ))
            asyncio.run(transaction_repo.create(
                stock_code=f"60000{i}.SH", stock_name=f"S{i}", action="sell",
                shares=100, price=f"{11 + i}.000", trade_date=date(2026, 5, 1),
            ))
        out = asyncio.run(get_annual_report(2026))
        assert out["closed_count"] == 7
        assert len(out["top5_profit"]) == 5
        assert len(out["top5_loss"]) == 0  # 全赚


class TestAnnualReportAPI:
    def test_get_report(self, client):
        asyncio.run(_seed_year_2026())
        r = client.get("/api/annual-report/2026")
        assert r.status_code == 200
        body = r.json()
        assert body["year"] == 2026
        assert body["closed_count"] == 2

    def test_invalid_year(self, client):
        r = client.get("/api/annual-report/1999")
        assert r.status_code == 400
        r = client.get("/api/annual-report/2200")
        assert r.status_code == 400


from decimal import Decimal  # noqa: E402  (放在文件末尾,被测试用例引用)