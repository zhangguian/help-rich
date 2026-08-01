"""P0 必修:资金流测试(E)"""
import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.orm import FundFlow
from app.services.fund_flow_service import (
    generate_one,
    list_recent,
    _random_event,
)
from sqlalchemy import delete


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean(client):
    from app.db import async_session

    async def _do():
        async with async_session() as session:
            await session.execute(delete(FundFlow))
            await session.commit()

    asyncio.run(_do())
    yield


class TestFundFlowService:
    def test_random_event_shape(self):
        e = _random_event("600519.SH")
        assert e.stock_code == "600519.SH"
        assert e.direction in {"in", "out"}
        assert e.category in {"small", "medium", "large", "super"}
        assert float(e.amount) > 0

    def test_generate_one_persists(self):
        flow = asyncio.run(generate_one("000001.SZ"))
        assert flow.id is not None
        rows = asyncio.run(list_recent("000001.SZ", limit=10))
        assert len(rows) >= 1
        assert any(r.id == flow.id for r in rows)


class TestFundFlowAPI:
    def test_get_recent(self, client):
        asyncio.run(generate_one("600519.SH"))
        asyncio.run(generate_one("600519.SH"))
        r = client.get("/api/fund-flow/600519.SH")
        assert r.status_code == 200
        data = r.json()
        assert data["stock_code"] == "600519.SH"
        assert len(data["items"]) >= 2

    def test_manual_generate(self, client):
        r = client.post("/api/fund-flow/600519.SH/generate")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_sse_endpoint_exists(self, client):
        """SSE 路由已注册(端到端验证靠 curl / scripts/dev.ps1)"""
        # 直接验证 OpenAPI schema 里有这个路由(避免 TestClient 卡 SSE 流)
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        assert "/api/fund-flow/{stock_code}/events" in paths