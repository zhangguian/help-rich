"""P4.9 评语反馈 + P5.1/P5.2 止损 API 测试

- PUT  /api/diagnose/{trade_id}/feedback:useful / useless / null
- POST /api/stop-losses:设置/更新(同 code 覆盖)
- GET  /api/stop-losses:列表
- DELETE /api/stop-losses/{code}
- POST /api/stop-losses/{code}/triggered:幂等(同日重复返回 duplicate=true)
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.stop_loss_repo import stop_loss_repo
from app.repositories.transaction_repo import transaction_repo
from app.repositories.trade_score_repo import trade_score_repo


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    """清空测试残留(transaction + trade_score + stop_loss + position)"""
    from app.db import async_session
    from app.models.orm import Position, StopLoss, TradeScore, Transaction
    from sqlalchemy import delete

    async def _do():
        async with async_session() as session:
            await session.execute(delete(TradeScore))
            await session.execute(delete(StopLoss))
            await session.execute(delete(Transaction))
            await session.execute(delete(Position))
            await session.commit()

    asyncio.run(_do())
    yield


async def _seed_trade_and_score():
    """插入交易 + 评分(feedback 测试用)"""
    t = await transaction_repo.create(
        stock_code="600519.SH", stock_name="贵州茅台",
        action="buy", shares=100, price="1450.000",
        trade_date=date(2026, 7, 20),
    )
    await trade_score_repo.upsert(
        trade_id=t.id, score=85, score_breakdown="{}"
    )
    return t.id


class TestFeedbackAPI:
    def test_useful(self, client):
        trade_id = asyncio.run(_seed_trade_and_score())
        r = client.put(f"/api/diagnose/{trade_id}/feedback", json={"feedback": "useful"})
        assert r.status_code == 200
        assert r.json()["feedback"] == "useful"

    def test_useless(self, client):
        trade_id = asyncio.run(_seed_trade_and_score())
        r = client.put(f"/api/diagnose/{trade_id}/feedback", json={"feedback": "useless"})
        assert r.status_code == 200

    def test_null_resets(self, client):
        trade_id = asyncio.run(_seed_trade_and_score())
        client.put(f"/api/diagnose/{trade_id}/feedback", json={"feedback": "useful"})
        r = client.put(f"/api/diagnose/{trade_id}/feedback", json={"feedback": None})
        assert r.status_code == 200
        assert r.json()["feedback"] is None

    def test_invalid_value_422(self, client):
        trade_id = asyncio.run(_seed_trade_and_score())
        r = client.put(f"/api/diagnose/{trade_id}/feedback", json={"feedback": "great"})
        assert r.status_code == 422

    def test_not_found_404(self, client):
        r = client.put("/api/diagnose/99999/feedback", json={"feedback": "useful"})
        assert r.status_code == 404


class TestStopLossAPI:
    def test_upsert_and_list(self, client):
        r = client.post("/api/stop-losses", json={
            "stock_code": "600519.SH",
            "stop_loss_price": "1400.000",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["stock_code"] == "600519.SH"
        assert body["stop_loss_price"] == "1400.000"
        assert body["enabled"] is True

        # 列表
        r = client.get("/api/stop-losses")
        assert r.status_code == 200
        items = r.json()
        assert any(i["stock_code"] == "600519.SH" for i in items)

    def test_upsert_overwrites(self, client):
        client.post("/api/stop-losses", json={
            "stock_code": "600519.SH", "stop_loss_price": "1400.000",
        })
        client.post("/api/stop-losses", json={
            "stock_code": "600519.SH", "stop_loss_price": "1350.000",
        })
        items = client.get("/api/stop-losses").json()
        sl = next(i for i in items if i["stock_code"] == "600519.SH")
        assert sl["stop_loss_price"] == "1350.000"

    def test_normalize_code(self, client):
        """纯 6 位 + 前缀字母都规范化"""
        r1 = client.post("/api/stop-losses", json={
            "stock_code": "600519", "stop_loss_price": "1400.000",
        })
        r2 = client.post("/api/stop-losses", json={
            "stock_code": "sh600519", "stop_loss_price": "1400.000",
        })
        assert r1.status_code == 200
        assert r2.status_code == 200
        # 同 code 应覆盖而非重复
        items = client.get("/api/stop-losses").json()
        assert sum(1 for i in items if i["stock_code"] == "600519.SH") == 1

    def test_negative_price_422(self, client):
        r = client.post("/api/stop-losses", json={
            "stock_code": "600519.SH", "stop_loss_price": "-1",
        })
        assert r.status_code == 422

    def test_notify_flags(self, client):
        r = client.post("/api/stop-losses", json={
            "stock_code": "600519.SH", "stop_loss_price": "1400.000",
            "notify_sound": False, "notify_desktop": False, "notify_vibrate": True,
        })
        assert r.status_code == 200
        assert r.json()["notify_sound"] is False
        assert r.json()["notify_vibrate"] is True

    def test_delete(self, client):
        client.post("/api/stop-losses", json={
            "stock_code": "600519.SH", "stop_loss_price": "1400.000",
        })
        r = client.delete("/api/stop-losses/600519.SH")
        assert r.status_code == 200
        items = client.get("/api/stop-losses").json()
        assert all(i["stock_code"] != "600519.SH" for i in items)

    def test_delete_not_found(self, client):
        r = client.delete("/api/stop-losses/999999.SH")
        assert r.status_code == 404

    def test_triggered_idempotent_same_day(self, client):
        client.post("/api/stop-losses", json={
            "stock_code": "600519.SH", "stop_loss_price": "1400.000",
        })
        r1 = client.post("/api/stop-losses/600519.SH/triggered")
        r2 = client.post("/api/stop-losses/600519.SH/triggered")
        assert r1.status_code == 200 and r1.json()["duplicate"] is False
        assert r2.status_code == 200 and r2.json()["duplicate"] is True

    def test_triggered_not_found(self, client):
        r = client.post("/api/stop-losses/999999.SH/triggered")
        assert r.status_code == 404