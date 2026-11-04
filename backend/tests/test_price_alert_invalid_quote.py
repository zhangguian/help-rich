"""**无效行情不得触发提醒**(开盘瞬间 `price=0.0` 误触发回归测试)。

事故背景(2026-11-04):
  09:15 集合竞价瞬间,行情源对部分标的返回占位值
  `price=0.0, change_pct=-100.0`。调度器把它原样喂进条件求值器,
  「价格 <= X」类提醒因 `0.0 <= X` **恒成立**而假触发 —— 09:15 误响 3 条,
  弹窗里显示「当前价 0.000」。

修法(口径:行情取不到 = null,不编数据):
  `alert/scheduler.py` 构造 `AlertContext` 前过滤无效价
  (`price <= 0` / 非数字 / NaN / ±inf)→ 该标的**本轮不评估**。
  与 `data/market_snapshot.py` 的 `price <= 0 → 跳过` 同源口径。

⚠️ 这类 bug 的特征是「**看起来能跑**」:price=0 是个合法数字,
   求值器不会报错,只会安静地给出错误答案。所以必须用测试锁死。
"""
import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.alert.scheduler import _scan_once, _to_float


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_push(monkeypatch):
    """提醒推送打成桩 —— 不去真弹桌面通知。"""

    async def fake_notify_with_limit(*args, **kwargs):
        from types import SimpleNamespace

        return [SimpleNamespace(channel="console", ok=True, detail="stub")]

    monkeypatch.setattr(
        "app.modules.alert.service.notify_service.notify_with_limit",
        fake_notify_with_limit,
    )


@pytest.fixture()
def raw_quotes(monkeypatch):
    """可控的**原始**行情:可以返回 price=0 / None / NaN 等无效值。"""
    import app.services.quote_service as qs

    box = {"price": 10.0, "change_pct": 0.0, "turnover_pct": None}

    class _Quote:
        def __init__(self, code):
            self.code = code
            self.current_price = box["price"]
            self.change_pct = box["change_pct"]
            self.turnover_pct = box["turnover_pct"]

    class _Svc:
        async def get_quotes_fresh(self, codes):
            if box["price"] is None and box["change_pct"] is None:
                raise RuntimeError("行情源不可用")
            return [_Quote(c) for c in codes]

        # 清单页(`/api/t-reminders/pending`)取现价走的是带缓存的那条路
        async def get_quotes(self, codes):
            if box["price"] is None:
                raise RuntimeError("行情源不可用")
            return [_Quote(c) for c in codes]

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


class TestToFloat:
    """无效值判定 —— 非有限值不能变成「恒成立」的假触及。"""

    def test_none_is_invalid(self):
        assert _to_float(None) is None

    def test_number_is_valid(self):
        assert _to_float(10.5) == 10.5
        assert _to_float("10.5") == 10.5
        assert _to_float(0) == 0.0

    def test_nan_and_inf_are_invalid(self):
        assert _to_float(float("nan")) is None
        assert _to_float(float("inf")) is None
        assert _to_float(float("-inf")) is None

    def test_non_numeric_is_invalid(self):
        assert _to_float("abc") is None
        assert _to_float([1]) is None


