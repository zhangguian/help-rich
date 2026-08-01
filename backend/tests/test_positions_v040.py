"""v0.4.0 持仓主数据化测试

- 流水自动同步持仓(recalc delta+flow)
- 导入基准保留(upsert 后流水变动不丢失)
- 持仓 CRUD(手动录入 / 删除联动删流水)
- 截图 holdings 导入端到端(API 路径)
- 年账单无流水提示
- 持仓体检 API
"""
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


def _buy(client, code, name, shares, price, trade_date="2026-07-25"):
    r = client.post(
        "/api/transactions",
        json={
            "stock_code": code,
            "stock_name": name,
            "action": "buy",
            "shares": shares,
            "price": price,
            "trade_date": trade_date,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _sell(client, code, shares, price, trade_date="2026-07-26"):
    r = client.post(
        "/api/transactions",
        json={
            "stock_code": code,
            "action": "sell",
            "shares": shares,
            "price": price,
            "trade_date": trade_date,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestFlowSyncsPositions:
    """流水自动同步持仓(v0.4.0 核心)"""

    def test_buy_creates_position(self, client):
        _buy(client, "000001", "平安银行", 1000, "10.500")
        r = client.get("/api/positions")
        items = r.json()["items"]
        assert len(items) == 1
        p = items[0]
        assert p["stock_code"] == "000001.SZ"
        assert p["shares"] == 1000
        assert p["avg_cost"] == "10.500"
        assert p["total_cost"] == "10500.00"

    def test_sell_reduces_position(self, client):
        _buy(client, "000001", "平安银行", 1000, "10.500")
        _sell(client, "000001", 400, "12.000")
        r = client.get("/api/positions")
        p = r.json()["items"][0]
        assert p["shares"] == 600
        # 成本 = 600 × 10.5(部分卖出不改变摊薄成本)
        assert p["avg_cost"] == "10.500"
        assert p["total_cost"] == "6300.00"
        assert p["realized_pnl"] == "600.00"  # (12 - 10.5) * 400

    def test_sell_all_removes_position(self, client):
        _buy(client, "000001", "平安银行", 1000, "10.500")
        _sell(client, "000001", 1000, "12.000")
        r = client.get("/api/positions")
        assert r.json()["items"] == []

    def test_sell_over_quota_rejected(self, client):
        _buy(client, "000001", "平安银行", 1000, "10.500")
        r = client.post(
            "/api/transactions",
            json={
                "stock_code": "000001",
                "action": "sell",
                "shares": 2000,
                "price": "12.000",
                "trade_date": "2026-07-26",
            },
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "INSUFFICIENT_SHARES"


class TestManualPosition:
    """手动录入 / 覆盖 / 删除(v0.4.0 持仓主数据)"""

    def test_create_position(self, client):
        r = client.post(
            "/api/positions",
            json={
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "shares": 100,
                "cost_price": "1450.000",
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["stock_code"] == "600519.SH"
        assert body["shares"] == 100
        assert body["avg_cost"] == "1450.000"
        assert body["total_cost"] == "145000.00"

    def test_create_requires_cost_price(self, client):
        r = client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 100},
        )
        assert r.status_code == 422

    def test_upsert_overwrites(self, client):
        client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 100, "cost_price": "1450.000"},
        )
        r = client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 200, "cost_price": "1400.000"},
        )
        assert r.status_code == 201
        assert r.json()["shares"] == 200
        assert r.json()["avg_cost"] == "1400.000"

    def test_imported_baseline_survives_flow(self, client):
        """导入 1000 股@10 → 流水买入 500@12 → 持仓 = 导入基准 + 流水 = 1500"""
        client.post(
            "/api/positions",
            json={"stock_code": "000001", "shares": 1000, "cost_price": "10.000"},
        )
        _buy(client, "000001", "平安银行", 500, "12.000")
        r = client.get("/api/positions")
        p = r.json()["items"][0]
        assert p["shares"] == 1500

    def test_delete_position_cascades_transactions(self, client):
        _buy(client, "000001", "平安银行", 1000, "10.500")
        r = client.delete("/api/positions/000001")
        assert r.status_code == 204
        # 持仓清空 + 流水联动删除(防 recalc 复活)
        assert client.get("/api/positions").json()["items"] == []
        assert client.get("/api/transactions").json()["total"] == 0

    def test_delete_missing_position_404(self, client):
        r = client.delete("/api/positions/999999")
        assert r.status_code == 404


class TestScreenshotHoldingsImport:
    """截图粘贴 JSON 持仓示例 → 一键导入(v0.4.0 关键路径)"""

    def test_paste_holdings_confirm_imports(self, client):
        raw = {
            "screenshot_type": "holdings",
            "items": [
                {"stock_code": "001896.SZ", "stock_name": "豫能控股",
                 "shares": 300, "price": "18.500"},
                {"stock_code": "600519.SH", "stock_name": "贵州茅台",
                 "shares": 100, "price": "1450.000"},
            ],
        }
        import json

        r = client.post("/api/screenshot/parse-paste", json={"raw_json": json.dumps(raw)})
        assert r.status_code == 200, r.text
        record_id = r.json()["record_id"]

        r2 = client.post(
            f"/api/screenshot/{record_id}/confirm",
            json={"items": raw["items"], "screenshot_type": "holdings"},
        )
        assert r2.status_code == 200

        positions = client.get("/api/positions").json()["items"]
        by_code = {p["stock_code"]: p for p in positions}
        assert by_code["001896.SZ"]["shares"] == 300
        assert by_code["001896.SZ"]["avg_cost"] == "18.500"
        assert by_code["600519.SH"]["shares"] == 100

    def test_paste_holdings_missing_cost_rejected(self, client):
        raw = {
            "screenshot_type": "holdings",
            "items": [{"stock_code": "001896.SZ", "stock_name": "豫能控股",
                       "shares": 300}],
        }
        import json

        r = client.post("/api/screenshot/parse-paste", json={"raw_json": json.dumps(raw)})
        record_id = r.json()["record_id"]
        r2 = client.post(
            f"/api/screenshot/{record_id}/confirm",
            json={"items": raw["items"], "screenshot_type": "holdings"},
        )
        assert r2.status_code == 422
        assert r2.json()["detail"]["code"] == "MISSING_PRICE"


class TestAnnualReportNoTransactions:
    def test_no_transactions_flag(self, client):
        r = client.get("/api/annual-report/2026")
        assert r.status_code == 200
        data = r.json()
        assert data["no_transactions"] is True
        assert data["net_pnl"] == "0.00"
        assert data["closed_count"] == 0

    def test_with_transactions_flag_false(self, client):
        _buy(client, "000001", "平安银行", 1000, "10.500")
        r = client.get("/api/annual-report/2026")
        assert r.json()["no_transactions"] is False


class TestHoldingsHealthAPI:
    def test_empty_holdings(self, client):
        r = client.get("/api/holdings-health")
        assert r.status_code == 200
        data = r.json()
        assert data["total_positions"] == 0
        assert data["items"] == []

    def test_with_positions(self, client, monkeypatch):
        from datetime import datetime
        from decimal import Decimal

        from app.data.unified import UnifiedQuote

        class FakeQuotes:
            async def get_quotes(self, codes):
                return [
                    UnifiedQuote(
                        code=c, name="测试股",
                        current_price=Decimal("20.00"), prev_close=Decimal("19.00"),
                        open=Decimal("19.00"), high=Decimal("20.50"),
                        low=Decimal("18.80"), change=Decimal("1.00"),
                        change_pct=5.26, volume=10000, amount=Decimal("200000"),
                        timestamp=datetime.now(),
                    )
                    for c in codes
                ]

        monkeypatch.setattr(
            "app.services.holdings_health_service.QuoteService", lambda: FakeQuotes()
        )
        client.post(
            "/api/positions",
            json={"stock_code": "600519", "shares": 100, "cost_price": "10.000"},
        )
        r = client.get("/api/holdings-health")
        assert r.status_code == 200
        data = r.json()
        assert data["total_positions"] == 1
        assert data["total_market_value"] == "2000.00"
        assert data["total_floating_pnl"] == "1000.00"
        assert data["pnl_ratio_pct"] == 50.0  # 浮盈 1000 / 市值 2000
        item = data["items"][0]
        # 单只 100% 集中度优先于盈亏状态(v0.4.0 状态优先级设计)
        assert item["status"] == "high_concentration"
        assert item["price_available"] is True
        assert data["quotes_unavailable"] is False

    def test_loss_status_when_diversified(self, client, monkeypatch):
        from datetime import datetime
        from decimal import Decimal

        from app.data.unified import UnifiedQuote

        class FakeQuotes:
            async def get_quotes(self, codes):
                return [
                    UnifiedQuote(
                        code=c, name="测试股",
                        current_price=Decimal("8.00"), prev_close=Decimal("9.00"),
                        open=Decimal("9.00"), high=Decimal("9.50"),
                        low=Decimal("7.80"), change=Decimal("-1.00"),
                        change_pct=-11.1, volume=10000, amount=Decimal("80000"),
                        timestamp=datetime.now(),
                    )
                    for c in codes
                ]

        monkeypatch.setattr(
            "app.services.holdings_health_service.QuoteService", lambda: FakeQuotes()
        )
        # 四只等额 → 单只 25% < 30%,无高集中,应显示盈亏状态
        for code in ("600519", "000001", "300750", "002415"):
            client.post(
                "/api/positions",
                json={"stock_code": code, "shares": 100, "cost_price": "10.000"},
            )
        r = client.get("/api/holdings-health")
        data = r.json()
        assert data["total_positions"] == 4
        statuses = {i["stock_code"]: i["status"] for i in data["items"]}
        assert all(s == "loss" for s in statuses.values())
        assert data["total_floating_pnl"] == "-800.00"
