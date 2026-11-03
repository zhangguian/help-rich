"""v0.11 摊薄成本口径回归测试(券商对齐)

背景:
    券商持仓页的「成本价」= **摊薄成本** = 累计净投入 ÷ 当前持股数。
    v0.10 及以前系统内部记的是「加权平均剩余成本」,展示时再用
    `(total_cost − realized_pnl) ÷ shares` 反推摊薄成本 ——
    基准里带了券商给的累计已实现盈亏时,已实现被**二次扣减**,成本就对不上券商。

    v0.11 改成直接追踪净投入(摊薄总额),摊薄成本与券商**恒等**。

覆盖:
- 基准带已实现盈亏 → 摊薄成本不被二次扣减(豫能控股真实场景)
- 卖出后摊薄成本按成交价回收净投入(561980 ETF 真实场景,券商 1.077)
- 摊薄成本 = 净投入 ÷ 股数,总成本 = 净投入
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _baseline(client, code, shares, cost_price, name=None, realized_pnl=None):
    body = {"stock_code": code, "shares": shares, "cost_price": cost_price}
    if name:
        body["stock_name"] = name
    if realized_pnl is not None:
        body["realized_pnl"] = realized_pnl
    r = client.post("/api/positions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _sell(client, code, shares, price, trade_date):
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


def _pos(client, code):
    items = client.get("/api/positions").json()["items"]
    return next((p for p in items if p["stock_code"] == code), None)


class TestDilutedCost:
    def test_realized_pnl_not_deducted_twice(self, client):
        """基准带已实现盈亏 → 摊薄成本 = 券商给的成本价(不被二次扣减)

        豫能控股真实场景:基准 600 股 @15.580、券商给的累计已实现 +1293.00,
        11-02 卖出 200 股 @8.86 → 券商持仓页显示 400 股 @18.940。
        """
        _baseline(
            client, "001896", 600, "15.580",
            name="豫能控股", realized_pnl="1293.00",
        )
        p = _pos(client, "001896.SZ")
        # 录入值就是展示值(摊薄总额 = 15.580 × 600 = 9348.00)
        assert p["avg_cost"] == "15.580"
        assert p["total_cost"] == "9348.00"
        assert p["realized_pnl"] == "1293.00"

    def test_sell_reduces_net_invested_broker_aligned(self, client):
        """卖出后摊薄成本 = 券商口径(净投入 ÷ 股数)"""
        _baseline(
            client, "001896", 600, "15.580",
            name="豫能控股", realized_pnl="1293.00",
        )
        _sell(client, "001896", 200, "8.860", "2026-11-02")

        p = _pos(client, "001896.SZ")
        assert p["shares"] == 400
        # 净投入 9348.00 − 200×8.86 = 7576.00 → 7576.00 ÷ 400 = 18.940(券商一致)
        assert p["total_cost"] == "7576.00"
        assert p["avg_cost"] == "18.940"
        # 已实现 = 1293.00 + (8.86 − 15.58) × 200 = −51.00
        assert p["realized_pnl"] == "-51.00"

    def test_etf_partial_sell_matches_broker_cost(self, client):
        """半导体设备ETF 招商 561980 真实场景:券商 300 股 @1.077"""
        _baseline(client, "561980", 500, "0.831", name="半导体设备ETF招商")
        _sell(client, "561980", 200, "0.462", "2026-11-02")

        p = _pos(client, "561980.SH")
        assert p["shares"] == 300
        # 净投入 415.50 − 200×0.462 = 323.10 → ÷ 300 = 1.077(券商分毫不差)
        assert p["total_cost"] == "323.10"
        assert p["avg_cost"] == "1.077"
        assert p["realized_pnl"] == "-73.80"

    def test_cost_equals_net_invested_over_shares(self, client):
        """摊薄成本 = 净投入 ÷ 股数(券商口径)"""
        _baseline(client, "600519", 1000, "1450.000", name="贵州茅台")
        _sell(client, "600519", 300, "1500.000", "2026-11-02")

        p = _pos(client, "600519.SH")
        # 净投入 1450000 − 300×1500 = 1000000 → ÷ 700 = 1428.571
        assert p["shares"] == 700
        assert p["total_cost"] == "1000000.00"
        assert p["avg_cost"] == "1428.571"
