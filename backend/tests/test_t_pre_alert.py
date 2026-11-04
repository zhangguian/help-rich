"""到价提醒的**提前预警**(到价之前先给一次「准备」信号)。

为什么要有预警:
  到价才响 = 没有操作空间 —— 价格可能直接穿过去,人还没反应过来。
  所以每条挂单再给一条**预警线**:生效到价线朝基准线方向再退 1%,
  价格进了这条线就提醒「快到了,先准备」。

口径:
- 预警线 = **生效到价线** × (1 ∓ 1%)。用户在二档,预警线就按二档算。
- 反T(往下接回)预警线**高于**到价线;正T(往上卖出)预警线**低于**到价线 —— 方向相反。
- 预警提醒是**一次性**的(条件树顶层 `once: true`):命中后自动停用,
  价格**离开**预警区后由清单同步**重新武装**。

本文件锁住这三条语义。
"""
import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.alert.engine import AlertContext
from app.modules.alert.service import price_alert_service
from app.modules.portfolio.t_pairing import DIRECTION_FORWARD, DIRECTION_REVERSE
from app.modules.portfolio.t_pricing import build_pre_alert


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def quotes(monkeypatch):
    """可控的行情:改 `quotes.price` 就改现价(None = 行情不可用)。"""
    import app.services.quote_service as qs

    box = {"price": None}

    class _Quote:
        def __init__(self, code, price):
            self.code = code
            self.current_price = price

    class _Svc:
        async def get_quotes(self, codes):
            if box["price"] is None:
                raise RuntimeError("行情源不可用")
            return [_Quote(c, box["price"]) for c in codes]

    monkeypatch.setattr(qs, "get_quote_service", lambda: _Svc())
    return box


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    """提醒推送打成桩 —— 不去真弹桌面通知(本机托盘气泡不渲染)。"""

    async def fake_notify_with_limit(*args, **kwargs):
        return [SimpleNamespace(channel="console", ok=True, detail="stub")]

    monkeypatch.setattr(
        "app.modules.alert.service.notify_service.notify_with_limit",
        fake_notify_with_limit,
    )


@pytest.fixture()
def fresh_quotes(monkeypatch):
    """调度器用的 fresh 行情(跳过 5 分钟缓存)。"""
    import app.services.quote_service as qs

    box = {"price": None}

    class _Quote:
        def __init__(self, code, price):
            self.code = code
            self.current_price = price
            self.change_pct = 0.0
            self.turnover_pct = None

    class _Svc:
        async def get_quotes_fresh(self, codes):
            if box["price"] is None:
                raise RuntimeError("行情源不可用")
            return [_Quote(c, box["price"]) for c in codes]

    monkeypatch.setattr(qs, "get_quote_service", lambda: _Svc())
    return box


def _seed(rows):
    """rows = [(code, action, shares, price, date)]"""
    from app.modules.portfolio.repository import transaction_repo

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


def _alerts(client, alert_id):
    return next(
        a for a in client.get("/api/price-alerts").json()["items"] if a["id"] == alert_id
    )


