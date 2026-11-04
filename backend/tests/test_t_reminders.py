"""补T待接回清单(GET /api/t-reminders/pending)

口径:
- 每只标的取「最近一个有流水的交易日」,当天 FIFO 抵消后剩下的净卖出 = 待接回股数
- 当天卖出后又买回(做T完成)→ 净卖出归零 → 这一条自动消失
- 不亏本接回线 = 当天净卖出的加权均价
- 更早日期的净卖出不挂着(卖出后没接回可能是减仓,不是做T)
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import async_session
from app.models.orm import Position as PositionRow
from app.modules.portfolio.repository import transaction_repo


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_quote(monkeypatch):
    """行情不可用 → 现价留 null(不编数字)。"""
    import app.services.quote_service as qs

    class _Boom:
        async def get_quotes(self, codes):
            raise RuntimeError("行情源不可用")

    monkeypatch.setattr(qs, "get_quote_service", lambda: _Boom())


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


def _seed_position(code: str, shares: int, total_cost: str):
    """建持仓行(卖出后的剩余持仓)"""

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


class TestPendingList:
    def test_empty_db(self, client):
        r = client.get("/api/t-reminders/pending")
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 0
        assert r.json()["items"] == []

    def test_net_sell_shows_up(self, client):
        """当天只有卖出 → 待接回股数 = 卖出股数,不亏本线 = 卖出价"""
        _seed([("600519.SH", "sell", 200, "10.500", date(2026, 11, 2))])
        r = client.get("/api/t-reminders/pending")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1
        it = items[0]
        assert it["stock_code"] == "600519.SH"
        assert it["shares"] == 200
        assert it["price"] == pytest.approx(10.5)
        assert it["open_date"] == "2026-11-02"
        assert it["stock_name"] == "测试股"
        assert it["direction"] == "reverse"

    def test_done_t_disappears(self, client):
        """当天卖出后又买回(做T完成)→ 净卖出归零 → 不出现在清单"""
        _seed(
            [
                ("600519.SH", "sell", 100, "36.750", date(2026, 11, 2)),
                ("600519.SH", "buy", 100, "36.700", date(2026, 11, 2)),
            ]
        )
        r = client.get("/api/t-reminders/pending")
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 0

    def test_partial_buyback_keeps_remainder(self, client):
        """卖 200 只、只买回 100 只 → 还差 100 只接回,线 = 加权均价"""
        _seed(
            [
                ("600519.SH", "sell", 200, "10.000", date(2026, 11, 2)),
                ("600519.SH", "buy", 100, "9.500", date(2026, 11, 2)),
            ]
        )
        r = client.get("/api/t-reminders/pending")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["shares"] == 100
        assert items[0]["price"] == pytest.approx(10.0)

    def test_only_latest_trading_day_counts(self, client):
        """跨天接回也算做完一次T → 不再挂着

        v0.12 起清单口径是「全链未闭合」:卖出腿和接回腿可以跨天(今天卖、明天接回
        是标准做T节奏),只要接回了就算做完,清单里不再出现。
        """
        _seed(
            [
                ("600519.SH", "sell", 100, "10.000", date(2026, 10, 20)),
                ("600519.SH", "buy", 100, "9.000", date(2026, 11, 2)),
            ]
        )
        r = client.get("/api/t-reminders/pending")
        assert r.json()["count"] == 0

    def test_partial_buyback_across_days_stays_on_list(self, client):
        """卖 200 只、跨天只接回 100 只 → 剩 100 股继续挂在待接回清单

        v0.12:以前口径只看「最近有流水的交易日」,接回一半就把剩下那半丢掉了,
        用户根本看不到还差多少。现在全链未闭合的都留着。
        """
        _seed(
            [
                ("600519.SH", "sell", 200, "10.000", date(2026, 11, 2)),
                ("600519.SH", "buy", 100, "9.500", date(2026, 11, 3)),
            ]
        )
        items = client.get("/api/t-reminders/pending").json()["items"]
        assert len(items) == 1
        assert items[0]["shares"] == 100
        assert items[0]["price"] == pytest.approx(10.0)
        assert items[0]["open_date"] == "2026-11-02"

    def test_multiple_sells_weighted_avg(self, client):
        """当天两笔卖出 → 加权均价 = 不亏本线"""
        _seed(
            [
                ("600519.SH", "sell", 100, "10.000", date(2026, 11, 2)),
                ("600519.SH", "sell", 300, "12.000", date(2026, 11, 2)),
            ]
        )
        items = client.get("/api/t-reminders/pending").json()["items"]
        assert len(items) == 1
        assert items[0]["shares"] == 400
        assert items[0]["price"] == pytest.approx((100 * 10 + 300 * 12) / 400)

    def test_multiple_codes(self, client):
        _seed(
            [
                ("600519.SH", "sell", 100, "10.000", date(2026, 11, 2)),
                ("000001.SZ", "sell", 200, "5.000", date(2026, 11, 2)),
            ]
        )
        items = client.get("/api/t-reminders/pending").json()["items"]
        assert {i["stock_code"] for i in items} == {"600519.SH", "000001.SZ"}


class TestOpenPrices:
    """**当初开腿的成交价**(反T=卖出价,正T=买入价)。

    与基准线(`price` = 加权均价 / 不亏本线)不是一回事:
    基准线是算出来的阈值,这里是那几笔开腿流水的**真成交价**。
    """

    def test_single_open_leg_keeps_its_price(self, client):
        """单笔开腿 → 当初卖出价 = 那笔的成交价"""
        _seed([("600519.SH", "sell", 200, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        assert it["open_prices"] == [pytest.approx(10.5)]

    def test_multiple_open_legs_list_every_price(self, client):
        """两笔开腿 → 两个价都列出来(基准线仍是加权均价)"""
        _seed(
            [
                ("600519.SH", "sell", 100, "10.000", date(2026, 11, 2)),
                ("600519.SH", "sell", 300, "12.000", date(2026, 11, 3)),
            ]
        )
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        assert it["open_prices"] == [pytest.approx(10.0), pytest.approx(12.0)]
        # 基准线 = 加权均价(和成交价不是一回事)
        assert it["price"] == pytest.approx((100 * 10 + 300 * 12) / 400)

    def test_forward_group_reports_buy_price(self, client):
        """正T(先买后卖)→ 当初**买入**价"""
        _seed([("600519.SH", "buy", 200, "8.800", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["forward_items"][0]
        assert it["direction"] == "forward"
        assert it["open_prices"] == [pytest.approx(8.8)]

    def test_closed_leg_not_counted(self, client):
        """已闭合的腿不算开腿 —— 只留真正还挂着的那笔"""
        _seed(
            [
                ("600519.SH", "sell", 100, "10.000", date(2026, 11, 2)),
                ("600519.SH", "sell", 200, "12.000", date(2026, 11, 3)),
                ("600519.SH", "buy", 100, "9.500", date(2026, 11, 3)),
            ]
        )
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        # 11-02 那笔被 11-03 的买回闭合 → 只剩 11-03 那笔开腿
        assert it["open_prices"] == [pytest.approx(12.0)]
        assert it["shares"] == 200

    def test_quote_unavailable_leaves_price_null(self, client):
        """行情取不到 → 现价 null,不编数字"""
        _seed([("600519.SH", "sell", 100, "10.000", date(2026, 11, 2))])
        items = client.get("/api/t-reminders/pending").json()["items"]
        assert items[0]["current_price"] is None

    def test_suggested_price_is_tier1_below_line(self, client):
        """一档建议接回价 = 不亏本线 × 0.99(挂单参考)"""
        _seed([("600519.SH", "sell", 200, "10.500", date(2026, 11, 2))])
        items = client.get("/api/t-reminders/pending").json()["items"]
        assert items[0]["price"] == pytest.approx(10.5)
        assert items[0]["suggested_price"] == pytest.approx(10.5 * 0.99, abs=1e-3)

    def test_suggested_price_rounds_to_tick(self, client):
        """建议价必须落在最小报价单位(3 位小数)上"""
        _seed(
            [
                ("600519.SH", "sell", 200, "8.860", date(2026, 11, 2)),
                ("000001.SZ", "sell", 100, "0.462", date(2026, 11, 2)),
            ]
        )
        items = {i["stock_code"]: i for i in client.get("/api/t-reminders/pending").json()["items"]}
        assert items["600519.SH"]["suggested_price"] == 8.771
        assert items["000001.SZ"]["suggested_price"] == 0.457
        assert items["000001.SZ"]["suggested_price"] < items["000001.SZ"]["price"]


class TestAlertLink:
    def test_existing_alert_is_linked(self, client):
        """已建「价格 <= 不亏本线」的到价提醒 → 作为「手工提醒」关联上"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        r = client.post(
            "/api/price-alerts",
            json={
                "stock_code": "600519.SH",
                "name": "明日补T接回100股",
                "conditions": {
                    "op": "and",
                    "conditions": [{"metric": "price", "op": "<=", "value": 10.5}],
                },
            },
        )
        assert r.status_code == 200, r.text
        items = client.get("/api/t-reminders/pending").json()["items"]
        assert items[0]["manual_alert_id"] == r.json()["id"]
        assert items[0]["manual_alert_price"] == pytest.approx(10.5)

    def test_auto_alert_is_created_when_missing(self, client):
        """没有提醒 → 自动建一条(一档价),标记为自动"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        items = client.get("/api/t-reminders/pending").json()["items"]
        assert items[0]["alert_id"] is not None
        assert items[0]["alert_auto"] is True
        assert items[0]["alert_tier"] == 1
        assert items[0]["alert_price"] == pytest.approx(10.5 * 0.99, abs=1e-6)

    def test_alert_at_suggested_price_is_linked(self, client):
        """手工提醒命中一档价 → 记在 manual_alert_id(与系统自动提醒分开,不被顶掉)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        suggested = client.get("/api/t-reminders/pending").json()["items"][0]["suggested_price"]
        r = client.post(
            "/api/price-alerts",
            json={
                "stock_code": "600519.SH",
                "name": "补T接回",
                "conditions": {
                    "op": "and",
                    "conditions": [{"metric": "price", "op": "<=", "value": suggested}],
                },
            },
        )
        assert r.status_code == 200, r.text
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        # 系统那条自动提醒(建在一档价)是主位
        assert it["alert_auto"] is True
        assert it["alert_tier"] == 1
        assert it["alert_price"] == pytest.approx(suggested, abs=1e-6)
        # 手工那条另算,不被顶掉
        assert it["manual_alert_id"] == r.json()["id"]
        assert it["manual_alert_price"] == pytest.approx(suggested, abs=1e-6)

    def test_forward_alert_at_or_above_is_linked(self, client):
        """正T组认「价格 >= X」的到价提醒(涨上去就提醒卖出)"""
        _seed([("600519.SH", "buy", 100, "10.500", date(2026, 11, 3))])
        suggested = (
            client.get("/api/t-reminders/pending").json()["forward_items"][0]["suggested_price"]
        )
        r = client.post(
            "/api/price-alerts",
            json={
                "stock_code": "600519.SH",
                "name": "正T卖出",
                "conditions": {
                    "op": "and",
                    "conditions": [{"metric": "price", "op": ">=", "value": suggested}],
                },
            },
        )
        assert r.status_code == 200, r.text
        it = client.get("/api/t-reminders/pending").json()["forward_items"][0]
        assert it["alert_auto"] is True
        assert it["alert_price"] == pytest.approx(suggested, abs=1e-6)
        assert it["manual_alert_id"] == r.json()["id"]

    def test_reverse_alert_does_not_match_forward_group(self, client):
        """反T组的 `<=` 提醒不会被正T组误认(方向要对得上)

        正T组会自己有一自动提醒(`>=`),但关联的必须是 `>=` 的那一条 ——
        不能把用户手工建的 `<=` 提醒错认成「涨到就提醒卖出」。
        """
        _seed([("600519.SH", "buy", 100, "10.500", date(2026, 11, 3))])
        r = client.post(
            "/api/price-alerts",
            json={
                "stock_code": "600519.SH",
                "name": "补T接回",
                "conditions": {
                    "op": "and",
                    "conditions": [{"metric": "price", "op": "<=", "value": 10.5}],
                },
            },
        )
        assert r.status_code == 200, r.text
        it = client.get("/api/t-reminders/pending").json()["forward_items"][0]
        assert it["alert_id"] != r.json()["id"]
        linked = next(
            a
            for a in client.get("/api/price-alerts").json()["items"]
            if a["id"] == it["alert_id"]
        )
        assert linked["conditions"]["conditions"][0]["op"] == ">="


