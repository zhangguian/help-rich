"""到价提醒 · 实时推送(SSE)与事件广播。

**为什么要有这条链路**:到价提醒原来只走「后端推系统通知」,
而 Windows 托盘气泡在部分 Win11 机器上**根本不渲染**
(实测 `ShowBalloonTip` 返回成功,屏幕上什么都没有)。
于是「用户在通知设置里开了桌面通知、也点过测试看到能弹,
但真到价了却什么都没收到」—— 除了托盘这条路本身失效,
后端也**没有任何一条不依赖系统通知的通道**能把提醒送到用户眼前。

本文件锁住这条兜底链路:
- 真的响了 → 往事件总线广播 `price_alert_fired`
- 被冷却/限流拦下 → **不广播**(用户什么都没收到,再弹一次等于骗人)
- SSE 建连时补发最近真响过的快照(断线期间漏掉的补回来)
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.modules.alert.service import (
    EVENT_PRICE_ALERT_FIRED,
    build_fired_payload,
    price_alert_service,
)
from app.services.event_bus import event_bus


def _alert_row(alert_id=7, code="001896.SZ", name="豫能控股 做T接回"):
    """规则行桩。"""
    return SimpleNamespace(
        id=alert_id,
        stock_code=code,
        name=name,
        conditions_json=json.dumps(
            {"metric": "price", "op": "<=", "value": 8.771}, ensure_ascii=False
        ),
        channels_json=None,
        cooldown_sec=1800,
        daily_limit=5,
    )


def _patch_notify(monkeypatch, *, rate_limited: bool = False):
    """把推送链路打成桩:返回各渠道结果,或模拟被限流(None)。"""

    async def fake_notify_with_limit(*args, **kwargs):
        if rate_limited:
            return None
        return [SimpleNamespace(channel="console", ok=True, detail="已写日志")]

    async def fake_record_trigger(alert_id, status, snapshot=None, results=None):
        return SimpleNamespace(id=999, triggered_at=None)

    async def fake_enabled():
        return ["console"]

    monkeypatch.setattr(
        "app.modules.alert.service.notify_service.notify_with_limit",
        fake_notify_with_limit,
    )
    monkeypatch.setattr(
        "app.modules.alert.service.price_alert_repo.record_trigger", fake_record_trigger
    )
    monkeypatch.setattr(
        "app.modules.alert.service.notify_service.enabled_channels", fake_enabled
    )


async def _collect_events(action):
    """订阅事件总线,跑一次 action,收它广播的事件。"""
    got: list[dict] = []

    async def cb(msg: dict) -> None:
        got.append(msg)

    unsub = event_bus.subscribe_callback(cb)
    try:
        await action()
        # 事件总线用 create_task 派发回调 → 让出控制权让它跑完
        for _ in range(5):
            await asyncio.sleep(0)
    finally:
        await unsub()
    return got


class TestPublishOnFire:
    def test_fired_alert_is_broadcast(self, monkeypatch):
        """真响了 → 广播 price_alert_fired,负载带标题/条件/价格/触发流水 id"""

        async def run():
            from app.modules.alert.engine import AlertContext

            await price_alert_service.fire(_alert_row(), AlertContext(price=8.83))

        _patch_notify(monkeypatch)
        got = asyncio.run(_collect_events(run))
        fired = [m for m in got if m.get("event") == EVENT_PRICE_ALERT_FIRED]
        assert len(fired) == 1
        payload = fired[0]
        assert payload["alert"]["stock_code"] == "001896.SZ"
        assert payload["alert"]["price"] == 8.83
        assert payload["alert"]["title"] == "价格提醒 · 001896.SZ"
        assert "8.771" in payload["alert"]["conditions_text"]
        assert payload["trigger_id"] == 999

    def test_rate_limited_alert_is_not_broadcast(self, monkeypatch):
        """被冷却/日限流拦下 → **不广播**(那条用户什么都没收到)"""

        async def run():
            from app.modules.alert.engine import AlertContext

            await price_alert_service.fire(_alert_row(), AlertContext(price=8.83))

        _patch_notify(monkeypatch, rate_limited=True)
        got = asyncio.run(_collect_events(run))
        assert [m for m in got if m.get("event") == EVENT_PRICE_ALERT_FIRED] == []

    def test_publish_failure_does_not_break_fire(self, monkeypatch):
        """广播炸了 → 提醒本身照样成功(返回各渠道结果)"""

        async def boom(event):
            raise RuntimeError("总线挂了")

        async def run():
            from app.modules.alert.engine import AlertContext

            return await price_alert_service.fire(_alert_row(), AlertContext(price=8.83))

        _patch_notify(monkeypatch)
        monkeypatch.setattr("app.modules.alert.service.event_bus.publish", boom)
        results = asyncio.run(run())
        assert results is not None
        assert results[0].channel == "console"


class TestPayloadShape:
    def test_payload_has_stable_fields(self):
        """实时推送与断线补发共用一个构造函数 → 字段必须一致。"""
        trig = SimpleNamespace(id=42, triggered_at=SimpleNamespace(isoformat=lambda: "T"))
        payload = build_fired_payload(
            _alert_row(),
            trig=trig,
            price=8.83,
            conditions_text="价格 <= 8.771",
            channels=[{"channel": "console", "ok": True}],
        )
        assert payload["event"] == EVENT_PRICE_ALERT_FIRED
        assert payload["trigger_id"] == 42
        assert payload["triggered_at"] == "T"
        assert payload["alert"]["id"] == 7
        assert payload["alert"]["body"].count("\n") == 2
        assert payload["channels"][0]["channel"] == "console"

    def test_price_none_is_not_faked(self):
        """价格拿不到 → null,正文里显示 '?',不能编一个数字出来"""
        payload = build_fired_payload(
            _alert_row(), trig=None, price=None, conditions_text="价格 <= 8.771"
        )
        assert payload["alert"]["price"] is None
        assert "当前价:?" in payload["alert"]["body"]
        assert payload["trigger_id"] is None


class TestSnapshot:
    def test_snapshot_uses_same_payload_builder(self, monkeypatch):
        """SSE 建连补发的快照,字段与实时推送一致(前端只写一套解析)"""
        from app.modules.alert import api as alert_api

        trig = SimpleNamespace(
            id=7,
            triggered_at=SimpleNamespace(isoformat=lambda: "2026-11-04T09:31:00"),
            snapshot_json=json.dumps({"price": 8.83}),
            status="matched",
        )
        alert = _alert_row()

        async def fake_rows(since, limit):
            return [(trig, alert)]

        monkeypatch.setattr(
            "app.modules.alert.api.price_alert_repo.list_recent_fired", fake_rows
        )
        items = asyncio.run(alert_api._snapshot_items())
        assert len(items) == 1
        assert items[0]["event"] == EVENT_PRICE_ALERT_FIRED
        assert items[0]["trigger_id"] == 7
        assert items[0]["alert"]["price"] == 8.83
        assert items[0]["alert"]["stock_code"] == "001896.SZ"

    def test_snapshot_survives_repo_failure(self, monkeypatch):
        """补发失败不能挡住 SSE 主流程"""

        async def boom(since, limit):
            raise RuntimeError("库读不到")

        monkeypatch.setattr(
            "app.modules.alert.api.price_alert_repo.list_recent_fired", boom
        )
        from app.modules.alert import api as alert_api

        assert asyncio.run(alert_api._snapshot_items()) == []


class TestTestPopup:
    """自检端点:广播的合成事件也得带**推送时间**。

    弹窗卡片上显示的就是 `triggered_at` —— 自检时看不到时间,
    就没法验证卡片长什么样(真实触发要等盘中触价,等不起)。
    """

    def test_popup_event_carries_triggered_at(self):
        from app.modules.alert import api as alert_api

        async def run():
            return await alert_api.test_popup(alert_api.PriceAlertTestPopup())

        got = asyncio.run(_collect_events(run))
        fired = [m for m in got if m.get("event") == EVENT_PRICE_ALERT_FIRED]
        assert len(fired) == 1
        assert fired[0]["triggered_at"] is not None
        # 合成事件没有真实流水 → trigger_id 保持 None,不影响前端按它去重
        assert fired[0]["trigger_id"] is None


class TestRoutes:
    def test_stream_and_recent_fired_routes_exist(self):
        """两个新端点必须真的注册上了"""
        from app.main import app

        paths = {r.path for r in app.routes}
        assert "/api/price-alerts/stream" in paths
        assert "/api/price-alerts/recent-fired" in paths

    def test_stream_route_registered_before_param_routes(self):
        """字面量路径必须注册在 `/{alert_id}` 之前,否则会被参数路由吃掉"""
        from app.main import app

        paths = [r.path for r in app.routes if r.path.startswith("/api/price-alerts")]
        assert paths.index("/api/price-alerts/stream") < paths.index(
            "/api/price-alerts/{alert_id}"
        )


@pytest.mark.parametrize("channel", ["console", "desktop"])
def test_both_channels_reach_the_broadcast(channel, monkeypatch):
    """桌面渠道修好之后,弹窗链路与渠道是否成功无关 —— 事件都会广播"""
    from app.modules.alert.engine import AlertContext

    async def fake_notify_with_limit(*args, **kwargs):
        return [SimpleNamespace(channel=channel, ok=True, detail="OK")]

    async def fake_record_trigger(alert_id, status, snapshot=None, results=None):
        return SimpleNamespace(id=1, triggered_at=None)

    async def fake_enabled():
        return [channel]

    monkeypatch.setattr(
        "app.modules.alert.service.notify_service.notify_with_limit",
        fake_notify_with_limit,
    )
    monkeypatch.setattr(
        "app.modules.alert.service.price_alert_repo.record_trigger", fake_record_trigger
    )
    monkeypatch.setattr(
        "app.modules.alert.service.notify_service.enabled_channels", fake_enabled
    )

    async def run():
        await price_alert_service.fire(_alert_row(), AlertContext(price=8.83))

    got = asyncio.run(_collect_events(run))
    fired = [m for m in got if m.get("event") == EVENT_PRICE_ALERT_FIRED]
    assert len(fired) == 1
    assert fired[0]["channels"][0]["channel"] == channel