class TestPreAlertPricing:
    def test_reverse_pre_line_is_above_trigger(self):
        """反T(往下接回):预警线**高于**到价线 —— 先触发预警,再等到价"""
        pre = build_pre_alert(10.395, DIRECTION_REVERSE)
        assert pre.price == pytest.approx(10.499, abs=1e-3)
        assert pre.price > 10.395

    def test_forward_pre_line_is_below_trigger(self):
        """正T(往上卖出):预警线**低于**到价线 —— 方向与反T 相反"""
        pre = build_pre_alert(10.605, DIRECTION_FORWARD)
        assert pre.price == pytest.approx(10.499, abs=1e-3)
        assert pre.price < 10.605

    def test_pre_line_lands_on_base_line(self):
        """1% 提前幅度 → 预警线≈基准线(回到成本/不亏本线就提醒)"""
        # 基准 10.500 → 一档 10.395(反T)→ 预警 10.499 ≈ 基准
        assert build_pre_alert(10.395, DIRECTION_REVERSE).price == pytest.approx(
            10.500, abs=0.001
        )
        # 基准 10.500 → 一档 10.605(正T)→ 预警 10.499 ≈ 基准
        assert build_pre_alert(10.605, DIRECTION_FORWARD).price == pytest.approx(
            10.500, abs=0.001
        )

    def test_distance_pct_to_trigger(self):
        """还差百分之几 —— 现价 8.83、到价线 8.771 → 还差 0.67%(反T 还要跌)"""
        pre = build_pre_alert(8.771, DIRECTION_REVERSE, current_price=8.83)
        assert pre.distance_pct == pytest.approx(0.67, abs=0.01)
        assert pre.reached is False
        # 8.83 已经低于预警线 8.859 → 已经在准备区里了
        assert pre.in_pre_zone is True

    def test_in_pre_zone_and_reached(self):
        """进了预警区(该准备)/ 越过到价线(该动手)"""
        # 反T:预警线 8.859、到价线 8.771
        in_zone = build_pre_alert(8.771, DIRECTION_REVERSE, current_price=8.83)
        assert in_zone.in_pre_zone is True
        assert in_zone.reached is False
        crossed = build_pre_alert(8.771, DIRECTION_REVERSE, current_price=8.70)
        assert crossed.reached is True
        assert crossed.in_pre_zone is True

    def test_no_price_means_no_distance(self):
        """现价拿不到 → 距离留 null,不编数字"""
        pre = build_pre_alert(8.771, DIRECTION_REVERSE, current_price=None)
        assert pre.distance_pct is None
        assert pre.in_pre_zone is False


