"""持仓「今日盈亏」· 券商口径(2026-11-04)

**为什么要有这个文件**:
项目原来算的是 `(现价 − 昨收) × 持股数`,但券商持仓页的「当日盈亏」是
**当日总资产变动**:

```
当日盈亏 = (当前持股×现价 + 今日卖出所得现金 − 今日买入支出现金)
           − 昨收 × 昨日持股数
昨日持股数 = 当前持股 − 今日买入股数 + 今日卖出股数
```

今天买卖过的票,两个口径差得很远(实测 000657 差 134 元、002185 差 95 元、
001896 差 7 元;5 只 ETF 分毫不差)。本文件把口径钉死,防止以后被改回去。

用例里的数字全部取自**用户 2026-11-04 的两张券商持仓截图**(深A 5 只 + ETF 6 只),
逐只与券商的「当日盈亏」核对过。
"""
from datetime import date, timedelta
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
def clean_db():
    """每个测试前清空 transactions + positions(依赖 conftest 的临时库)"""
    from app.db import async_session
    from app.models.orm import Position, Transaction
    from sqlalchemy import delete

    async def _clean():
        async with async_session() as session:
            await session.execute(delete(Transaction))
            await session.execute(delete(Position))
            await session.commit()

    asyncio.run(_clean())
    yield


class FakeQuoteService:
    """假行情:价格按代码给,默认 10.00 / 9.50"""

    def __init__(self, price_map: dict[str, tuple[str, str]]):
        self.price_map = price_map

    async def get_quotes(self, codes):
        out = []
        for code in codes:
            price, prev = self.price_map.get(code, ("10.000", "9.500"))
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
                    timestamp=date.today(),
                )
            )
        return out


@pytest.fixture()
def patch_quotes(monkeypatch):
    def _apply(price_map: dict[str, tuple[str, str]]):
        monkeypatch.setattr(
            "app.modules.portfolio.api_positions.get_quote_service",
            lambda: FakeQuoteService(price_map),
        )

    return _apply


def _seed_tx(client: TestClient, code: str, action: str, shares: int, price: str, when: date):
    r = client.post(
        "/api/transactions",
        json={
            "stock_code": code,
            "stock_name": "测试股",
            "action": action,
            "shares": shares,
            "price": price,
            "trade_date": when.isoformat(),
        },
    )
    assert r.status_code == 201, r.text


def _today_pnl_of(client: TestClient, code: str) -> Decimal:
    items = client.get("/api/positions").json()["items"]
    for it in items:
        if it["stock_code"] == code:
            return Decimal(it["today_pnl"])
    raise AssertionError(f"持仓里没有 {code}")


class TestTodayPnlBrokerParity:
    """与券商持仓页逐只核对(数字来自 2026-11-04 券商截图)"""

    def test_today_sell_is_counted_at_sell_price(self, client, patch_quotes):
        """000657 中钨高新:今日 09:37 卖 100@37.000,现价 39.230,昨收 35.660

        券商当日盈亏 = 1,205.00
          旧口径 (39.230−35.660)×300                      = 1,071.00
          新口径 (300×39.230 + 100×37.000) − 35.660×400   = 1,205.00
        """
        today = date.today()
        # 先有 400 股底仓(3 天前),今天卖 100 → 当前 300 股
        _seed_tx(client, "000657", "buy", 400, "40.000", today - timedelta(days=3))
        _seed_tx(client, "000657", "sell", 100, "37.000", today)
        patch_quotes({"000657.SZ": ("39.230", "35.660")})
        assert _today_pnl_of(client, "000657.SZ") == Decimal("1205.00")

    def test_today_buy_is_counted_at_buy_price(self, client, patch_quotes):
        """001896 豫能控股:今日 09:59 买 100@8.760,现价 9.050,昨收 8.830

        券商当日盈亏 = 139.00
          新口径 (600×9.050 + 0 − 100×8.760) − 8.830×500 = 139.00
        """
        today = date.today()
        _seed_tx(client, "001896", "buy", 100, "8.760", today)
        _seed_tx(client, "001896", "buy", 500, "16.000", today - timedelta(days=3))
        patch_quotes({"001896.SZ": ("9.050", "8.830")})
        assert _today_pnl_of(client, "001896.SZ") == Decimal("139.00")

    def test_no_today_flow_falls_back_to_price_diff(self, client, patch_quotes):
        """今天没买卖 → 退化成 (现价 − 昨收) × 持股数(旧口径,不能变)"""
        _seed_tx(client, "000807", "buy", 100, "8.000", date.today() - timedelta(days=3))
        patch_quotes({"000807.SZ": ("25.300", "25.080")})
        assert _today_pnl_of(client, "000807.SZ") == Decimal("22.00")

    def test_yesterday_trade_is_not_counted_twice(self, client, patch_quotes):
        """昨天的成交已经体现在昨收里 → 不能再算一次"""
        _seed_tx(client, "588160", "buy", 3100, "1.300", date.today() - timedelta(days=3))
        _seed_tx(client, "588160", "sell", 1000, "0.802", date.today() - timedelta(days=1))
        patch_quotes({"588160.SH": ("0.807", "0.735")})
        # 2100 股 × (0.807 − 0.735) = 151.20(昨天的卖出不进今日口径)
        assert _today_pnl_of(client, "588160.SH") == Decimal("151.20")

    def test_pure_function_matches_broker_formula(self):
        """直接测纯函数:公式与券商口径一致"""
        from app.modules.portfolio.api_positions import _today_pnl

        flow = {
            "buy_amount": Decimal("876.00"),
            "buy_shares": 100,
            "sell_amount": Decimal("0"),
            "sell_shares": 0,
        }
        got = _today_pnl(600, Decimal("9.050"), Decimal("8.830"), flow)
        assert got == Decimal("139.00")

    def test_missing_prev_close_falls_back(self):
        """昨收不可用(≤0)→ 退回旧口径,不拿 0 当昨收算"""
        from app.modules.portfolio.api_positions import _today_pnl

        flow = {
            "buy_amount": Decimal("876.00"),
            "buy_shares": 100,
            "sell_amount": Decimal("0"),
            "sell_shares": 0,
        }
        got = _today_pnl(600, Decimal("9.050"), Decimal("0"), flow)
        assert got == Decimal("9.050") * 600
