"""P0 必修:风险敞口报告测试(C1)"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.risk_service import PositionExposure, calc_risk
from sqlalchemy import delete


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    from app.db import async_session
    from app.models.orm import TradeScore, Transaction

    async def _do():
        async with async_session() as session:
            await session.execute(delete(TradeScore))
            await session.execute(delete(Transaction))
            await session.commit()

    asyncio.run(_do())
    yield


def _make_position(code, name, shares, cost):
    return PositionExposure(
        stock_code=code,
        stock_name=name,
        shares=shares,
        avg_cost=cost,
        market_value=shares * float(cost),
    )


class TestCalcRisk:
    def test_no_positions(self):
        r = calc_risk([])
        assert r["total_positions"] == 0
        assert r["risk_level"] == "低"
        assert "无持仓" in r["warnings"][0]

    def test_single_high_concentration(self):
        positions = [_make_position("600519.SH", "茅台", 1000, "1500")]
        r = calc_risk(positions)
        assert r["total_positions"] == 1
        assert r["top_holding_ratio"] == 100.0
        assert r["hhi_index"] == 10000.0  # 100%^2 * 10000
        assert r["risk_level"] == "高"
        assert any("集中度" in w for w in r["warnings"])

    def test_diversified(self):
        # 平均分散:每只 ~20k 市值,top ~23%
        positions = [
            _make_position("600519.SH", "茅台", 15, "1500"),     # 22500
            _make_position("000001.SZ", "平安", 1500, "12"),     # 18000
            _make_position("300750.SZ", "宁德", 100, "200"),    # 20000
            _make_position("002185.SZ", "华天", 1300, "15"),    # 19500
            _make_position("600036.SH", "招行", 600, "35"),      # 21000
            _make_position("600276.SH", "恒瑞", 250, "35"),     # 8750
        ]
        r = calc_risk(positions)
        assert r["total_positions"] == 6
        assert r["sector_count"] >= 3
        assert r["risk_level"] in {"低", "中"}
        assert r["top_holding_ratio"] < 30
        assert r["hhi_index"] < 2000

    def test_same_sector_warning(self):
        positions = [
            _make_position("600519.SH", "茅台", 100, "1500"),
            _make_position("600036.SH", "招行", 100, "35"),
            _make_position("601318.SH", "平安", 100, "45"),
        ]
        r = calc_risk(positions)
        assert r["sector_count"] == 1
        assert any("板块" in w for w in r["warnings"])

    def test_hhi_calculation(self):
        # 50% / 30% / 20% → HHI = 50^2 + 30^2 + 20^2 = 2500 + 900 + 400 = 3800
        positions = [
            _make_position("600519.SH", "A", 50, "100"),  # 5000
            _make_position("000001.SZ", "B", 30, "100"),  # 3000
            _make_position("300750.SZ", "C", 20, "100"),  # 2000
        ]
        r = calc_risk(positions)
        assert r["total_market_value"] == 10000.0
        assert abs(r["hhi_index"] - 3800) < 0.1


class TestRiskReportAPI:
    def test_empty(self, client):
        r = client.get("/api/risk-report")
        assert r.status_code == 200
        data = r.json()
        assert data["total_positions"] == 0

    def test_with_transactions(self, client):
        from datetime import date

        from app.repositories.transaction_repo import transaction_repo

        async def seed():
            await transaction_repo.create(
                stock_code="600519.SH", stock_name="茅台",
                action="buy", shares=100, price="1500.000",
                trade_date=date(2026, 7, 1),
            )
            await transaction_repo.create(
                stock_code="000001.SZ", stock_name="平安",
                action="buy", shares=1000, price="12.000",
                trade_date=date(2026, 7, 2),
            )

        asyncio.run(seed())

        r = client.get("/api/risk-report")
        assert r.status_code == 200
        data = r.json()
        assert data["total_positions"] == 2
        assert data["top_holding_ratio"] > 50  # 茅台 150000 vs 总 162000
        assert data["sector_count"] >= 1