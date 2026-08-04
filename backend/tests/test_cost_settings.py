"""GB-001 IR-4 交易费用设置 API 测试

- GET /api/cost/settings:读取(默认关闭)
- PUT /api/cost/settings:保存(校验 Decimal/非负)
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


class TestCostSettingsAPI:
    def test_get_default_disabled(self, client):
        """默认:关闭 + 默认费率"""
        r = client.get("/api/cost/settings")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["commission_rate"] == "0.00025"
        assert body["min_commission"] == "5.00"

    def test_put_save_and_read_back(self, client):
        r = client.put("/api/cost/settings", json={
            "enabled": True,
            "commission_rate": "0.0003",
            "min_commission": "1.00",
            "stamp_tax_rate": "0.0005",
            "transfer_fee_rate": "0.00002",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is True
        assert body["commission_rate"] == "0.0003"
        assert body["min_commission"] == "1.00"

        r2 = client.get("/api/cost/settings")
        assert r2.json()["enabled"] is True
        assert r2.json()["commission_rate"] == "0.0003"

    def test_put_invalid_rate_rejected(self, client):
        r = client.put("/api/cost/settings", json={
            "enabled": True,
            "commission_rate": "abc",
            "min_commission": "5.00",
            "stamp_tax_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        })
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_RATE"

    def test_put_negative_rejected(self, client):
        r = client.put("/api/cost/settings", json={
            "enabled": True,
            "commission_rate": "-0.001",
            "min_commission": "5.00",
            "stamp_tax_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        })
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "INVALID_RATE"


class TestCostEngineFees:
    def test_buy_fee_added_to_cost(self):
        """IR-4:买入费用计入成本"""
        from decimal import Decimal

        from app.core.cost_engine import TradeFees, calculate_after_transaction

        fees = TradeFees(enabled=True)
        r = calculate_after_transaction(
            shares_before=0, cost_before=Decimal("0"), action="buy",
            tx_shares=1000, tx_price=Decimal("10.000"), fees=fees,
        )
        assert r["total_cost_after"] == Decimal("10005.10")  # 10000 + 佣金5 + 过户0.10

    def test_sell_net_less_than_gross(self):
        from decimal import Decimal

        from app.core.cost_engine import TradeFees, calculate_after_transaction

        fees = TradeFees(enabled=True)
        r_buy = calculate_after_transaction(
            shares_before=0, cost_before=Decimal("0"), action="buy",
            tx_shares=1000, tx_price=Decimal("10.000"), fees=fees,
        )
        r_sell = calculate_after_transaction(
            shares_before=1000, cost_before=r_buy["cost_after"],
            action="sell", tx_shares=1000, tx_price=Decimal("15.000"), fees=fees,
        )
        assert r_sell["realized_pnl_net"] < r_sell["realized_pnl_gross"]
        # 卖出费用 = 佣金5 + 印花税 15000*0.0005=7.5 + 过户15000*0.00001=0.15 = 12.65
        assert r_sell["fee_paid"] == Decimal("12.65")

    def test_fees_disabled_unchanged(self):
        """default:关闭时不产生任何费用,与旧版一致"""
        from decimal import Decimal

        from app.core.cost_engine import TradeFees, calculate_after_transaction

        fees = TradeFees(enabled=False)
        r_buy = calculate_after_transaction(
            shares_before=0, cost_before=Decimal("0"), action="buy",
            tx_shares=1000, tx_price=Decimal("10.000"), fees=fees,
        )
        assert r_buy["total_cost_after"] == Decimal("10000.00")
        assert r_buy["fee_paid"] == Decimal("0")
        r_buy_nofee = calculate_after_transaction(
            shares_before=0, cost_before=Decimal("0"), action="buy",
            tx_shares=1000, tx_price=Decimal("10.000"),
        )
        assert r_buy["total_cost_after"] == r_buy_nofee["total_cost_after"]