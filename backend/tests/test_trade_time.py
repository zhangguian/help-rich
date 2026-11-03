"""交易时间节点(trade_time):存储 / 链排序 / 契约校验

覆盖:
- 录入带时间 → 落库回读一致(HH:MM:SS)
- 时间缺省 = 未知(NULL,不编造)
- 非法时间格式 → 422
- PATCH 可改时间
- **同日两笔按时间排序**(不是按录入顺序)→ 成本链结果随之改变
- 存量兼容:时间全为 NULL 时,顺序与改动前(按 id)完全一致
"""
import asyncio
from datetime import date, time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.portfolio.repository import transaction_repo


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_scoring(monkeypatch):
    """不跑真实评分(要打网络):这里只验证录入 / 排序 / 契约行为"""
    from app.services.diagnose_service import diagnose_service

    async def _fake(trade_id, with_comment=True):
        return None

    monkeypatch.setattr(diagnose_service, "score_and_notify", _fake)


def _tx(client, **over):
    body = {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "action": "buy",
        "shares": 100,
        "price": "1400.000",
        "trade_date": "2026-07-25",
    }
    body.update(over)
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ============================================================
# 存储
# ============================================================

class TestTradeTimeStorage:
    def test_repo_create_persists_trade_time(self):
        async def _do():
            return await transaction_repo.create(
                stock_code="600519.SH",
                action="buy",
                shares=100,
                price="1400.000",
                trade_date=date(2026, 7, 25),
                trade_time=time(14, 30, 5),
            )

        row = asyncio.run(_do())
        assert row.trade_time == time(14, 30, 5)

    def test_api_accepts_trade_time(self, client):
        tx = _tx(client, trade_time="14:38")
        assert tx["trade_time"] == "14:38:00"

    def test_api_accepts_trade_time_with_seconds(self, client):
        tx = _tx(client, trade_time="09:35:12")
        assert tx["trade_time"] == "09:35:12"

    def test_api_trade_time_optional_is_unknown(self, client):
        """不填时间 → NULL(未知),不编造"""
        tx = _tx(client)
        assert tx["trade_time"] is None

    def test_api_empty_trade_time_is_unknown(self, client):
        tx = _tx(client, trade_time="")
        assert tx["trade_time"] is None

    def test_api_rejects_invalid_trade_time(self, client):
        r = client.post(
            "/api/transactions",
            json={
                "stock_code": "600519",
                "action": "buy",
                "shares": 100,
                "price": "1400.000",
                "trade_date": "2026-07-25",
                "trade_time": "25:00",
            },
        )
        assert r.status_code == 422

    def test_api_rejects_garbage_trade_time(self, client):
        r = client.post(
            "/api/transactions",
            json={
                "stock_code": "600519",
                "action": "buy",
                "shares": 100,
                "price": "1400.000",
                "trade_date": "2026-07-25",
                "trade_time": "abc",
            },
        )
        assert r.status_code == 422

    def test_api_patch_trade_time(self, client):
        tx = _tx(client)
        r = client.patch(f"/api/transactions/{tx['id']}", json={"trade_time": "13:05"})
        assert r.status_code == 200, r.text
        assert r.json()["trade_time"] == "13:05:00"

    def test_list_returns_trade_time(self, client):
        _tx(client, trade_time="14:38")
        items = client.get("/api/transactions").json()["items"]
        assert items[0]["trade_time"] == "14:38:00"


# ============================================================
# 链排序
# ============================================================

class TestChainOrdering:
    def test_chain_sort_key_orders_by_time_within_day(self):
        from app.modules.portfolio.service import chain_sort_key

        d = date(2026, 7, 25)
        early = chain_sort_key(d, time(9, 35), 2)
        late = chain_sort_key(d, time(14, 0), 1)
        assert early < late  # 时间优先于 id

    def test_chain_sort_key_unknown_time_sorts_first(self):
        """时间未知(NULL)排在同日有时间的流水之前"""
        from app.modules.portfolio.service import chain_sort_key

        d = date(2026, 7, 25)
        unknown = chain_sort_key(d, None, 9)
        timed = chain_sort_key(d, time(9, 30), 1)
        assert unknown < timed

    def test_same_day_orders_by_time_not_insertion(self, client):
        """同日两笔:后录的 09:35 买排在先录的 14:00 卖之前 → 成本链按时间重放

        基准 1000 股 @10.500:
        - 先录 14:00 卖 100 @12.000
        - 后录 09:35 买 100 @11.000
        按时间重放 → 先买后卖 → 均价 (10500+1100)/1100 = 10.545454…
          → 已实现 (12 - 10.545454…) × 100 = 145.45
        按 id 重放(旧行为) → 先卖后买 → 已实现 (12 - 10.5) × 100 = 150.00
        """
        client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 1000, "cost_price": "10.500"},
        )
        _tx(
            client,
            action="sell",
            shares=100,
            price="12.000",
            trade_date="2026-07-25",
            trade_time="14:00",
        )
        _tx(
            client,
            action="buy",
            shares=100,
            price="11.000",
            trade_date="2026-07-25",
            trade_time="09:35",
        )

        pos = client.get("/api/positions").json()["items"][0]
        assert pos["realized_pnl"] == "145.45"

    def test_null_time_keeps_insertion_order(self, client):
        """存量兼容:时间全为 NULL → 顺序仍按 id(与改动前一致)"""
        client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 1000, "cost_price": "10.500"},
        )
        # 先录卖、后录买(都没有时间)→ 旧顺序:先卖 100 @12,再买 100 @11
        _tx(
            client,
            action="sell",
            shares=100,
            price="12.000",
            trade_date="2026-07-25",
        )
        _tx(
            client,
            action="buy",
            shares=100,
            price="11.000",
            trade_date="2026-07-25",
        )

        pos = client.get("/api/positions").json()["items"][0]
        # 先卖后买 → 已实现 (12 - 10.5) × 100 = 150.00
        assert pos["realized_pnl"] == "150.00"
        assert pos["shares"] == 1000

    def test_replay_snapshot_written_in_time_order(self, client):
        """每笔流水的 after 快照按时间顺序落位"""
        _tx(client, action="buy", shares=100, price="10.000",
            trade_date="2026-07-25", trade_time="09:30")
        _tx(client, action="buy", shares=100, price="11.000",
            trade_date="2026-07-25", trade_time="14:00")

        items = client.get("/api/transactions", params={"stock_code": "600519"}).json()["items"]
        by_time = sorted(items, key=lambda t: t["trade_time"])
        # 09:30 那笔的快照 = 100 股;14:00 那笔 = 200 股
        assert by_time[0]["shares_after"] == 100
        assert by_time[1]["shares_after"] == 200