class TestInvalidQuoteDoesNotFire:
    """开盘瞬间的无效行情**不得**触发提醒。"""

    def test_zero_price_does_not_fire(self, client, raw_quotes):
        """price=0.0 → 反T 到价提醒(价格 <= 到价线)**不能**被触发

        事故当天 09:15 就是这样假响了 3 条。
        """
        raw_quotes["price"] = 0.0
        raw_quotes["change_pct"] = -100.0
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        alert_id = it["alert_id"]

        fired = asyncio.run(_scan_once())
        assert fired == 0
        # 提醒仍在启用状态(没被"响"掉),也**没有**产生触发流水
        assert _alerts(client, alert_id)["enabled"] is True
        trig = client.get(f"/api/price-alerts/{alert_id}/triggers").json()["items"]
        assert trig == []

    def test_zero_price_does_not_fire_pre_alert(self, client, raw_quotes):
        """预警提醒同样不得被 price=0 触发"""
        raw_quotes["price"] = 0.0
        raw_quotes["change_pct"] = -100.0
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]

        fired = asyncio.run(_scan_once())
        assert fired == 0
        assert _alerts(client, pre_id)["enabled"] is True

    def test_none_price_does_not_fire(self, client, raw_quotes):
        """行情返回 None → 同样不评估"""
        raw_quotes["price"] = None
        raw_quotes["change_pct"] = 0.0
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        alert_id = it["alert_id"]

        fired = asyncio.run(_scan_once())
        assert fired == 0
        assert _alerts(client, alert_id)["enabled"] is True

    def test_nan_price_does_not_fire(self, client, raw_quotes):
        """NaN 价格 → 不评估(NaN 比较恒为 False,不能靠求值器兜底)"""
        raw_quotes["price"] = float("nan")
        raw_quotes["change_pct"] = 0.0
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        alert_id = it["alert_id"]

        fired = asyncio.run(_scan_once())
        assert fired == 0
        assert _alerts(client, alert_id)["enabled"] is True

    def test_valid_price_still_fires(self, client, raw_quotes):
        """对照组:**有效**行情仍要正常触发(别把门禁修过头)"""
        raw_quotes["price"] = 9.5  # 反T:低于到价线 → 该响
        raw_quotes["change_pct"] = -3.0
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        alert_id = it["alert_id"]

        fired = asyncio.run(_scan_once())
        assert fired >= 1
        trig = client.get(f"/api/price-alerts/{alert_id}/triggers").json()["items"]
        assert len(trig) >= 1


class TestInvalidQuoteInList:
    """清单页不能被无效行情**打挂**。

    NaN / ±inf 不是合法 JSON —— 直接返回会让整个接口 500,
    用户的补T清单**整页打不开**。
    """

    def test_nan_price_does_not_break_pending_list(self, client, raw_quotes):
        raw_quotes["price"] = float("nan")
        raw_quotes["change_pct"] = 0.0
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])

        r = client.get("/api/t-reminders/pending")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 1
        # 无效行情 → 现价留 null(不编数据),而不是 0.0 或 NaN
        assert items[0]["current_price"] is None

    def test_zero_price_does_not_show_as_current_price(self, client, raw_quotes):
        """开盘瞬间的 0.0 占位值不能显示成「现价 0.000」"""
        raw_quotes["price"] = 0.0
        raw_quotes["change_pct"] = -100.0
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])

        r = client.get("/api/t-reminders/pending")
        assert r.status_code == 200
        assert r.json()["items"][0]["current_price"] is None


class TestInvalidQuoteDoesNotRearm:
    """无效行情**不得**触发预警重新武装。

    重新武装的判据是「当前价不再满足预警条件」。若行情是 0.0(无效),
    0.0 可能恰好「不满足」条件 → 会把预警**错误地**重新武装,
    下轮再来一遍。这就是「不编数据」要覆盖的第二面。
    """

    def test_zero_price_does_not_rearm(self, client, raw_quotes):
        raw_quotes["price"] = 0.0
        raw_quotes["change_pct"] = -100.0
        _seed([("600519.SH", "sell", 100, "10.500", date(2026, 11, 2))])
        it = client.get("/api/t-reminders/pending").json()["items"][0]
        pre_id = it["pre_alert_id"]

        # 先让预警响一次(命中后自动停用)
        from app.modules.alert.engine import AlertContext
        from app.modules.alert.service import price_alert_service

        async def _fire():
            alert = await price_alert_service.get_alert(pre_id)
            await price_alert_service.fire(alert, AlertContext(price=9.0))

        asyncio.run(_fire())
        assert _alerts(client, pre_id)["enabled"] is False

        # 无效行情的一轮 → **不得**把它武装回去
        asyncio.run(_scan_once())
        assert _alerts(client, pre_id)["enabled"] is False
