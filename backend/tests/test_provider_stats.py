"""A3 多 Provider 占比月度统计测试"""
import asyncio
from datetime import datetime

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
    from app.models.orm import TradeScore, Transaction

    async def _do():
        async with async_session() as session:
            await session.execute(delete(TradeScore))
            await session.execute(delete(Transaction))
            await session.commit()

    asyncio.run(_do())
    yield


async def _seed_scores(rows: list[dict]):
    """种 trade + score(直接 ORM,不走 API)"""
    from app.db import async_session
    from app.models.orm import TradeScore, Transaction

    async with async_session() as session:
        for r in rows:
            tx = Transaction(
                stock_code=r["stock_code"],
                stock_name=r.get("stock_name", "T"),
                action=r.get("action", "buy"),
                shares=r.get("shares", 100),
                price=r.get("price", "10.000"),
                trade_date=r.get("trade_date", datetime(2026, 7, 1).date()),
            )
            session.add(tx)
            await session.flush()
            ts = TradeScore(
                trade_id=tx.id,
                score=r.get("score", 75),
                score_breakdown="{}",
                ai_provider=r["provider"],
                ai_status=r.get("status", "success"),
                created_at=r["created_at"],
            )
            session.add(ts)
        await session.commit()


class TestMonthlyProviderStats:
    def test_empty_year(self, client):
        r = client.get("/api/provider-stats/monthly?year=2026")
        assert r.status_code == 200
        data = r.json()
        assert data["year"] == 2026
        assert len(data["items"]) == 12
        for item in data["items"]:
            assert item["total"] == 0
            assert item["providers"] == {}
            assert item["statuses"] == {}

    def test_single_month_single_provider(self, client):
        async def seed():
            await _seed_scores([
                {"stock_code": "600519.SH", "provider": "deepseek",
                 "created_at": datetime(2026, 7, 15)},
            ])
        asyncio.run(seed())
        data = client.get("/api/provider-stats/monthly?year=2026").json()
        jul = next(i for i in data["items"] if i["month"] == "2026-07")
        assert jul["total"] == 1
        assert jul["providers"] == {"deepseek": 1}
        assert jul["statuses"] == {"success": 1}

    def test_multi_providers_in_month(self, client):
        async def seed():
            await _seed_scores([
                {"stock_code": "600519.SH", "provider": "deepseek",
                 "created_at": datetime(2026, 7, 1)},
                {"stock_code": "000001.SZ", "provider": "deepseek",
                 "created_at": datetime(2026, 7, 2)},
                {"stock_code": "300750.SZ", "provider": "minimax",
                 "created_at": datetime(2026, 7, 3)},
                {"stock_code": "002415.SZ", "provider": "doubao",
                 "created_at": datetime(2026, 7, 4)},
            ])
        asyncio.run(seed())
        data = client.get("/api/provider-stats/monthly?year=2026").json()
        jul = next(i for i in data["items"] if i["month"] == "2026-07")
        assert jul["total"] == 4
        assert jul["providers"] == {"deepseek": 2, "minimax": 1, "doubao": 1}

    def test_multi_months_and_statuses(self, client):
        async def seed():
            await _seed_scores([
                {"stock_code": "600519.SH", "provider": "deepseek",
                 "status": "success", "created_at": datetime(2026, 6, 1)},
                {"stock_code": "000001.SZ", "provider": "minimax",
                 "status": "no_key", "created_at": datetime(2026, 6, 5)},
                {"stock_code": "300750.SZ", "provider": "deepseek",
                 "status": "failed", "created_at": datetime(2026, 7, 10)},
            ])
        asyncio.run(seed())
        data = client.get("/api/provider-stats/monthly?year=2026").json()
        jun = next(i for i in data["items"] if i["month"] == "2026-06")
        jul = next(i for i in data["items"] if i["month"] == "2026-07")
        assert jun["total"] == 2
        assert jun["providers"] == {"deepseek": 1, "minimax": 1}
        assert jun["statuses"] == {"success": 1, "no_key": 1}
        assert jul["total"] == 1
        assert jul["providers"] == {"deepseek": 1}
        assert jul["statuses"] == {"failed": 1}

    def test_other_year_excluded(self, client):
        async def seed():
            await _seed_scores([
                {"stock_code": "600519.SH", "provider": "deepseek",
                 "created_at": datetime(2025, 12, 31)},
                {"stock_code": "000001.SZ", "provider": "deepseek",
                 "created_at": datetime(2026, 1, 1)},
            ])
        asyncio.run(seed())
        data = client.get("/api/provider-stats/monthly?year=2026").json()
        # 2025 不计入 2026 统计
        assert sum(i["total"] for i in data["items"]) == 1

    def test_default_year(self, client):
        """不传 year → 默认 2026"""
        r = client.get("/api/provider-stats/monthly")
        assert r.status_code == 200
        assert r.json()["year"] == 2026


class TestProviderSummary:
    def test_empty_summary(self, client):
        r = client.get("/api/provider-stats/summary?year=2026")
        assert r.status_code == 200
        data = r.json()
        assert data["year"] == 2026
        assert data["total"] == 0
        assert data["providers"] == []

    def test_summary_with_data(self, client):
        async def seed():
            await _seed_scores([
                {"stock_code": "600519.SH", "provider": "deepseek",
                 "created_at": datetime(2026, 6, 1)},
                {"stock_code": "000001.SZ", "provider": "deepseek",
                 "created_at": datetime(2026, 7, 1)},
                {"stock_code": "300750.SZ", "provider": "minimax",
                 "created_at": datetime(2026, 7, 2)},
                {"stock_code": "002415.SZ", "provider": "doubao",
                 "created_at": datetime(2026, 8, 1)},
            ])
        asyncio.run(seed())
        data = client.get("/api/provider-stats/summary?year=2026").json()
        assert data["total"] == 4
        providers = {p["provider"]: p for p in data["providers"]}
        assert providers["deepseek"]["count"] == 2
        assert providers["deepseek"]["pct"] == 50.0
        assert providers["minimax"]["count"] == 1
        assert providers["minimax"]["pct"] == 25.0
        assert providers["doubao"]["count"] == 1
        assert providers["doubao"]["pct"] == 25.0
        # 按 count 降序
        counts = [p["count"] for p in data["providers"]]
        assert counts == sorted(counts, reverse=True)