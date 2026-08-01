"""持仓 API 今日盈亏测试(P3.5.4 验收)

- 独立临时 SQLite(conftest.py 设置 DATABASE_URL,不污染开发库)
- monkeypatch QuoteService 为假实现,不依赖网络
- 验证 /api/positions 返回 current_price / today_pnl / floating_pnl
- 行情全失败时降级为 null
"""
from datetime import datetime
from decimal import Decimal

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.data.unified import UnifiedQuote
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db(client):
    """每个测试前清空 transactions 表,保证断言独立(依赖 client 完成建表)"""
    from app.db import async_session
    from app.models.orm import Transaction
    from sqlalchemy import delete

    async def _clean():
        async with async_session() as session:
            await session.execute(delete(Transaction))
            await session.commit()

    asyncio.run(_clean())
    yield


class FakeQuoteService:
    """假行情服务:返回固定价格"""

    async def get_quotes(self, codes):
        price_map = {
            "000001.SZ": ("11.63", "11.61"),
            "600519.SH": ("1350.60", "1361.76"),
        }
        out = []
        for code in codes:
            price, prev = price_map.get(code, ("10.00", "9.50"))
            p, pc = Decimal(price), Decimal(prev)
            out.append(
                UnifiedQuote(
                    code=code,
                    name="测试股",
                    current_price=p,
                    prev_close=pc,
                    open=pc,
                    high=p,
                    low=pc,
                    change=p - pc,
                    change_pct=float((p / pc - 1) * 100),
                    volume=10000,
                    amount=Decimal("100000"),
                    timestamp=datetime.now(),
                )
            )
        return out


@pytest.fixture()
def patch_quotes(monkeypatch):
    monkeypatch.setattr(
        "app.api.positions.get_quote_service", lambda: FakeQuoteService()
    )


def _seed_tx(client: TestClient):
    """造一笔:买入 1000 股 @10.50"""
    r = client.post(
        "/api/transactions",
        json={
            "stock_code": "000001",
            "stock_name": "平安银行",
            "action": "buy",
            "shares": 1000,
            "price": "10.500",
            "trade_date": "2026-07-25",
        },
    )
    assert r.status_code == 201, r.text


class TestPositionsWithQuotes:
    def test_positions_with_quote_fields(self, client, patch_quotes):
        _seed_tx(client)
        r = client.get("/api/positions")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        p = items[0]
        # 迁移后的代码格式
        assert p["stock_code"] == "000001.SZ"
        # 行情字段
        assert p["current_price"] == "11.63"
        assert p["prev_close"] == "11.61"
        # 今日盈亏 = (11.63 - 11.61) * 1000 = 20.00
        assert p["today_pnl"] == "20.00"
        # 浮动盈亏 = (11.63 - 10.50) * 1000 = 1130.00
        assert p["floating_pnl"] == "1130.00"

    def test_stock_code_normalized_on_create(self, client, patch_quotes):
        """录入时纯 6 位代码自动补市场后缀"""
        _seed_tx(client)
        r = client.get("/api/transactions")
        tx = r.json()["items"][0]
        assert tx["stock_code"] == "000001.SZ"

    def test_invalid_stock_code_rejected(self, client, patch_quotes):
        r = client.post(
            "/api/transactions",
            json={
                "stock_code": "12x",
                "action": "buy",
                "shares": 100,
                "price": "10.500",
                "trade_date": "2026-07-25",
            },
        )
        assert r.status_code == 422


class TestQuotesDegraded:
    def test_quotes_all_fail_returns_null(self, client, monkeypatch):
        """行情全失败时 current_price 等为 null(前端降级)"""

        class DownService:
            async def get_quotes(self, codes):
                return []

        monkeypatch.setattr("app.api.positions.get_quote_service", lambda: DownService())
        _seed_tx(client)
        r = client.get("/api/positions")
        assert r.status_code == 200
        p = r.json()["items"][0]
        assert p["current_price"] is None
        assert p["today_pnl"] is None
        assert p["floating_pnl"] is None


class TestCalculatorNormalize:
    """P3.6 联调:calculator 用纯 6 位代码也能查到带后缀的持仓"""

    def test_calc_with_bare_code_finds_position(self, client, patch_quotes):
        _seed_tx(client)
        r = client.post(
            "/api/calculator",
            json={
                "stock_code": "000001",  # 纯 6 位,应规范化到 000001.SZ
                "action": "buy",
                "tx_shares": 500,
                "tx_price": "11.000",
            },
        )
        assert r.status_code == 200
        data = r.json()
        # 找到持仓:before.shares = 1000(seed 的 000001)
        assert data["before"]["shares"] == 1000
        # 加仓后 1500
        assert data["after"]["shares"] == 1500
        # input 已规范化
        assert data["input"]["stock_code"] == "000001.SZ"

    def test_calc_sell_over_quota(self, client, patch_quotes):
        _seed_tx(client)
        r = client.post(
            "/api/calculator",
            json={
                "stock_code": "000001",
                "action": "sell",
                "tx_shares": 5000,
                "tx_price": "12.000",
            },
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "INSUFFICIENT_SHARES"

    def test_calc_with_suffix_code(self, client, patch_quotes):
        _seed_tx(client)
        r = client.post(
            "/api/calculator",
            json={
                "stock_code": "000001.SZ",
                "action": "buy",
                "tx_shares": 100,
                "tx_price": "11.500",
            },
        )
        assert r.status_code == 200
        assert r.json()["before"]["shares"] == 1000