class TestPreAlertAutoCreated:
    def test_pre_alert_created_for_reverse(self, client):
        """反T挂单 → 自动建一条 `price <= 预警线` 的预警提醒"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        body = client.get("/api/t-reminders/pending").json()
        it = body["items"][0]
        assert body["pre_alerts_created"] == 1
        assert it["pre_alert_id"] is not None
        assert it["pre_alert_price"] == pytest.approx(10.499, abs=1e-3)

        alert = _alerts(client, it["pre_alert_id"])
        assert alert["name"].startswith("[做T·预警]")
        leaf = alert["conditions"]["conditions"][0]
        assert leaf["op"] == "<="
        assert leaf["value"] == pytest.approx(10.499, abs=1e-3)

    def test_pre_alert_conditions_carry_kind_and_once(self, client):
        """条件树顶层带 kind=pre_alert + once=true(一次性 + 前端可区分徽章)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        cond = _alerts(client, it["pre_alert_id"])["conditions"]
        assert cond["kind"] == "pre_alert"
        assert cond["once"] is True

    def test_pre_alert_created_for_forward(self, client):
        """正T挂单 → 预警提醒用 `>=`(方向与反T 相反)"""
        _seed([("600519.SH", "buy", 100, "10.500", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        it = body["forward_items"][0]
        assert body["pre_alerts_created"] == 1
        leaf = _alerts(client, it["pre_alert_id"])["conditions"]["conditions"][0]
        assert leaf["op"] == ">="
        assert leaf["value"] == pytest.approx(10.499, abs=1e-3)

    def test_pre_alert_and_trigger_alert_are_separate(self, client):
        """预警提醒与到价提醒是**两条**规则,各管各的"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        assert it["pre_alert_id"] != it["alert_id"]
        assert it["pre_alert_price"] > it["alert_price"]

    def test_sync_is_idempotent(self, client):
        """重复打开清单不会重复建预警提醒"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        client.get("/api/t-reminders/pending")
        body = client.get("/api/t-reminders/pending").json()
        assert body["pre_alerts_created"] == 0
        pres = [
            a
            for a in client.get("/api/price-alerts").json()["items"]
            if a["name"].startswith("[做T·预警]")
        ]
        assert len(pres) == 1

    def test_pre_alert_follows_user_tier_choice(self, client):
        """用户把到价提醒改到二档 → 预警线按二档算(始终早一步)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        # 用户把到价提醒改到二档(10.290)
        r = client.patch(
            f"/api/price-alerts/{it['alert_id']}",
            json={
                "conditions": {
                    "op": "and",
                    "conditions": [
                        {"metric": "price", "op": "<=", "value": 10.290}
                    ],
                }
            },
        )
        assert r.status_code == 200
        it2 = client.get("/api/t-reminders/pending").json()["items"][0]
        assert it2["alert_tier"] == 2
        # 预警线 = 二档 × 1.01 = 10.393
        assert it2["pre_alert_price"] == pytest.approx(10.393, abs=1e-3)


class TestPreAlertOnce:
    def test_pre_alert_is_disabled_after_firing(self, client):
        """一次性:预警命中后自动停用(不删除,保留触发历史)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]

        async def _run():
            alert = await price_alert_service.get_alert(pre_id)
            return await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_run())
        assert _alerts(client, pre_id)["enabled"] is False

    def test_trigger_alert_is_not_once(self, client):
        """到价提醒**不是**一次性的 —— 命中后仍然启用(挂单还在就该继续盯)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        alert_id = it["alert_id"]

        async def _run():
            alert = await price_alert_service.get_alert(alert_id)
            return await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_run())
        assert _alerts(client, alert_id)["enabled"] is True

    def test_rearmed_after_price_leaves_pre_zone(self, client, quotes):
        """价格**离开**预警区 → 重新武装(下次再进区还会提醒)"""
        quotes["price"] = 11.0  # 反T:高于预警线 10.499 → 在区外
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]

        async def _run():
            alert = await price_alert_service.get_alert(pre_id)
            return await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_run())
        assert _alerts(client, pre_id)["enabled"] is False

        # 价格回到区外 → 同步时重新武装
        body = client.get("/api/t-reminders/pending").json()
        assert body["pre_alerts_rearmed"] == 1
        assert _alerts(client, pre_id)["enabled"] is True

    def test_stays_disabled_while_inside_pre_zone(self, client, quotes):
        """还在预警区里 → 保持停用(已经提醒过,别反复响)"""
        quotes["price"] = 10.0  # 反T:10.0 <= 预警线 10.499 → 在区内
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]

        async def _run():
            alert = await price_alert_service.get_alert(pre_id)
            return await price_alert_service.fire(alert, AlertContext(price=10.0))

        asyncio.run(_run())
        assert _alerts(client, pre_id)["enabled"] is False

        body = client.get("/api/t-reminders/pending").json()
        assert body["pre_alerts_rearmed"] == 0
        assert _alerts(client, pre_id)["enabled"] is False
        assert body["items"][0]["pre_alert_fired"] is True


class TestPreAlertRearmByScheduler:
    """**页面关着也能收到**:重新武装必须由**后端调度器**承担。

    背景:预警是「一次性」的,命中后自动停用;原先只有**清单页同步**
    会把它重新武装 —— 页面关着就再也不武装,预警响一次就哑了。
    用户要的恰恰是「页面关着也能收到」,所以这一步必须搬进调度器。
    """

    def test_rearm_when_price_leaves_pre_zone(self, client):
        """价格离开预警区 → 重新武装(不需要打开任何页面)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]

        async def _fire():
            alert = await price_alert_service.get_alert(pre_id)
            await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_fire())
        assert _alerts(client, pre_id)["enabled"] is False

        # 反T:价格 11.0 高于预警线 10.499 → 已离开预警区
        n = asyncio.run(
            price_alert_service.rearm_pre_alerts(
                {"600519.SH": AlertContext(price=11.0)}
            )
        )
        assert n == 1
        assert _alerts(client, pre_id)["enabled"] is True

    def test_stays_disabled_while_inside_pre_zone(self, client):
        """还在预警区里 → 保持停用(已经提醒过,别反复响)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]

        async def _fire():
            alert = await price_alert_service.get_alert(pre_id)
            await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_fire())
        n = asyncio.run(
            price_alert_service.rearm_pre_alerts(
                {"600519.SH": AlertContext(price=10.0)}
            )
        )
        assert n == 0
        assert _alerts(client, pre_id)["enabled"] is False

    def test_no_price_means_no_rearm(self, client):
        """行情取不到 → 不做任何动作(不编数据、不瞎武装)"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]

        async def _fire():
            alert = await price_alert_service.get_alert(pre_id)
            await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_fire())
        n = asyncio.run(price_alert_service.rearm_pre_alerts({}))
        assert n == 0
        assert _alerts(client, pre_id)["enabled"] is False

    def test_trigger_alert_is_never_rearmed(self, client):
        """到价提醒停用(挂单消失)后**不会**被重新武装 —— 它不是预警"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        alert_id = it["alert_id"]
        r = client.patch(f"/api/price-alerts/{alert_id}", json={"enabled": False})
        assert r.status_code == 200

        n = asyncio.run(
            price_alert_service.rearm_pre_alerts(
                {"600519.SH": AlertContext(price=11.0)}
            )
        )
        assert n == 0
        assert _alerts(client, alert_id)["enabled"] is False

    def test_pre_alert_codes_lists_disabled_pre_alerts(self, client):
        """调度器要为「停用的预警」拉行情,才能判断是否离开预警区"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]
        r = client.patch(f"/api/price-alerts/{pre_id}", json={"enabled": False})
        assert r.status_code == 200

        codes = asyncio.run(price_alert_service.pre_alert_codes())
        assert "600519.SH" in codes

    def test_scheduler_rearms_without_opening_the_page(self, client, fresh_quotes):
        """端到端:调度器跑一轮就完成重新武装 —— 全程不碰清单页"""
        fresh_quotes["price"] = 11.0  # 反T:高于预警线 → 在区外
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]

        async def _fire():
            alert = await price_alert_service.get_alert(pre_id)
            await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_fire())
        assert _alerts(client, pre_id)["enabled"] is False

        from app.modules.alert.scheduler import _scan_once

        asyncio.run(_scan_once())
        assert _alerts(client, pre_id)["enabled"] is True


