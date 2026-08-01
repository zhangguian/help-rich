"""v0.4.1 持仓一键清仓(P-stop-loss-v2)测试"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    from app.db import async_session
    from app.models.orm import Position, Transaction

    async def _do():
        async with async_session() as session:
            await session.execute(delete(Transaction))
            await session.execute(delete(Position))
            await session.commit()

    asyncio.run(_do())
    yield


class TestClearPosition:
    def test_clear_creates_sell_and_removes_position(self, client):
        """一键清仓 → 持仓归零 + 创建 sell 流水"""
        r = client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 100, "cost_price": "1450.000"},
        )
        assert r.status_code == 201

        # 清仓(以 1500 卖出,盈利)
        r = client.post(
            "/api/positions/600519/clear",
            json={"price": "1500.000", "note": "止盈清仓"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["stock_code"] == "600519.SH"
        assert data["shares"] == 100
        assert data["price"] == "1500.000"
        # realized = (1500 - 1450) * 100 = 5000
        assert data["realized_pnl"] == "5000.00"
        assert data["trade_id"] >= 1
        assert data["trade_date"] == date.today().isoformat()

        # 持仓已删除
        r = client.get("/api/positions")
        assert r.json()["items"] == []

        # sell 流水已创建
        r = client.get("/api/transactions")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["action"] == "sell"
        assert items[0]["shares"] == 100
        assert items[0]["note"] == "止盈清仓"

    def test_clear_with_loss(self, client):
        """清仓亏损(卖出价 < 成本)→ realized_pnl 为负"""
        client.post(
            "/api/positions",
            json={"stock_code": "000001", "shares": 1000, "cost_price": "12.000"},
        )
        r = client.post(
            "/api/positions/000001/clear",
            json={"price": "10.500"},
        )
        assert r.status_code == 201
        # realized = (10.5 - 12) * 1000 = -1500
        assert r.json()["realized_pnl"] == "-1500.00"

    def test_clear_default_note(self, client):
        """不传 note → 默认 '一键清仓'"""
        client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 100, "cost_price": "1450.000"},
        )
        r = client.post(
            "/api/positions/600519/clear",
            json={"price": "1500.000"},
        )
        items = client.get("/api/transactions").json()["items"]
        assert items[0]["note"] == "一键清仓"

    def test_clear_position_not_found(self, client):
        """无持仓 → 404"""
        r = client.post(
            "/api/positions/600519/clear",
            json={"price": "1500.000"},
        )
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "POSITION_NOT_FOUND"

    def test_clear_bare_code_normalized(self, client):
        """路径参数 纯 6 位 → 规范化为带后缀"""
        client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 100, "cost_price": "1450.000"},
        )
        r = client.post(
            "/api/positions/600519/clear",  # 纯 6 位
            json={"price": "1500.000"},
        )
        assert r.status_code == 201
        assert r.json()["stock_code"] == "600519.SH"

    def test_clear_invalid_price(self, client):
        """price <= 0 → 422"""
        client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 100, "cost_price": "1450.000"},
        )
        r = client.post(
            "/api/positions/600519/clear",
            json={"price": "0"},
        )
        assert r.status_code == 422