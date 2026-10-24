"""v0.5.0 成本事件溯源测试(方案B)

核心不变量:
    当前持仓 = 基准(base_*) + 其后所有 id > base_tx_id 的流水
               按 (trade_date, id) 顺序逐笔加权平均应用

覆盖:
- 每笔流水存自己的 after 快照(事件溯源)
- 改 / 删任意一笔 → 从基准精确回滚,链尾快照全部重写
- 导入基准吸收历史流水 → 不再双算(华天科技真实场景回归)
- 已被基准吸收的流水:改 / 删明确拒绝(409 TX_ABSORBED)
- 卖出额度按「该笔落位时」的持仓判定(补录更早日期也准)
- 清仓保留已实现盈亏(可为负)
"""
import asyncio
from datetime import date
from decimal import Decimal

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


def _tx(client, code, action, shares, price, trade_date, name=None):
    body = {
        "stock_code": code,
        "action": action,
        "shares": shares,
        "price": price,
        "trade_date": trade_date,
    }
    if name:
        body["stock_name"] = name
    r = client.post("/api/transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _baseline(client, code, shares, cost_price, name=None, realized_pnl=None):
    body = {
        "stock_code": code,
        "shares": shares,
        "cost_price": cost_price,
    }
    if name:
        body["stock_name"] = name
    if realized_pnl is not None:
        body["realized_pnl"] = realized_pnl
    r = client.post("/api/positions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _pos(client, code):
    items = client.get("/api/positions").json()["items"]
    return next((p for p in items if p["stock_code"] == code), None)


def _txs(client, code):
    items = client.get("/api/transactions", params={"stock_code": code}).json()["items"]
    return sorted(items, key=lambda t: (t["trade_date"], t["id"]))


# ============================================================
# 纯函数
# ============================================================

class TestPureChain:
    def test_replay_from_baseline(self):
        from app.modules.portfolio.service import ChainState, TxSpec, replay_chain

        base = ChainState(800, Decimal("13896.80"), Decimal("0"))
        specs = [
            TxSpec(9, date(2026, 10, 22), "buy", 200, Decimal("15.680")),
            TxSpec(10, date(2026, 10, 23), "sell", 100, Decimal("16.420")),
            TxSpec(11, date(2026, 10, 23), "buy", 100, Decimal("16.290")),
        ]
        final, snaps = replay_chain(base, specs)
        assert final.shares == 1000
        # 均价不量化到 3 位再回乘 —— 否则总成本会漂 0.02/次
        assert final.total_cost == Decimal("16958.5200")
        assert (final.total_cost / final.shares).quantize(Decimal("0.001")) == Decimal("16.959")
        assert final.realized_pnl == Decimal("-61.2800")
        assert [s.shares for _, s in snaps] == [1000, 900, 1000]

    def test_sell_over_shares_raises(self):
        from app.modules.portfolio.service import (
            ChainState,
            PositionChainError,
            apply_transaction,
        )

        with pytest.raises(PositionChainError):
            apply_transaction(ChainState(100, Decimal("1000"), Decimal("0")), "sell", 200, Decimal("11"))

    def test_sell_with_zero_shares_raises(self):
        from app.modules.portfolio.service import (
            ChainState,
            PositionChainError,
            apply_transaction,
        )

        with pytest.raises(PositionChainError):
            apply_transaction(ChainState(0, Decimal("0"), Decimal("0")), "sell", 100, Decimal("11"))


# ============================================================
# 快照
# ============================================================

class TestTransactionSnapshots:
    def test_each_transaction_records_after_snapshot(self, client):
        _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        _tx(client, "000001", "sell", 400, "12.000", "2026-07-26")

        txs = _txs(client, "000001.SZ")
        assert txs[0]["shares_after"] == 1000
        assert txs[0]["total_cost_after"] == "10500.00"
        assert txs[0]["realized_after"] == "0.00"
        # 卖 400 @ 12 → 已实现 (12 - 10.5) * 400 = 600,剩余 600 股
        assert txs[1]["shares_after"] == 600
        assert txs[1]["total_cost_after"] == "6300.00"
        assert txs[1]["realized_after"] == "600.00"

    def test_snapshot_chain_ends_at_position(self, client):
        _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        _tx(client, "000001", "buy", 500, "12.000", "2026-07-26")
        txs = _txs(client, "000001.SZ")
        p = _pos(client, "000001.SZ")
        assert txs[-1]["shares_after"] == p["shares"]
        assert txs[-1]["total_cost_after"] == p["total_cost"]


# ============================================================
# 精确回滚
# ============================================================

class TestRollback:
    def test_modify_transaction_replays_chain(self, client):
        _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        sell = _tx(client, "000001", "sell", 400, "12.000", "2026-07-26")

        # 改卖价 12 → 13:已实现 = (13 - 10.5) * 400 = 1000
        r = client.patch(f"/api/transactions/{sell['id']}", json={"price": "13.000"})
        assert r.status_code == 200, r.text

        p = _pos(client, "000001.SZ")
        assert p["shares"] == 600
        assert p["avg_cost"] == "10.500"
        assert p["realized_pnl"] == "1000.00"
        assert _txs(client, "000001.SZ")[1]["realized_after"] == "1000.00"

    def test_modify_earlier_transaction_rewrites_later_snapshots(self, client):
        buy = _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        _tx(client, "000001", "sell", 400, "12.000", "2026-07-26")

        # 改买价 10.5 → 12:成本 = 12000,已实现 = (12 - 12) * 400 = 0
        r = client.patch(f"/api/transactions/{buy['id']}", json={"price": "12.000"})
        assert r.status_code == 200, r.text

        txs = _txs(client, "000001.SZ")
        assert txs[0]["total_cost_after"] == "12000.00"
        assert txs[1]["shares_after"] == 600
        assert txs[1]["total_cost_after"] == "7200.00"
        assert txs[1]["realized_after"] == "0.00"
        p = _pos(client, "000001.SZ")
        assert p["total_cost"] == "7200.00"
        assert p["realized_pnl"] == "0.00"

    def test_delete_transaction_replays_chain(self, client):
        _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        sell = _tx(client, "000001", "sell", 400, "12.000", "2026-07-26")

        r = client.delete(f"/api/transactions/{sell['id']}")
        assert r.status_code == 204, r.text

        p = _pos(client, "000001.SZ")
        assert p["shares"] == 1000
        assert p["total_cost"] == "10500.00"
        assert p["realized_pnl"] == "0.00"

    def test_delete_buy_that_later_sell_depends_on_rejected(self, client):
        """删掉买入 → 后续卖出失去成本基准 → 422(不是 500)"""
        buy = _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        _tx(client, "000001", "sell", 400, "12.000", "2026-07-26")

        r = client.delete(f"/api/transactions/{buy['id']}")
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "CHAIN_INVALID"
        # 持仓不受影响
        p = _pos(client, "000001.SZ")
        assert p["shares"] == 600
        assert p["realized_pnl"] == "600.00"


# ============================================================
# 基准吸收历史流水(双算 bug 的根治点)
# ============================================================

class TestBaselineAbsorbsHistory:
    def test_upsert_absorbs_existing_transactions(self, client):
        _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        _baseline(client, "000001", 1000, "10.500")
        # 基准重置后,旧流水不再参与重放 → 持仓不翻倍
        p = _pos(client, "000001.SZ")
        assert p["shares"] == 1000
        assert p["total_cost"] == "10500.00"
        # 被吸收的流水快照清空
        assert _txs(client, "000001.SZ")[0]["shares_after"] is None

    def test_huatian_keeps_real_cost_after_reimport(self, client):
        """华天科技 002185 真实场景(双算 bug 回归)

        10-21 覆盖导入 800 @ 17.371(已含 8-07 那 4 笔历史)→
        10-22 买 200 @ 15.680 / 10-23 卖 100 @ 16.420 / 10-23 买 100 @ 16.290

        旧模型:导入快照已含历史效果,历史流水又重放 → 卖出时少冲成本 1058.72 元
        新模型:基准吸收历史,链尾只重放这 3 笔 → 均价 16.959
        """
        _baseline(
            client, "002185", 800, "17.371",
            name="华天科技", realized_pnl="-198.63",
        )
        _tx(client, "002185", "buy", 200, "15.680", "2026-10-22")
        _tx(client, "002185", "sell", 100, "16.420", "2026-10-23")
        _tx(client, "002185", "buy", 100, "16.290", "2026-10-23")

        p = _pos(client, "002185.SZ")
        assert p["shares"] == 1000
        assert p["avg_cost"] == "16.959"
        assert p["total_cost"] == "16958.52"
        # 基准 -198.63 + 本段卖出 -61.28
        assert p["realized_pnl"] == "-259.91"

    def test_import_does_not_double_count(self, client):
        """连续两次导入同一基准 → 持仓不变(不会翻倍)"""
        _baseline(client, "000001", 1000, "10.500")
        _baseline(client, "000001", 1000, "10.500")
        p = _pos(client, "000001.SZ")
        assert p["shares"] == 1000
        assert p["total_cost"] == "10500.00"

    def test_new_flow_after_baseline_chains_on_base(self, client):
        _baseline(client, "000001", 1000, "10.500")
        _tx(client, "000001", "buy", 500, "12.000", "2026-08-01")
        p = _pos(client, "000001.SZ")
        assert p["shares"] == 1500
        assert p["total_cost"] == "16500.00"
        assert p["avg_cost"] == "11.000"


# ============================================================
# 已吸收流水的保护
# ============================================================

class TestAbsorbedTransactionGuard:
    def test_update_absorbed_tx_rejected(self, client):
        tx = _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        _baseline(client, "000001", 1000, "10.500")

        r = client.patch(f"/api/transactions/{tx['id']}", json={"price": "11.000"})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "TX_ABSORBED"
        # 持仓不受影响
        assert _pos(client, "000001.SZ")["avg_cost"] == "10.500"

    def test_delete_absorbed_tx_rejected(self, client):
        tx = _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        _baseline(client, "000001", 1000, "10.500")

        r = client.delete(f"/api/transactions/{tx['id']}")
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "TX_ABSORBED"
        assert len(_txs(client, "000001.SZ")) == 1

    def test_chain_tx_is_editable(self, client):
        _baseline(client, "000001", 1000, "10.500")
        tx = _tx(client, "000001", "buy", 500, "12.000", "2026-08-01")
        r = client.patch(f"/api/transactions/{tx['id']}", json={"price": "13.000"})
        assert r.status_code == 200, r.text
        assert _pos(client, "000001.SZ")["total_cost"] == "17000.00"


# ============================================================
# 卖出额度
# ============================================================

class TestSellCapacity:
    def test_sell_over_quota_rejected(self, client):
        _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        r = client.post(
            "/api/transactions",
            json={
                "stock_code": "000001", "action": "sell", "shares": 1200,
                "price": "12.000", "trade_date": "2026-07-26",
            },
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "INSUFFICIENT_SHARES"

    def test_backdated_sell_breaking_later_sell_rejected(self, client):
        """补录更早日期的卖出:额度按那一天算,但链整体仍须自洽

        基准 1000 股 → 08-01 卖 900(剩 100)→ 补录 07-20 卖 500:
        07-20 当天有 1000 股(额度过得去),但重放后 08-01 只剩 500 股 → 卖 900 越界 → 422
        """
        _baseline(client, "000001", 1000, "10.500")
        _tx(client, "000001", "sell", 900, "12.000", "2026-08-01")

        r = client.post(
            "/api/transactions",
            json={
                "stock_code": "000001", "action": "sell", "shares": 500,
                "price": "12.000", "trade_date": "2026-07-20",
            },
        )
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "CHAIN_INVALID"
        # 原持仓不受影响
        p = _pos(client, "000001.SZ")
        assert p["shares"] == 100
        assert p["realized_pnl"] == "1350.00"  # (12 - 10.5) * 900

    def test_backdated_sell_within_quota_allowed(self, client):
        _baseline(client, "000001", 1000, "10.500")
        # 补录 07-20 卖 300(基准 1000 股,那天有 1000 股)→ 放行
        r = client.post(
            "/api/transactions",
            json={
                "stock_code": "000001", "action": "sell", "shares": 300,
                "price": "12.000", "trade_date": "2026-07-20",
            },
        )
        assert r.status_code == 201, r.text
        p = _pos(client, "000001.SZ")
        assert p["shares"] == 700
        assert p["realized_pnl"] == "450.00"  # (12 - 10.5) * 300


class TestBaseDateAnchor:
    """基准日期:只吸收该日期之前的流水,之后的留在链里继续生效"""

    def test_base_date_keeps_later_flows_alive(self, client):
        # 08-01 基准 600@18.298(券商快照),08-07 记 4 笔,10-22/10-23 再记 3 笔
        client.post(
            "/api/positions",
            json={
                "stock_code": "002185", "stock_name": "华天科技",
                "shares": 600, "cost_price": "18.298",
                "realized_pnl": "0.00", "base_date": "2026-08-01",
            },
        )
        _tx(client, "002185", "sell", 100, "17.530", "2026-08-07")
        _tx(client, "002185", "buy", 100, "17.400", "2026-08-07")
        _tx(client, "002185", "sell", 100, "16.930", "2026-08-07")
        _tx(client, "002185", "buy", 200, "17.050", "2026-08-07")

        # 10-21 覆盖导入 → 锚在 10-21:吸收 08-07 那 4 笔
        client.post(
            "/api/positions",
            json={
                "stock_code": "002185", "stock_name": "华天科技",
                "shares": 800, "cost_price": "17.371",
                "realized_pnl": "-198.63", "base_date": "2026-10-21",
            },
        )
        # 10-22 / 10-23 三笔在基准之后 → 仍是活链
        _tx(client, "002185", "buy", 200, "15.680", "2026-10-22")
        _tx(client, "002185", "sell", 100, "16.420", "2026-10-23")
        _tx(client, "002185", "buy", 100, "16.290", "2026-10-23")

        p = _pos(client, "002185.SZ")
        assert p["shares"] == 1000
        assert p["avg_cost"] == "16.959"
        # 精确总成本 16958.52(不是 3 位均价反推的 16959.00)
        assert p["total_cost"] == "16958.52"
        assert p["realized_pnl"] == "-259.91"

    def test_base_date_keeps_flows_editable(self, client):
        client.post(
            "/api/positions",
            json={
                "stock_code": "002185", "shares": 800, "cost_price": "17.371",
                "realized_pnl": "-198.63", "base_date": "2026-10-21",
            },
        )
        buy = _tx(client, "002185", "buy", 200, "15.680", "2026-10-22")

        # 基准之后的流水仍可改(不被吸收)
        r = client.patch(f"/api/transactions/{buy['id']}", json={"price": "16.000"})
        assert r.status_code == 200, r.text
        p = _pos(client, "002185.SZ")
        assert p["total_cost"] == "17096.80"  # 13896.80 + 200*16.000

    def test_base_date_writes_snapshots_for_live_chain(self, client):
        client.post(
            "/api/positions",
            json={
                "stock_code": "002185", "shares": 800, "cost_price": "17.371",
                "realized_pnl": "-198.63", "base_date": "2026-10-21",
            },
        )
        _tx(client, "002185", "buy", 200, "15.680", "2026-10-22")
        _tx(client, "002185", "sell", 100, "16.420", "2026-10-23")

        txs = _txs(client, "002185.SZ")
        assert txs[0]["shares_after"] == 1000
        assert txs[0]["total_cost_after"] == "17032.80"
        assert txs[1]["shares_after"] == 900
        assert txs[1]["total_cost_after"] == "15329.52"
        assert txs[1]["realized_after"] == "-259.91"

    def test_without_base_date_absorbs_everything(self, client):
        _tx(client, "002185", "buy", 200, "15.680", "2026-10-22")
        # 不给基准日期 → 吸收全部现有流水 → 链为空 → 流水不可改
        client.post(
            "/api/positions",
            json={
                "stock_code": "002185", "shares": 1000, "cost_price": "16.959",
                "realized_pnl": "-259.91",
            },
        )
        txs = _txs(client, "002185.SZ")
        assert txs[0]["shares_after"] is None
        r = client.patch(f"/api/transactions/{txs[0]['id']}", json={"price": "16.000"})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "TX_ABSORBED"


# ============================================================
# 已实现盈亏
# ============================================================

class TestRealizedPnl:
    def test_negative_realized_pnl_accepted(self, client):
        r = _baseline(
            client, "002185", 1000, "16.959",
            name="华天科技", realized_pnl="-259.91",
        )
        assert r["realized_pnl"] == "-259.91"
        assert _pos(client, "002185.SZ")["realized_pnl"] == "-259.91"

    def test_realized_pnl_omitted_keeps_current(self, client):
        _tx(client, "000001", "buy", 1000, "10.500", "2026-07-25")
        _tx(client, "000001", "sell", 400, "12.000", "2026-07-26")
        before = _pos(client, "000001.SZ")["realized_pnl"]
        assert before == "600.00"
        # 不传 realized_pnl → 沿用当前累计
        _baseline(client, "000001", 600, "10.500")
        assert _pos(client, "000001.SZ")["realized_pnl"] == "600.00"

    def test_clear_keeps_realized_pnl(self, client):
        _baseline(client, "600519", 100, "1450.000", realized_pnl="-120.00")
        r = client.post(
            "/api/positions/600519/clear", json={"price": "1500.000"},
        )
        assert r.status_code == 201, r.text
        # 已实现 = -120 + (1500 - 1450) * 100 = 4880 → 持仓归零
        assert _pos(client, "600519.SH") is None
        from app.modules.portfolio.service import get_position

        p = asyncio.run(get_position("600519.SH", include_closed=True))
        assert p is not None
        assert p.shares == 0
        assert p.realized_pnl == Decimal("4880.00")


# ============================================================
# 诊断口径(交易前持仓走链重放)
# ============================================================

class TestPositionBeforeTrade:
    def test_position_before_trade_uses_baseline(self):
        from app.db import async_session
        from app.models.orm import Position as PositionRow, Transaction as TxRow

        async def _seed():
            async with async_session() as session:
                session.add(
                    PositionRow(
                        account_id=1, stock_code="600519.SH", stock_name="贵州茅台",
                        shares=1000, total_cost="10000.00", realized_pnl="0.00",
                        base_shares=1000, base_total_cost="10000.00",
                        base_realized_pnl="0.00", base_tx_id=0,
                    )
                )
                await session.commit()

        asyncio.run(_seed())

        from app.modules.portfolio.service import recalc_position

        async def _flow():
            from app.modules.portfolio.repository import transaction_repo

            tx = await transaction_repo.create(
                stock_code="600519.SH", stock_name="贵州茅台", action="buy",
                shares=500, price="12.000", trade_date=date(2026, 8, 1),
            )
            await recalc_position("600519.SH")
            return tx.id

        tx_id = asyncio.run(_flow())

        from app.modules.portfolio.service import position_before_trade

        p = asyncio.run(position_before_trade("600519.SH", tx_id))
        assert p is not None
        # 交易前 = 基准 1000 股(不是从 0 聚合)
        assert p.shares == 1000
        assert p.total_cost == Decimal("10000.00")