class TestPreAlertLifecycle:
    def test_pre_alert_disabled_when_position_closed(self, client):
        """挂单消失(接回)→ 预警提醒也跟着停用"""
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]
        assert _alerts(client, pre_id)["enabled"] is True

        # 接回 → 挂单闭合
        _seed([("600519.SH", "buy", 100, "10.400", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        assert body["count"] == 0
        assert body["pre_alerts_disabled"] == 1
        assert _alerts(client, pre_id)["enabled"] is False

    def test_distance_pct_exposed(self, client, quotes):
        """清单里能直接看到「还差百分之几」"""
        quotes["price"] = 10.000
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        # 到价线 10.395、现价 10.000 → 差 3.95%;反T 现价已跌穿到价线 → reached
        assert it["pre_alert_distance_pct"] == pytest.approx(3.95, abs=0.01)
        assert it["pre_alert_reached"] is True


class TestRetiredPreAlertIsNotRearmed:
    """**已结束的做T不得继续订阅提醒**。

    复现的 bug:录完补T(挂单闭合)→ 业务侧把预警停用 → 调度器的
    「离开预警区就重新武装」分不清「命中后停用」和「挂单没了被停用」→
    下一轮把这条预警**复活**,于是一笔已经结束的做T还在订阅到价提醒。

    修法:业务侧停用时打上 `retired: true`,调度器见到这个标记就不武装。
    对照断言:只是**命中**停用(无 retired)的预警,必须照旧能被武装回来 ——
    否则就把「页面关着也要能收到」那条给修坏了。
    """

    def test_closed_t_pre_alert_is_not_rearmed(self, client):
        """录完接回 → 预警退役 → 调度器不复活它"""
        _seed(
            [
                ("600519.SH", "sell", 100, "10.500", date(2026, 11, 2)),
                ("000001.SZ", "sell", 100, "10.500", date(2026, 11, 2)),
            ]
        )
        body = client.get("/api/t-reminders/pending").json()
        pre = {it["stock_code"]: it["pre_alert_id"] for it in body["items"]}
        assert pre["600519.SH"] and pre["000001.SZ"]  # 自检:两条挂单都建了预警

        # 600519 接回 → 挂单闭合;000001 保持挂着
        _seed([("600519.SH", "buy", 100, "10.400", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        assert body["pre_alerts_disabled"] == 1

        retired = _alerts(client, pre["600519.SH"])
        assert retired["enabled"] is False
        assert retired["conditions"].get("retired") is True

        # 000001 模拟「命中后停用」(一次性提醒被引擎自动停用,无 retired 标记)
        async def _fire():
            alert = await price_alert_service.get_alert(pre["000001.SZ"])
            await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_fire())
        assert _alerts(client, pre["000001.SZ"])["enabled"] is False
        assert _alerts(client, pre["000001.SZ"])["conditions"].get("retired") is None

        # 两只票现价都 11.0(远离预警线 10.499)→ 只有「命中停用」的那只该被武装回来
        n = asyncio.run(
            price_alert_service.rearm_pre_alerts(
                {
                    "600519.SH": AlertContext(price=11.0),
                    "000001.SZ": AlertContext(price=11.0),
                }
            )
        )
        assert n == 1
        assert _alerts(client, pre["600519.SH"])["enabled"] is False  # 已结束的做T
        assert _alerts(client, pre["000001.SZ"])["enabled"] is True  # 还挂着的做T

    def test_already_disabled_pre_alert_still_gets_retired(self, client):
        """**命中过**(已停用)的预警,挂单闭合后也必须打上退役标记

        这个缺口很容易漏:停用循环若先判 `enabled` 再处理预警,
        一条「命中停用」的预警在挂单闭合时就被跳过 → 拿不到 retired →
        调度器下一轮照样把它重新武装,已结束的做T继续订阅提醒。
        """
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        pre_id = client.get("/api/t-reminders/pending").json()["items"][0]["pre_alert_id"]

        # 先让它命中一次(一次性 → 自动停用,但挂单还在)
        async def _fire():
            alert = await price_alert_service.get_alert(pre_id)
            await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_fire())
        assert _alerts(client, pre_id)["enabled"] is False
        assert _alerts(client, pre_id)["conditions"].get("retired") is None

        # 挂单闭合 → 补T录完
        _seed([("600519.SH", "buy", 100, "10.400", date(2026, 11, 3))])
        body = client.get("/api/t-reminders/pending").json()
        assert body["pre_alerts_disabled"] == 1
        assert _alerts(client, pre_id)["conditions"].get("retired") is True

        # 再同步一次 → 幂等(不重复计数)
        assert client.get("/api/t-reminders/pending").json()["pre_alerts_disabled"] == 0

        # 调度器不得复活它
        n = asyncio.run(
            price_alert_service.rearm_pre_alerts(
                {"600519.SH": AlertContext(price=11.0)}
            )
        )
        assert n == 0
        assert _alerts(client, pre_id)["enabled"] is False

    def test_retired_flag_cleared_when_pending_comes_back(self, client):
        """同一只票又开了新挂单 → retired 标记必须被清掉,重新武装恢复正常

        防「修过头」:退役标记如果永久粘住,这只票**以后**的做T预警就再也武装不回来。
        """
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        pre_id = client.get("/api/t-reminders/pending").json()["items"][0]["pre_alert_id"]

        _seed([("600519.SH", "buy", 100, "10.400", date(2026, 11, 3))])
        client.get("/api/t-reminders/pending")
        assert _alerts(client, pre_id)["conditions"].get("retired") is True

        # 新一轮反T挂单(现价在区外:11.0 高于预警线)→ 清单同步复用并武装这条提醒
        _seed([("600519.SH", "sell", 100, "10.600", date(2026, 11, 4))])
        client.get("/api/t-reminders/pending")

        alert = _alerts(client, pre_id)
        assert alert["enabled"] is True
        assert alert["conditions"].get("retired") is None