class TestForwardGroup:
    """正T待卖出组 —— v0.12 新增(先买后卖,买进了还没卖)"""

    def test_buy_only_goes_to_forward_group(self, client):
        """只有买入 → 进「待卖出」组,不在「待接回」组"""
        _seed([("600519.SH", "buy", 100, "10.500", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        assert body["count"] == 0  # 待接回组空
        assert body["forward_count"] == 1  # 待卖出组有一条
        assert body["total_count"] == 1
        it = body["forward_items"][0]
        assert it["stock_code"] == "600519.SH"
        assert it["direction"] == "forward"
        assert it["shares"] == 100
        assert it["price"] == pytest.approx(10.5)
        assert it["open_date"] == "2026-11-03"

    def test_forward_suggested_price_is_tier1_above(self, client):
        """一档建议卖出价 = 买入均价 × 1.01(与反T的一档对称)"""
        _seed([("600519.SH", "buy", 200, "10.500", date(2026, 11, 3))])
        it = client.get("/api/t-reminders/pending").json()["forward_items"][0]
        assert it["price"] == pytest.approx(10.5)
        assert it["suggested_price"] == pytest.approx(10.5 * 1.01, abs=1e-3)
        assert it["suggested_price"] > it["price"]

    def test_forward_suggested_price_rounds_to_tick(self, client):
        """建议价必须落在最小报价单位(3 位小数)上"""
        _seed([("000001.SZ", "buy", 100, "0.442", date(2026, 11, 3))])
        it = client.get("/api/t-reminders/pending").json()["forward_items"][0]
        assert it["suggested_price"] == 0.446

    def test_buyback_closes_reverse_not_leaving_forward(self, client):
        """卖出后买回 → 闭合反T,不产生正T挂单"""
        _seed(
            [
                ("600519.SH", "sell", 100, "11.000", date(2026, 11, 2)),
                ("600519.SH", "buy", 100, "10.500", date(2026, 11, 3)),
            ]
        )
        body = client.get("/api/t-reminders/pending").json()
        assert body["count"] == 0
        assert body["forward_count"] == 0

    def test_mixed_chain_splits_two_groups(self, client):
        """真实场景:反T闭合 + 正T挂单 → 两组各一条

        11-02 卖 200 @0.462 → 11-03 买 200 @0.452(闭合反T)
                                  → 11-03 买 200 @0.442(正T开腿,待卖出)
        """
        _seed(
            [
                ("561980.SH", "sell", 200, "0.462", date(2026, 11, 2)),
                ("561980.SH", "buy", 200, "0.452", date(2026, 11, 3)),
                ("561980.SH", "buy", 200, "0.442", date(2026, 11, 3)),
            ]
        )
        body = client.get("/api/t-reminders/pending").json()
        assert body["count"] == 0  # 反T已闭合
        assert body["forward_count"] == 1
        it = body["forward_items"][0]
        assert it["stock_code"] == "561980.SH"
        assert it["shares"] == 200
        assert it["price"] == pytest.approx(0.442)

    def test_multiple_codes_in_both_groups(self, client):
        """多标的、多方向 → 两组各自聚合"""
        _seed(
            [
                ("600519.SH", "sell", 100, "10.000", date(2026, 11, 2)),
                ("000001.SZ", "buy", 200, "5.000", date(2026, 11, 3)),
            ]
        )
        body = client.get("/api/t-reminders/pending").json()
        assert {i["stock_code"] for i in body["items"]} == {"600519.SH"}
        assert {i["stock_code"] for i in body["forward_items"]} == {"000001.SZ"}
        assert body["total_count"] == 2


class TestPairWindow:
    """配对时间窗口(默认 3 天)—— v0.18

    做T是短周期动作。隔了半个月的买卖不是做T,是加仓或割肉。
    没有窗口的话,「十月的买入」会吃掉「今天的卖出」,真正的今日做T反而配错腿。
    """

    def test_same_day_t_pairs(self, client):
        """窗口内(同一天)的一买一卖 → 照常配成一次T"""
        _seed(
            [
                ("600519.SH", "buy", 100, "10.500", date(2026, 11, 3)),
                ("600519.SH", "sell", 100, "11.000", date(2026, 11, 3)),
            ]
        )
        body = client.get("/api/t-reminders/pending").json()
        assert body["total_count"] == 0  # 两腿配上了,不留挂单

    def test_next_day_pairs(self, client):
        """窗口内(次日)的一卖一买 → 照常配成一次T"""
        _seed(
            [
                ("600519.SH", "sell", 100, "11.000", date(2026, 11, 2)),
                ("600519.SH", "buy", 100, "10.500", date(2026, 11, 3)),
            ]
        )
        assert client.get("/api/t-reminders/pending").json()["total_count"] == 0

    def test_long_gap_sell_stays_pending_not_paired_to_old_buy(self, client):
        """相隔超窗口的买卖 → 不配成一次T

        10-01 买、11-02 卖:这不是做T,是加仓后调仓。
        10-01 那笔买入不能吃掉 11-02 的卖出 —— 否则真正的今日做T会散架。
        """
        _seed(
            [
                ("600519.SH", "buy", 100, "10.500", date(2026, 10, 1)),
                ("600519.SH", "sell", 100, "11.000", date(2026, 11, 2)),
            ]
        )
        body = client.get("/api/t-reminders/pending").json()
        # 10-01 的买入被冻结(不在窗口内,也不显示)
        # 11-02 的卖出在窗口内 → 作为反T待接回挂着
        assert body["count"] == 1
        assert body["forward_count"] == 0
        it = body["items"][0]
        assert it["shares"] == 100
        assert it["price"] == pytest.approx(11.0)
        assert it["open_date"] == "2026-11-02"

    def test_old_add_position_drops_out_of_list(self, client):
        """窗口外的老加仓不占清单位置

        10-20 买 100 股一直没卖(是加仓,不是正在做的T),
        11-03 又买了一笔 → 清单里只应出现 11-03 这一笔。
        """
        _seed(
            [
                ("600519.SH", "buy", 100, "10.500", date(2026, 10, 20)),
                ("600519.SH", "buy", 100, "9.500", date(2026, 11, 3)),
            ]
        )
        body = client.get("/api/t-reminders/pending").json()
        assert body["forward_count"] == 1
        it = body["forward_items"][0]
        assert it["shares"] == 100
        assert it["price"] == pytest.approx(9.5)
        assert it["open_date"] == "2026-11-03"


class TestCostAfterBuyback:
    """接回后成本(从成本线角度:这次 T 能把成本拉低多少)"""

    def test_cost_after_uses_suggested_price(self, client):
        # 当前持仓 400 股 @15.578(总成本 6231.20);今天卖出 200 股 @8.860
        _seed_position("600519.SH", shares=400, total_cost="6231.20")
        _seed([("600519.SH", "sell", 200, "8.860", date(2026, 11, 2))])

        items = client.get("/api/t-reminders/pending").json()["items"]
        assert len(items) == 1
        it = items[0]
        # 一档建议接回价 = 8.860 × 0.99 = 8.771(量化 3 位)
        assert it["suggested_price"] == pytest.approx(8.771, abs=1e-6)
        # 当前成本线 = 6231.20 / 400 = 15.578
        assert it["cost_before"] == pytest.approx(15.578, abs=1e-3)
        # 接回后成本 = (6231.20 + 8.771×200) / 600 = 13.309
        assert it["cost_after"] == pytest.approx(13.309, abs=1e-3)
        # 成本被拉低了
        assert it["cost_after"] < it["cost_before"]

    def test_cost_fields_null_without_position(self, client):
        """没有持仓行 → 当前成本线留 null(不编数字),接回后成本也留 null"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        assert it["cost_before"] is None
        assert it["cost_after"] is None
        # 三档价格照样给得出(只依赖基准线)
        assert len(it["tiers"]) == 3
        assert all(t["cost_before"] is None for t in it["tiers"])


class TestThreeTiers:
    """三档建议价(方向相反 + 每档带成本前→后)"""

    def test_three_tiers_always_present(self, client):
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        tiers = it["tiers"]
        assert len(tiers) == 3
        assert [t["tier"] for t in tiers] == [1, 2, 3]
        assert [t["label"] for t in tiers] == ["一档", "二档", "三档"]

    def test_reverse_tiers_go_down(self, client):
        """反T(待接回):三档价格往下走 —— 越等越便宜,幅度越大越难成交"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        prices = [t["price"] for t in it["tiers"]]
        assert prices == pytest.approx([10.395, 10.29, 10.185])
        assert prices[0] > prices[1] > prices[2]
        assert prices[0] < it["price"]  # 一档也低于不亏本线

    def test_forward_tiers_go_up(self, client):
        """正T(待卖出):三档价格往上走 —— 方向必须与反T相反,不能一味价高"""
        _seed([("600519.SH", "buy", 100, "10.500", date(2026, 11, 3))])
        it = client.get("/api/t-reminders/pending").json()["forward_items"][0]
        prices = [t["price"] for t in it["tiers"]]
        assert prices == pytest.approx([10.605, 10.71, 10.815])
        assert prices[0] < prices[1] < prices[2]
        assert prices[0] > it["price"]  # 一档也高于买入均价

    def test_reverse_tier_cost_after_decreases(self, client):
        """反T:接回价越低 → 摊薄成本线被拉得越低"""
        _seed_position("600519.SH", shares=400, total_cost="6231.20")
        _seed([("600519.SH", "sell", 200, "8.860", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        tiers = it["tiers"]
        assert all(t["cost_before"] == pytest.approx(15.578, abs=1e-3) for t in tiers)
        after = [t["cost_after"] for t in tiers]
        assert after == pytest.approx([13.309, 13.280, 13.250], abs=1e-3)
        assert after[0] > after[1] > after[2]

    def test_forward_tier_cost_after_decreases(self, client):
        """正T:卖价越高 → 摊薄成本线被拉得越低

        持仓 400 股 @10.000(总成本 4000.00),挂着一笔 200 股 @10.500 的正T待卖出。
        三档卖价都高于成本线 → 卖完剩下的持仓成本被拉低。
        """
        _seed_position("600519.SH", shares=400, total_cost="4000.00")
        _seed([("600519.SH", "buy", 200, "10.500", date(2026, 11, 3))])
        it = client.get("/api/t-reminders/pending").json()["forward_items"][0]
        tiers = it["tiers"]
        assert all(t["cost_before"] == pytest.approx(10.0, abs=1e-3) for t in tiers)
        after = [t["cost_after"] for t in tiers]
        assert after == pytest.approx([9.395, 9.290, 9.185], abs=1e-3)
        assert after[0] > after[1] > after[2]
        assert after[0] < 10.0  # 卖在成本线之上 → 成本被拉低

    def test_tier1_equals_suggested_price(self, client):
        """顶层 suggested_price = 一档价(兼容旧字段)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        assert it["suggested_price"] == pytest.approx(it["tiers"][0]["price"], abs=1e-9)


class TestAutoAlerts:
    """到价提醒自动建立 / 自动停用"""

    def test_auto_alert_created_for_reverse(self, client):
        """反T挂单 → 自动建 `price <= 一档价` 的提醒"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        body = client.get("/api/t-reminders/pending").json()
        it = body["items"][0]
        assert body["auto_alerts_created"] == 1
        assert it["alert_auto"] is True
        assert it["alert_tier"] == 1
        alert = next(
            a for a in client.get("/api/price-alerts").json()["items"] if a["id"] == it["alert_id"]
        )
        assert alert["name"].startswith("[做T]")
        leaf = alert["conditions"]["conditions"][0]
        assert leaf["op"] == "<="
        assert leaf["value"] == pytest.approx(10.395)

    def test_auto_alert_created_for_forward(self, client):
        """正T挂单 → 自动建 `price >= 一档价` 的提醒(方向与反T相反)"""
        _seed([("600519.SH", "buy", 100, "10.500", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        it = body["forward_items"][0]
        assert body["auto_alerts_created"] == 1
        alert = next(
            a for a in client.get("/api/price-alerts").json()["items"] if a["id"] == it["alert_id"]
        )
        leaf = alert["conditions"]["conditions"][0]
        assert leaf["op"] == ">="
        assert leaf["value"] == pytest.approx(10.605)

    def test_auto_alert_is_idempotent(self, client):
        """重复拉清单不会重复建提醒"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        client.get("/api/t-reminders/pending")
        body = client.get("/api/t-reminders/pending").json()
        assert body["auto_alerts_created"] == 0
        assert body["auto_alerts_disabled"] == 0
        # 每条挂单现在有两条系统提醒:到价提醒 `[做T]` + 预警提醒 `[做T·预警]`。
        # 这里只数到价提醒 —— 重复拉清单不应该多建出价提醒。
        alerts = client.get("/api/price-alerts").json()["items"]
        assert len([a for a in alerts if a["name"].startswith("[做T]")]) == 1

    def test_auto_alert_disabled_when_pending_closed(self, client):
        """挂单接回 → 从清单消失 → 对应的自动提醒自动停用(不是删除)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        alert_id = it["alert_id"]
        assert alert_id is not None

        _seed([("600519.SH", "buy", 100, "10.000", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        assert body["total_count"] == 0
        assert body["auto_alerts_disabled"] == 1
        alert = next(
            a for a in client.get("/api/price-alerts").json()["items"] if a["id"] == alert_id
        )
        assert alert["enabled"] is False

    def test_manual_alert_is_never_disabled(self, client):
        """用户手工建的提醒不属于系统管 —— 挂单消失也不碰它

        前提是**没被清单认领过**(价格不在任何一档上,见 `TestClaimedManualAlert`)。
        """
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        manual = client.post(
            "/api/price-alerts",
            json={
                "stock_code": "600519.SH",
                "name": "我自己的提醒",
                "conditions": {
                    "op": "and",
                    "conditions": [{"metric": "price", "op": "<=", "value": 9.0}],
                },
            },
        )
        assert manual.status_code == 200, manual.text
        manual_id = manual.json()["id"]

        _seed([("600519.SH", "buy", 100, "10.000", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        assert body["total_count"] == 0
        alert = next(
            a for a in client.get("/api/price-alerts").json()["items"] if a["id"] == manual_id
        )
        assert alert["enabled"] is True

    def test_auto_alert_follows_new_suggested_price(self, client):
        """基准线变了(又卖了一笔)→ 提醒**就地**挪到新的一档价(不新建、不停用)"""
        _seed([("600519.SH", "sell", 100, "10.000", date(2026, 11, 2))])
        first = client.get("/api/t-reminders/pending").json()["items"][0]
        assert first["alert_price"] == pytest.approx(9.9)

        _seed([("600519.SH", "sell", 100, "12.000", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        second = body["items"][0]
        # 新基准线 = (10.000 + 12.000) / 2 = 11.000 → 一档 = 10.890
        assert second["price"] == pytest.approx(11.0)
        assert second["alert_price"] == pytest.approx(10.89)
        # 同一条提醒就地改价,不产生第二条
        assert second["alert_id"] == first["alert_id"]
        assert body["auto_alerts_created"] == 0
        assert body["auto_alerts_realigned"] == 1
        # 只数到价提醒(预警提醒另算),就地改价不应该多出一条
        alerts = client.get("/api/price-alerts").json()["items"]
        assert len([a for a in alerts if a["name"].startswith("[做T]")]) == 1

    def test_auto_alert_tier_choice_is_respected(self, client):
        """用户把自动提醒改到二档 → 同步认这一档,不拉回一档"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        first = client.get("/api/t-reminders/pending").json()["items"][0]
        tiers = first["tiers"]
        tier2 = tiers[1]["price"]

        r = client.patch(
            f"/api/price-alerts/{first['alert_id']}",
            json={
                "conditions": {
                    "op": "and",
                    "conditions": [{"metric": "price", "op": "<=", "value": tier2}],
                }
            },
        )
        assert r.status_code == 200, r.text

        body = client.get("/api/t-reminders/pending").json()
        it = body["items"][0]
        assert it["alert_id"] == first["alert_id"]
        assert it["alert_tier"] == 2
        assert it["alert_price"] == pytest.approx(tier2)
        assert body["auto_alerts_realigned"] == 0
        assert body["auto_alerts_created"] == 0

    def test_auto_alert_out_of_ladder_is_realigned(self, client):
        """改成了档位之外的自定义价 → 拉回一档(提醒必须挂在阶梯上才有意义)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        first = client.get("/api/t-reminders/pending").json()["items"][0]

        r = client.patch(
            f"/api/price-alerts/{first['alert_id']}",
            json={
                "conditions": {
                    "op": "and",
                    "conditions": [{"metric": "price", "op": "<=", "value": 9.99}],
                }
            },
        )
        assert r.status_code == 200, r.text

        body = client.get("/api/t-reminders/pending").json()
        it = body["items"][0]
        assert it["alert_id"] == first["alert_id"]
        assert it["alert_tier"] == 1
        assert it["alert_price"] == pytest.approx(first["tiers"][0]["price"])
        assert body["auto_alerts_realigned"] == 1


def _manual_alert(client, code: str, op: str, price: float, name: str = "明日补T接回"):
    r = client.post(
        "/api/price-alerts",
        json={
            "stock_code": code,
            "name": name,
            "conditions": {
                "op": "and",
                "conditions": [{"metric": "price", "op": op, "value": price}],
            },
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _alert_of(client, alert_id: int) -> dict:
    return next(
        a for a in client.get("/api/price-alerts").json()["items"] if a["id"] == alert_id
    )


def _claim_scenario(client, code: str = "600519.SH") -> tuple[int, float]:
    """造出「手工提醒已被清单认领」的状态,返回 (手工提醒 id, 一档价)。

    步骤为什么这么绕:认领只在「这条挂单**还没有**自动提醒」时发生,
    所以必须先让系统建出来再删掉 —— 等于回到「用户先手动建了提醒」的状态。

    认领是**下一次拉清单**时才落库的(见 `sync_auto_alerts`),所以这里最后
    还要再拉一次并断言已认领 —— 否则测的就不是「认领过的提醒」了。

    一档价从接口取(不硬编码 0.99 之类的口径),口径变了测试也不会假过。
    """
    _seed([(code, "sell", 100, "10.500", date(2026, 11, 2))])
    first = client.get("/api/t-reminders/pending").json()["items"][0]
    tier1 = first["tiers"][0]["price"]
    # 删掉系统刚建的到价提醒 → 回到「没有自动提醒」
    assert client.delete(f"/api/price-alerts/{first['alert_id']}").status_code == 200
    manual_id = _manual_alert(client, code, "<=", tier1)

    it = client.get("/api/t-reminders/pending").json()["items"][0]
    assert it["alert_id"] == manual_id, "一档价的手工提醒应该被复用,而不是另建一条"
    assert it["alert_auto"] is False
    assert _alert_of(client, manual_id)["conditions"].get("claimed") is True, "认领标记没落库"
    return manual_id, tier1


class TestClaimedManualAlert:
    """被清单认领过的手工提醒,随挂单闭合自动停用。

    为什么要有这一组:用户手工建的「明日补T接回」会被复用成某条挂单的到价提醒。
    做T闭合后挂单从清单消失,原先只按 `[做T]` 前缀判断归属 → 这条永远不停,
    结果一笔早就结束的做T天天提醒接回(真实数据里触发过 313 次)。
    """

    def test_manual_alert_at_tier1_is_claimed(self, client):
        """同标的 + 同方向 + 一档价 → 复用手工提醒并打上认领标记"""
        manual_id, tier1 = _claim_scenario(client)
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        # 复用的是手工那条(没有另外建自动提醒)
        assert it["alert_id"] == manual_id
        assert it["alert_auto"] is False
        assert it["alert_price"] == pytest.approx(tier1)
        assert _alert_of(client, manual_id)["conditions"]["claimed"] is True

    def test_claim_is_idempotent(self, client):
        """重复拉清单不重复认领,也不停用(挂单还在)"""
        manual_id, _ = _claim_scenario(client)
        body = client.get("/api/t-reminders/pending").json()
        assert body["claimed_alerts_disabled"] == 0
        assert body["items"][0]["alert_id"] == manual_id
        alert = _alert_of(client, manual_id)
        assert alert["enabled"] is True
        assert alert["conditions"]["claimed"] is True

    def test_claimed_alert_disabled_when_pending_closed(self, client):
        """挂单接回 → 被认领的手工提醒跟着停用,并撤掉认领标记"""
        manual_id, _ = _claim_scenario(client)
        assert _alert_of(client, manual_id)["enabled"] is True

        # 买回来 → 这条做T闭合,挂单从清单消失
        _seed([("600519.SH", "buy", 100, "10.000", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        assert body["total_count"] == 0
        assert body["claimed_alerts_disabled"] == 1

        alert = _alert_of(client, manual_id)
        assert alert["enabled"] is False
        # 认领关系终结 → 标记撤掉,这条提醒彻底还给用户
        assert alert["conditions"].get("claimed") is None

    def test_unclaimed_manual_alert_is_never_touched(self, client):
        """没被认领过的手工提醒(价不在任何一档上)→ 挂单闭合也不碰"""
        manual_id = _manual_alert(client, "600519.SH", "<=", 9.0)
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        # 一档价是 10.395,手工那条挂 9.0 → 不会被认领(系统另建一条自动提醒)
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        assert it["alert_id"] != manual_id
        assert it["alert_auto"] is True
        assert _alert_of(client, manual_id)["conditions"].get("claimed") is None

        _seed([("600519.SH", "buy", 100, "10.000", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        assert body["claimed_alerts_disabled"] == 0
        assert _alert_of(client, manual_id)["enabled"] is True

    def test_claim_keeps_user_condition_tree(self, client):
        """认领只动顶层标记 —— 用户自己的多条件树必须原样保留

        手工提醒可能不只有价格(还可以带涨跌幅、量比、换手),而且可能嵌套。
        认领/撤标记都走 `_with_flag`(复制 + 改顶层键),绝不重建条件树。
        """
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        first = client.get("/api/t-reminders/pending").json()["items"][0]
        tier1 = first["tiers"][0]["price"]
        assert client.delete(f"/api/price-alerts/{first['alert_id']}").status_code == 200

        r = client.post(
            "/api/price-alerts",
            json={
                "stock_code": "600519.SH",
                "name": "补T接回(带量能条件)",
                "conditions": {
                    "op": "and",
                    "conditions": [
                        {"metric": "price", "op": "<=", "value": tier1},
                        {"metric": "change_pct", "op": "<=", "value": -2},
                    ],
                },
            },
        )
        assert r.status_code == 200, r.text
        manual_id = r.json()["id"]

        client.get("/api/t-reminders/pending")
        claimed = _alert_of(client, manual_id)["conditions"]
        assert claimed["claimed"] is True
        assert claimed["op"] == "and"
        assert claimed["conditions"] == [
            {"metric": "price", "op": "<=", "value": tier1},
            {"metric": "change_pct", "op": "<=", "value": -2},
        ], "用户的两个条件都必须原样保留"

        # 闭合 → 停用并撤标记,条件树仍然完好
        _seed([("600519.SH", "buy", 100, "10.000", date(2026, 11, 3))])
        client.get("/api/t-reminders/pending")
        released = _alert_of(client, manual_id)["conditions"]
        assert released.get("claimed") is None
        assert released["conditions"] == [
            {"metric": "price", "op": "<=", "value": tier1},
            {"metric": "change_pct", "op": "<=", "value": -2},
        ]

    def test_user_can_reenable_after_release(self, client):
        """停用后用户手动重新启用 → 不会再被系统以同一理由停掉

        这是「停用时要撤标记」的直接验证:标记留着的话这条提醒永远开不起来。
        """
        manual_id, _ = _claim_scenario(client)
        _seed([("600519.SH", "buy", 100, "10.000", date(2026, 11, 3))])
        client.get("/api/t-reminders/pending")
        assert _alert_of(client, manual_id)["enabled"] is False

        r = client.patch(f"/api/price-alerts/{manual_id}", json={"enabled": True})
        assert r.status_code == 200, r.text
        body = client.get("/api/t-reminders/pending").json()
        assert body["claimed_alerts_disabled"] == 0
        assert _alert_of(client, manual_id)["enabled"] is True

