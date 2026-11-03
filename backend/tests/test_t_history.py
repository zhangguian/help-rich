"""做T操作历史(GET /api/t-history/{stock_code})

口径:
- 做T = 先卖出、后买回;按链全序 FIFO 配对(买入从最早的卖出扣)
- 每条给两个盈亏口径:
  - t_pnl       做T差价盈亏 = (卖出价 − 买回价) × T股数
  - realized_pnl 卖出确认的已实现盈亏 = (卖出价 − T前成本价) × 股数
- 成本价取自成本链(基准 + 活链重放):
  - cost_before = 卖出那一刻的持仓加权成本
  - cost_after  = 买回之后的持仓加权成本
  基准吸收掉的早期流水没有逐笔成本快照 → 这两个字段为 null(不编数字)
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import async_session
from app.main import app
from app.models.orm import Position as PositionRow
from app.modules.portfolio.repository import transaction_repo


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _seed_base(code: str, shares: int, cost: str):
    """建基准持仓(导入那一刻的真实持仓)"""

    async def _do():
        async with async_session() as session:
            session.add(
                PositionRow(
                    account_id=1,
                    stock_code=code,
                    stock_name="测试股",
                    shares=shares,
                    total_cost=cost,
                    realized_pnl="0.00",
                    base_shares=shares,
                    base_total_cost=cost,
                    base_realized_pnl="0.00",
                    base_tx_id=0,
                )
            )
            await session.commit()

    asyncio.run(_do())


def _seed(rows):
    """rows = [(code, action, shares, price, date)]"""

    async def _do():
        out = []
        for code, action, shares, price, d in rows:
            out.append(
                await transaction_repo.create(
                    stock_code=code,
                    action=action,
                    shares=shares,
                    price=price,
                    trade_date=d,
                    stock_name="测试股",
                )
            )
        return out

    return asyncio.run(_do())


class TestTHistory:
    def test_empty(self, client):
        r = client.get("/api/t-history/600519.SH")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 0
        assert body["items"] == []

    def test_done_t_has_costs_and_both_pnls(self, client):
        """先卖后买(同日)→ 一条已接回记录,T前/T后成本与两个盈亏都有值"""
        _seed_base("600519.SH", 1000, "10000.00")  # 基准成本 10.000
        _seed(
            [
                ("600519.SH", "sell", 100, "11.000", date(2026, 11, 2)),
                ("600519.SH", "buy", 100, "10.500", date(2026, 11, 2)),
            ]
        )
        r = client.get("/api/t-history/600519.SH")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1
        it = items[0]
        assert it["status"] == "closed"
        assert it["shares"] == 100
        assert it["sell_price"] == pytest.approx(11.0)
        assert it["buy_price"] == pytest.approx(10.5)
        # T 前成本 = 卖出那一刻的持仓摊薄成本(净投入 10000 ÷ 1000 股 = 10.000)
        # T 后 = 买回后的摊薄成本:净投入 10000 − 1100(卖出) + 1050(买回) = 9950 ÷ 1000
        # 摊薄口径下卖出按成交价回收净投入 → 成本线会动(券商同口径)
        assert it["cost_before"] == pytest.approx(10.0)
        assert it["cost_after"] == pytest.approx(9.95)
        # 差价盈亏 = (11.0 − 10.5) × 100 = +50
        assert it["t_pnl"] == pytest.approx(50.0)
        # 已实现 = (11.0 − 10.0) × 100 = +100
        assert it["realized_pnl"] == pytest.approx(100.0)

    def test_pending_t_has_no_buy_leg(self, client):
        """卖出还没买回 → 待接回:有 T 前成本与已实现,没有买回价/差价/后成本"""
        _seed_base("600519.SH", 1000, "10000.00")
        _seed([("600519.SH", "sell", 200, "10.500", date(2026, 11, 2))])
        r = client.get("/api/t-history/600519.SH")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1
        it = items[0]
        assert it["status"] == "pending"
        assert it["shares"] == 200
        assert it["buy_price"] is None
        assert it["buy_date"] is None
        assert it["cost_after"] is None
        assert it["t_pnl"] is None
        assert it["cost_before"] == pytest.approx(10.0)
        # 已实现 = (10.5 − 10.0) × 200 = +100
        assert it["realized_pnl"] == pytest.approx(100.0)

    def test_cross_day_buyback_pairs(self, client):
        """当天卖、次日买回 → 仍算一次做T(不限时限)"""
        _seed_base("600519.SH", 1000, "10000.00")
        _seed(
            [
                ("600519.SH", "sell", 100, "11.000", date(2026, 11, 2)),
                ("600519.SH", "buy", 100, "10.500", date(2026, 11, 3)),
            ]
        )
        r = client.get("/api/t-history/600519.SH")
        items = r.json()["items"]
        assert len(items) == 1
        it = items[0]
        assert it["status"] == "closed"
        assert it["sell_date"] == "2026-11-02"
        assert it["buy_date"] == "2026-11-03"
        assert it["t_pnl"] == pytest.approx(50.0)

    def test_fifo_pairs_oldest_sell_first(self, client):
        """两笔卖出 + 一笔买入 → 先扣最早的卖出(其余仍是待接回)"""
        _seed_base("600519.SH", 1000, "10000.00")
        _seed(
            [
                ("600519.SH", "sell", 100, "12.000", date(2026, 10, 1)),
                ("600519.SH", "sell", 100, "11.000", date(2026, 10, 2)),
                ("600519.SH", "buy", 100, "10.500", date(2026, 10, 3)),
            ]
        )
        r = client.get("/api/t-history/600519.SH")
        items = r.json()["items"]
        assert len(items) == 2
        closed = [i for i in items if i["status"] == "closed"]
        pending = [i for i in items if i["status"] == "pending"]
        assert len(closed) == 1 and len(pending) == 1
        # 买回配的是最早那笔卖出(12.000)
        assert closed[0]["sell_price"] == pytest.approx(12.0)
        assert closed[0]["t_pnl"] == pytest.approx(150.0)
        # 剩下 11.000 那笔仍是待接回
        assert pending[0]["sell_price"] == pytest.approx(11.0)
        assert pending[0]["shares"] == 100

    def test_buy_without_prior_sell_is_pending_forward_t(self, client):
        """只有买入(还没卖)→ 正T开腿,记一条「待卖出」

        v0.12:做T记录区分正T(先买后卖)与反T(先卖后买)。
        一笔买入若后面没有卖出闭合,它就是**未闭合的正T开腿** ——
        挂着等卖,不能被悄悄丢掉(以前直接丢弃,用户看不到自己还有正T在手上)。
        """
        _seed_base("600519.SH", 1000, "10000.00")
        _seed([("600519.SH", "buy", 100, "10.500", date(2026, 11, 2))])
        r = client.get("/api/t-history/600519.SH")
        items = r.json()["items"]
        assert len(items) == 1
        it = items[0]
        assert it["direction"] == "forward"
        assert it["status"] == "pending"
        assert it["shares"] == 100
        # 正T开腿 = 买入那一笔;卖出腿还没有
        assert it["buy_tx_id"] is not None
        assert it["buy_price"] == pytest.approx(10.5)
        assert it["sell_tx_id"] is None
        assert it["sell_price"] is None
        # 还没卖 → 没有价差、没有已实现
        assert it["t_pnl"] is None
        assert it["realized_pnl"] is None
        # T 前成本 = 买入那一刻的持仓摊薄成本(净投入 10000 ÷ 1000 股 = 10.000)
        assert it["cost_before"] == pytest.approx(10.0)

    def test_newest_first(self, client):
        """多条记录 → 最近的在最前"""
        _seed_base("600519.SH", 1000, "10000.00")
        _seed(
            [
                ("600519.SH", "sell", 100, "11.000", date(2026, 10, 1)),
                ("600519.SH", "buy", 100, "10.500", date(2026, 10, 1)),
                ("600519.SH", "sell", 100, "12.000", date(2026, 10, 5)),
                ("600519.SH", "buy", 100, "11.500", date(2026, 10, 5)),
            ]
        )
        r = client.get("/api/t-history/600519.SH")
        items = r.json()["items"]
        assert len(items) == 2
        assert items[0]["sell_date"] == "2026-10-05"
        assert items[1]["sell_date"] == "2026-10-01"

    def test_losing_t_is_negative(self, client):
        """高卖低买 → 差价盈亏为负"""
        _seed_base("600519.SH", 1000, "10000.00")
        _seed(
            [
                ("600519.SH", "sell", 100, "11.000", date(2026, 11, 2)),
                ("600519.SH", "buy", 100, "11.500", date(2026, 11, 2)),
            ]
        )
        r = client.get("/api/t-history/600519.SH")
        it = r.json()["items"][0]
        assert it["t_pnl"] == pytest.approx(-50.0)


class TestForwardT:
    """正T(先买后卖) —— v0.12 新增"""

    def test_forward_t_closed(self, client):
        """先买后卖 → 一条正T记录,方向 forward,差价盈亏 =(卖价 − 买价)×股数"""
        _seed_base("600519.SH", 1000, "10000.00")
        _seed(
            [
                ("600519.SH", "buy", 100, "10.500", date(2026, 11, 2)),
                ("600519.SH", "sell", 100, "11.000", date(2026, 11, 2)),
            ]
        )
        r = client.get("/api/t-history/600519.SH")
        items = r.json()["items"]
        assert len(items) == 1
        it = items[0]
        assert it["direction"] == "forward"
        assert it["status"] == "closed"
        assert it["shares"] == 100
        assert it["buy_price"] == pytest.approx(10.5)
        assert it["sell_price"] == pytest.approx(11.0)
        # 低买高卖赚差价 =(11.0 − 10.5) × 100 = +50
        assert it["t_pnl"] == pytest.approx(50.0)
        # T 前成本 = 买入那一刻的摊薄成本 10.000
        assert it["cost_before"] == pytest.approx(10.0)
        # T 后成本 = 卖出之后:净投入 10000 + 1050(买入) − 1100(卖出) = 9950 ÷ 1000
        assert it["cost_after"] == pytest.approx(9.95)
        # 已实现 = (卖价 − 卖出那一刻的摊薄成本) × 100
        # 买入后摊薄成本 = 11050/1100 = 10.04545 → (11.0 − 10.04545) × 100 = +95.45
        # (先低吸把成本摊下来了,再卖 11.0 就是赚钱的)
        assert it["realized_pnl"] == pytest.approx(95.45, abs=1e-2)

    def test_reverse_and_forward_in_one_chain(self, client):
        """同一条链里反T与正T各一笔 → 两条记录,方向不同

        真实场景(2026-11-03 半导体设备ETF):
          11-02 卖 200 @0.462(反T开腿)
          11-03 买 200 @0.452(接回,闭合反T)
          11-03 买 200 @0.442(正T开腿,还没卖)
        """
        _seed_base("561980.SH", 500, "230.70")
        _seed(
            [
                ("561980.SH", "sell", 200, "0.462", date(2026, 11, 2)),
                ("561980.SH", "buy", 200, "0.452", date(2026, 11, 3)),
                ("561980.SH", "buy", 200, "0.442", date(2026, 11, 3)),
            ]
        )
        r = client.get("/api/t-history/561980.SH")
        items = r.json()["items"]
        assert len(items) == 2
        by_dir = {it["direction"]: it for it in items}
        # 反T:11-02 卖 0.462 ↔ 11-03 买 0.452 → 闭合
        rev = by_dir["reverse"]
        assert rev["status"] == "closed"
        assert rev["shares"] == 200
        assert rev["sell_price"] == pytest.approx(0.462)
        assert rev["buy_price"] == pytest.approx(0.452)
        assert rev["t_pnl"] == pytest.approx(2.0)  # (0.462 − 0.452) × 200
        # 正T:11-03 买 0.442 → 还没卖,挂单中
        fwd = by_dir["forward"]
        assert fwd["status"] == "pending"
        assert fwd["shares"] == 200
        assert fwd["buy_price"] == pytest.approx(0.442)
        assert fwd["sell_price"] is None
        assert fwd["t_pnl"] is None
        assert fwd["realized_pnl"] is None

    def test_partial_buyback_leaves_reverse_pending(self, client):
        """卖 200 只接回 100 只 → 反T闭合 100 + 剩 100 股待接回"""
        _seed_base("001896.SH", 600, "9346.80")
        _seed(
            [
                ("001896.SH", "sell", 200, "8.860", date(2026, 11, 2)),
                ("001896.SH", "buy", 100, "8.790", date(2026, 11, 3)),
            ]
        )
        r = client.get("/api/t-history/001896.SH")
        items = r.json()["items"]
        assert len(items) == 2
        closed = [i for i in items if i["status"] == "closed"]
        pending = [i for i in items if i["status"] == "pending"]
        assert len(closed) == 1 and len(pending) == 1
        assert closed[0]["shares"] == 100
        assert closed[0]["t_pnl"] == pytest.approx(7.0)  # (8.860 − 8.790) × 100
        # 剩下 100 股还是反T挂单(待接回),成本线沿用卖出那一刻
        assert pending[0]["direction"] == "reverse"
        assert pending[0]["shares"] == 100
        assert pending[0]["sell_price"] == pytest.approx(8.86)
        assert pending[0]["buy_price"] is None
        assert pending[0]["t_pnl"] is None
