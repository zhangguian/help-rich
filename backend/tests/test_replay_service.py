# -*- coding: utf-8 -*-
"""Tests for replay_service (v2.3).

- summarize_stock: window filter + 5-dim aggregation
- force_replay UPSERT: same (stock, window) -> only latest kept
- latest_tx_id invalidates cache when new transaction recorded
- window validation: 1d/3d/5d/10d/20d/60d only
"""
import asyncio
import json as _json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select as _select

from app.db import async_session
from app.main import app
from app.models.orm import ReplayRecord, TradeScore, Transaction


@pytest.fixture()
def client():
    # Disable async diagnose scoring (POST /transactions triggers background
    # diagnose_service.score_and_notify which writes trade_scores -> collides
    # with manual _seed_score on same trade_id).
    from app.services import diagnose_service
    original = diagnose_service.diagnose_service.score_and_notify

    async def _noop(trade_id):
        return None

    diagnose_service.diagnose_service.score_and_notify = _noop
    try:
        with TestClient(app) as c:
            yield c
    finally:
        diagnose_service.diagnose_service.score_and_notify = original


@pytest.fixture(autouse=True)
def _clean(client):
    """Clean tables before each test (depends on client to trigger lifespan)"""
    async def _do():
        async with async_session() as session:
            await session.execute(delete(ReplayRecord))
            await session.execute(delete(TradeScore))
            await session.execute(delete(Transaction))
            await session.commit()

    asyncio.run(_do())
    yield


