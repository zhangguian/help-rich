"""P0 必修:K 线测试(D)"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.orm import KlineCache
from app.services.kline_service import fetch_klines, _mock_klines
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
            await session.execute(delete(KlineCache))
            await session.commit()

    asyncio.run(_do())
    yield


class TestMockKlines:
    def test_shape(self):
        rows = _mock_klines("600519.SH", count=30)
        assert len(rows) == 30
        first = rows[0]
        assert set(first.keys()) == {"trade_date", "open", "high", "low", "close", "volume"}
        assert first["trade_date"] < rows[-1]["trade_date"]
        for r in rows:
            assert float(r["low"]) <= float(r["open"])
            assert float(r["low"]) <= float(r["close"])
            assert float(r["high"]) >= float(r["open"])
            assert float(r["high"]) >= float(r["close"])
            assert r["volume"] > 0


class TestFetchKlines:
    def test_first_request_miss_mock(self):
        """首次请求:缓存空,mock 生成 + 落库"""
        items = asyncio.run(fetch_klines("600519.SH", count=20))
        assert len(items) == 20
        # 落库了
        from sqlalchemy import select

        async def _count():
            from app.db import async_session

            async with async_session() as session:
                stmt = select(KlineCache).where(KlineCache.stock_code == "600519.SH")
                return len((await session.execute(stmt)).scalars().all())

        assert asyncio.run(_count()) == 20

    def test_second_request_cache_hit(self):
        """第二次请求:从缓存读,数据一致"""
        first = asyncio.run(fetch_klines("600519.SH", count=20))
        second = asyncio.run(fetch_klines("600519.SH", count=20))
        assert first == second


class TestKlineAPI:
    def test_get_kline(self, client):
        r = client.get("/api/kline/600519.SH?limit=30")
        assert r.status_code == 200
        data = r.json()
        assert data["stock_code"] == "600519.SH"
        assert data["period"] == "daily"
        assert data["count"] == 30
        assert len(data["items"]) == 30

    def test_invalid_period(self, client):
        r = client.get("/api/kline/600519.SH?period=hourly")
        assert r.status_code == 400

    def test_invalid_limit(self, client):
        r = client.get("/api/kline/600519.SH?limit=999")
        assert r.status_code == 400