"""日内多次做T:仓位与成本必须与手算一致

口径(摊薄 / 券商持仓页):摊薄总额 = 累计买入金额 − 累计卖出金额,摊薄成本 = 摊薄总额 ÷ 持股数。
一次完整的反T(先卖后买)对摊薄总额的影响 = (+买回金额) − (卖出金额) = −做T收益。
所以日内做 N 次反T、每次赚 G,收完之后:股数不变、摊薄总额减少 N×G。

⚠️ 这个文件存在的理由:用户反馈「日内多次操作做T时仓位不对、成本不对」。
这里把多次做T的结果逐项钉死,任何一处口径漂移都会让某一条变红。
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import async_session
from app.main import app
from app.models.orm import Position as PositionRow
from app.services.diagnose_service import diagnose_service


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_quote(monkeypatch):
    import app.services.quote_service as qs

    class _Boom:
        async def get_quotes(self, codes):
            raise RuntimeError("行情源不可用")

    monkeypatch.setattr(qs, "get_quote_service", lambda: _Boom())


@pytest.fixture(autouse=True)
def _no_diagnose(monkeypatch):
    async def _noop(_tx_id):
        return None

    monkeypatch.setattr(diagnose_service, "score_and_notify", _noop)


def _seed_position(code: str, shares: int, total_cost: str):
    """建持仓基准(摊薄总额 = 净投入)。"""

    async def _do():
        async with async_session() as session:
            session.add(
                PositionRow(
                    account_id=1,
                    stock_code=code,
                    stock_name="测试股",
                    shares=shares,
                    total_cost=total_cost,
                    realized_pnl="0.00",
                    base_shares=shares,
                    base_total_cost=total_cost,
                    base_realized_pnl="0.00",
                    base_tx_id=0,
                )
            )
            await session.commit()

    asyncio.run(_do())


def _post(client, code, action, shares, price, d, t=None):
    body = {
        "stock_code": code,
        "action": action,
        "shares": shares,
        "price": price,
        "trade_date": d,
        "stock_name": "测试股",
    }
    if t:
        body["trade_time"] = t
    return client.post("/api/transactions", json=body)


def _position(client, code):
    for p in client.get("/api/positions").json()["items"]:
        if p["stock_code"] == code:
            return p
    return None


class TestIntradayMultiT:
    """基准 1000 股 / 净投入 15000.00(成本 15.000)"""

    def test_two_reverse_t_intraday(self, client):
        """日内两次反T(先卖后买),每次赚 100 → 股数不变,净投入 15000-200=14800"""
        code = "600519.SH"
        _seed_position(code, 1000, "15000.00")

        # T1: 09:40 卖 100@16.000 → 10:30 买回 100@15.000 (赚 100)
        assert _post(client, code, "sell", 100, "16.000", "2026-11-04", "09:40").status_code == 201
        assert _post(client, code, "buy", 100, "15.000", "2026-11-04", "10:30").status_code == 201
        # T2: 13:30 卖 100@16.000 → 14:20 买回 100@15.000 (再赚 100)
        assert _post(client, code, "sell", 100, "16.000", "2026-11-04", "13:30").status_code == 201
        assert _post(client, code, "buy", 100, "15.000", "2026-11-04", "14:20").status_code == 201

        pos = _position(client, code)
        assert pos is not None
        assert pos["shares"] == 1000  # 股数回到起点
        assert float(pos["total_cost"]) == pytest.approx(14800.00, abs=0.01)
        assert float(pos["avg_cost"]) == pytest.approx(14.800, abs=1e-6)

    def test_two_t_out_of_order_entry_same_day(self, client):
        """同日 4 笔**倒序录入**(接回先录)→ 链按时间点排序,结果必须与正序一致"""
        code = "600000.SH"
        _seed_position(code, 1000, "15000.00")

        # 倒着录:14:20 买回、13:30 卖出、10:30 买回、09:40 卖出
        assert _post(client, code, "buy", 100, "15.000", "2026-11-04", "14:20").status_code == 201
        assert _post(client, code, "sell", 100, "16.000", "2026-11-04", "13:30").status_code == 201
        assert _post(client, code, "buy", 100, "15.000", "2026-11-04", "10:30").status_code == 201
        assert _post(client, code, "sell", 100, "16.000", "2026-11-04", "09:40").status_code == 201

        pos = _position(client, code)
        assert pos["shares"] == 1000
        assert float(pos["total_cost"]) == pytest.approx(14800.00, abs=0.01)

    def test_intraday_t_then_close_legs_leave_no_pending(self, client):
        """两次做T都闭合 → 补T清单不残留挂单"""
        code = "000001.SZ"
        _seed_position(code, 1000, "15000.00")

        for t_sell, t_buy in (("09:40", "10:30"), ("13:30", "14:20")):
            assert (
                _post(client, code, "sell", 100, "16.000", "2026-11-04", t_sell).status_code
                == 201
            )
            assert (
                _post(client, code, "buy", 100, "15.000", "2026-11-04", t_buy).status_code
                == 201
            )

        body = client.get("/api/t-reminders/pending").json()
        assert body["total_count"] == 0

    def test_partial_intraday_t_keeps_remainder_pending(self, client):
        """日内卖出 300、只接回 100 → 还剩 200 股挂单(仓位与挂单都要对)"""
        code = "000002.SZ"
        _seed_position(code, 1000, "15000.00")

        assert _post(client, code, "sell", 300, "16.000", "2026-11-04", "09:40").status_code == 201
        assert _post(client, code, "buy", 100, "15.000", "2026-11-04", "10:30").status_code == 201

        pos = _position(client, code)
        # 1000 - 300 + 100 = 800
        assert pos["shares"] == 800

        body = client.get("/api/t-reminders/pending").json()
        assert body["count"] == 1
        item = body["items"][0]
        assert item["shares"] == 200
        assert item["position_shares"] == 800
        # 不亏本接回线 = 卖出的加权均价 = 16.000
        assert item["price"] == pytest.approx(16.0)
