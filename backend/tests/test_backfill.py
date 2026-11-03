"""补评 / 全量重算(POST /api/diagnose/backfill)

覆盖:
- force=False → 只补**没有评分**的流水(漏评的那些)
- force=True  → 全部重算(评分口径升级后必须走这条)
- include_comment=False → 只算分不调 LLM
- 幂等:重复执行不报错
- 一键清仓 / 截图导入 也会产生待补评的流水
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.portfolio.repository import transaction_repo
from app.repositories.trade_score_repo import trade_score_repo


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def scored_calls(monkeypatch):
    """记录被触发的评分任务(trade_id, with_comment)"""
    from app.services.diagnose_service import diagnose_service

    calls: list[tuple] = []

    async def _fake(trade_id, with_comment=True):
        calls.append((trade_id, with_comment))

    monkeypatch.setattr(diagnose_service, "score_and_notify", _fake)
    return calls


def _seed_scored(trade_id: int, score: int = 70) -> None:
    async def _do():
        await trade_score_repo.upsert(
            trade_id=trade_id,
            score=score,
            score_breakdown="{}",
            ai_provider="deepseek",
        )

    asyncio.run(_do())


class TestBackfillCandidates:
    def test_only_unscored_selected(self, client, scored_calls):
        async def _seed():
            t1 = await transaction_repo.create(
                stock_code="600519.SH", action="buy", shares=100,
                price="1400.000", trade_date=date(2026, 7, 10),
            )
            t2 = await transaction_repo.create(
                stock_code="600519.SH", action="sell", shares=100,
                price="1450.000", trade_date=date(2026, 7, 20),
            )
            return t1, t2

        t1, t2 = asyncio.run(_seed())
        _seed_scored(t1.id)

        r = client.post("/api/diagnose/backfill", json={"force": False})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["candidates"] == 1
        assert data["trade_ids"] == [t2.id]
        assert scored_calls == [(t2.id, True)]

    def test_force_rescores_everything(self, client, scored_calls):
        async def _seed():
            t1 = await transaction_repo.create(
                stock_code="600519.SH", action="buy", shares=100,
                price="1400.000", trade_date=date(2026, 7, 10),
            )
            t2 = await transaction_repo.create(
                stock_code="600519.SH", action="sell", shares=100,
                price="1450.000", trade_date=date(2026, 7, 20),
            )
            return t1, t2

        t1, t2 = asyncio.run(_seed())
        _seed_scored(t1.id)

        r = client.post("/api/diagnose/backfill", json={"force": True})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["candidates"] == 2
        assert sorted(data["trade_ids"]) == sorted([t1.id, t2.id])

    def test_no_comment_flag_skips_llm(self, client, scored_calls):
        async def _seed():
            return await transaction_repo.create(
                stock_code="600519.SH", action="buy", shares=100,
                price="1400.000", trade_date=date(2026, 7, 10),
            )

        t1 = asyncio.run(_seed())
        r = client.post(
            "/api/diagnose/backfill",
            json={"force": True, "include_comment": False},
        )
        assert r.status_code == 200, r.text
        assert scored_calls == [(t1.id, False)]

    def test_stock_code_scope(self, client, scored_calls):
        async def _seed():
            a = await transaction_repo.create(
                stock_code="600519.SH", action="buy", shares=100,
                price="1400.000", trade_date=date(2026, 7, 10),
            )
            b = await transaction_repo.create(
                stock_code="000001.SZ", action="buy", shares=100,
                price="10.500", trade_date=date(2026, 7, 10),
            )
            return a, b

        a, b = asyncio.run(_seed())
        r = client.post(
            "/api/diagnose/backfill",
            json={"force": True, "stock_code": "600519"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["trade_ids"] == [a.id]

    def test_idempotent(self, client, scored_calls):
        """重复执行不报错(第二次仍能找到同一批未评分的)"""

        async def _seed():
            return await transaction_repo.create(
                stock_code="600519.SH", action="buy", shares=100,
                price="1400.000", trade_date=date(2026, 7, 10),
            )

        t1 = asyncio.run(_seed())
        r1 = client.post("/api/diagnose/backfill", json={"force": False})
        r2 = client.post("/api/diagnose/backfill", json={"force": False})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["candidates"] == 1
        assert r2.json()["candidates"] == 1

    def test_route_not_parsed_as_trade_id(self, client, scored_calls):
        """/backfill 不能被 /{trade_id} 抢走(否则 trade_id=int 解析失败 → 422)"""
        r = client.post("/api/diagnose/backfill", json={})
        assert r.status_code == 200, r.text
        assert "candidates" in r.json()


class TestScoringTriggeredPaths:
    """两条曾经漏评的写入路径:一键清仓 / 截图导入"""

    def test_clear_position_triggers_scoring(self, client, scored_calls):
        client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 100, "cost_price": "1450.000"},
        )
        r = client.post(
            "/api/positions/600519/clear",
            json={"price": "1500.000"},
        )
        assert r.status_code == 201, r.text
        trade_id = r.json()["trade_id"]
        assert (trade_id, True) in scored_calls

    def test_clear_position_records_trade_time(self, client):
        """清仓发生在当下 → 时间点 = 当前时刻(不是未知)"""
        client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 100, "cost_price": "1450.000"},
        )
        client.post(
            "/api/positions/600519/clear",
            json={"price": "1500.000"},
        )
        items = client.get("/api/transactions").json()["items"]
        assert items[0]["trade_time"] is not None