def _seed_tx(client, code, action, shares, price, trade_date, stock_name=None):
    r = client.post(
        "/api/transactions",
        json={
            "stock_code": code,
            "stock_name": stock_name,
            "action": action,
            "shares": shares,
            "price": price,
            "trade_date": trade_date,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _seed_score(trade_id, score, breakdown):
    """Insert trade_scores directly (skip async diagnose to speed up tests)"""
    async def _do():
        async with async_session() as session:
            session.add(
                TradeScore(
                    trade_id=trade_id,
                    score=score,
                    score_breakdown=_json.dumps(breakdown, ensure_ascii=False),
                    ai_status="success",
                )
            )
            await session.commit()

    asyncio.run(_do())


# ============================================================
# Window validation
# ============================================================


class TestWindowValidation:
    def test_invalid_window_400(self, client):
        r = client.post(
            "/api/diagnose/stock/001896.SZ/summary",
            params={"window": "99d"},
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_WINDOW"

    def test_get_nonexistent_404(self, client):
        r = client.get(
            "/api/diagnose/stock/001896.SZ/summary",
            params={"window": "1d"},
        )
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "REPLAY_NOT_FOUND"


# ============================================================
# Aggregation + UPSERT
# ============================================================


class TestReplayService:
    def test_summarize_empty_window(self, client):
        """Empty window: returns 200 with score_avg=None"""
        r = client.post(
            "/api/diagnose/stock/001896.SZ/summary",
            params={"window": "1d"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["stock_code"] == "001896.SZ"
        assert body["window"] == "1d"
        assert body["score_avg"] is None
        assert body["dimension_avg"] == _full_breakdown(0.0, 0.0, 0.0, 0.0, 0.0)
        assert body["latest_tx_id"] == 0
        assert body["ai_status"] in ("success", "failed", "no_key")

    def test_force_replay_upsert_overwrites(self, client):
        """Same window force-replay -> UPSERT keeps only 1 row"""
        today = date.today().isoformat()
        _seed_tx(client, "001896", "buy", 100, "12.990", today)

        r1 = client.post(
            "/api/diagnose/stock/001896.SZ/summary",
            params={"window": "1d"},
        )
        assert r1.status_code == 200

        r2 = client.post(
            "/api/diagnose/stock/001896.SZ/summary",
            params={"window": "1d"},
        )
        assert r2.status_code == 200

        async def _count():
            async with async_session() as session:
                stmt = _select(ReplayRecord).where(
                    ReplayRecord.stock_code == "001896.SZ",
                    ReplayRecord.window == "1d",
                )
                return len(list((await session.execute(stmt)).scalars().all()))

        assert asyncio.run(_count()) == 1

    def test_new_tx_invalidates_cache(self, client):
        """New transaction changes latest_tx_id -> next replay sees fresh data"""
        today = date.today().isoformat()
        _seed_tx(client, "001896", "buy", 100, "12.990", today)

        r1 = client.post(
            "/api/diagnose/stock/001896.SZ/summary",
            params={"window": "1d"},
        )
        first = r1.json()
        first_latest = first["latest_tx_id"]
        assert first_latest > 0

        _seed_tx(client, "001896", "sell", 50, "13.500", today)
        r2 = client.post(
            "/api/diagnose/stock/001896.SZ/summary",
            params={"window": "1d"},
        )
        second = r2.json()
        assert second["latest_tx_id"] > first_latest

    def test_get_summary_returns_latest(self, client):
        """GET summary reads from DB (no LLM)"""
        today = date.today().isoformat()
        _seed_tx(client, "001896", "buy", 100, "12.990", today)
        client.post(
            "/api/diagnose/stock/001896.SZ/summary",
            params={"window": "5d"},
        )
        r = client.get(
            "/api/diagnose/stock/001896.SZ/summary",
            params={"window": "5d"},
        )
        assert r.status_code == 200
        assert r.json()["window"] == "5d"

    def test_summaries_returns_all_windows(self, client):
        """GET summaries returns all 6 windows (unreplayed -> None)"""
        r = client.get("/api/diagnose/stock/001896.SZ/summaries")
        assert r.status_code == 200
        windows = r.json()["windows"]
        assert set(windows.keys()) == {"1d", "3d", "5d", "10d", "20d", "60d"}
        assert all(windows[w] is None for w in windows)


# ============================================================
# Score aggregation
# ============================================================


# Use ASCII keys here? No - the backend DIM dict uses Chinese keys
# (集中度, 价格合理性, 操作间隔, 市场环境, 板块热度) per scorer.py
# We must match exactly so aggregation works.
_DIM_NAMES = [
    "\u96c6\u4e2d\u5ea6",      # 集中度
    "\u4ef7\u683c\u5408\u7406\u6027",  # 价格合理性
    "\u64cd\u4f5c\u95f4\u9694",  # 操作间隔
    "\u5e02\u573a\u73af\u5883",  # 市场环境
    "\u677f\u5757\u70ed\u5ea6",  # 板块热度
]


def _full_breakdown(a, b, c, d, e):
    return {
        _DIM_NAMES[0]: a,
        _DIM_NAMES[1]: b,
        _DIM_NAMES[2]: c,
        _DIM_NAMES[3]: d,
        _DIM_NAMES[4]: e,
    }


class TestScoreAggregation:
    def test_aggregates_5_dimension_scores(self, client):
        today = date.today().isoformat()
        # 3 buys with different breakdowns
        tx1 = _seed_tx(client, "600519", "buy", 100, "1450.000", today)
        _seed_score(tx1["id"], 80, _full_breakdown(18, 16, 14, 16, 16))

        tx2 = _seed_tx(client, "600519", "buy", 200, "1460.000", today)
        _seed_score(tx2["id"], 60, _full_breakdown(14, 8, 12, 14, 12))

        tx3 = _seed_tx(client, "600519", "buy", 300, "1470.000", today)
        _seed_score(tx3["id"], 70, _full_breakdown(16, 12, 14, 14, 14))

        r = client.post(
            "/api/diagnose/stock/600519.SH/summary",
            params={"window": "1d"},
        )
        body = r.json()
        # avg score = (80+60+70)/3 = 70.0
        assert body["score_avg"] == "70.00"
        # dimension averages
        assert body["dimension_avg"][_DIM_NAMES[0]] == 16.0
        assert body["dimension_avg"][_DIM_NAMES[1]] == 12.0
        # (14+12+14)/3 = 13.33 -> rounded 13.3
        assert body["dimension_avg"][_DIM_NAMES[2]] == 13.3
        # top 3 ascending
        assert body["top_issues"][0]["score"] <= body["top_issues"][1]["score"]