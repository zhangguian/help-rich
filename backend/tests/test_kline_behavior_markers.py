"""K 线端点追加 `behavior_markers` 的测试

钉死计划里的核心行为:
- **既有字段完全不变**(追加字段,不破坏契约)
- **资金流不可用 → 仍 200**,`behavior_markers=[]` + `behavior_markers_unavailable=true`
- **不编数字**:缺数据不产出标注
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import behavior_fund_flow_service as flow_svc
from app.services import kline_service


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _dates(n: int, start: date = date(2026, 1, 1)) -> list[str]:
    out: list[str] = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _klines(n: int = 130) -> list[dict]:
    dates = _dates(n)
    return [
        {
            "date": d,
            "open": "10.0",
            "high": "10.1",
            "low": "9.9",
            "close": "10.0",
            "volume": 100000,
        }
        for d in dates
    ]


@pytest.fixture()
def stub_klines(monkeypatch):
    """把 K 线取数换成固定 130 根(测试不依赖外网)。"""

    async def fake_fetch(stock_code: str, period: str, count: int):
        return _klines(130)

    monkeypatch.setattr(kline_service, "fetch_klines", fake_fetch)
    monkeypatch.setattr("app.api.kline.fetch_klines", fake_fetch)


@pytest.fixture()
def stub_flows(monkeypatch):
    """把资金流取数换成固定数据。"""

    async def fake_fetch_flow(stock_code: str, count: int = 120, **kwargs):
        return [
            {
                "date": d,
                "net_amount": 1.0e8,
                "r0_net": 0.8e8,
                "r0x_ratio": 70.0,
                "r0_ratio": 50.0,
                "turnover": 20.0,
                "change_ratio": 0.02,
            }
            for d in _dates(130)
        ]

    monkeypatch.setattr(flow_svc, "fetch_flow_daily", fake_fetch_flow)
    monkeypatch.setattr("app.api.kline.fetch_flow_daily", fake_fetch_flow)


class TestBehaviorMarkersInKlineApi:
    def test_existing_fields_unchanged(self, client, stub_klines, stub_flows):
        """既有字段(indicators/items/count)完全不变,只做追加。"""
        resp = client.get("/api/kline/600519.SH/indicators?period=daily&limit=130")
        assert resp.status_code == 200
        data = resp.json()
        # 既有字段
        assert "stock_code" in data
        assert "period" in data
        assert "count" in data
        assert "items" in data
        assert "indicators" in data
        assert data["indicators"].get("ma") is not None
        assert data["indicators"].get("signal_series") is not None
        # 新增字段
        assert "behavior_markers" in data
        assert "behavior_markers_unavailable" in data
        assert isinstance(data["behavior_markers"], list)
        assert data["behavior_markers_unavailable"] is False

    def test_unavailable_degrades_gracefully(self, client, stub_klines, monkeypatch):
        """资金流不可用 → 仍 200,标注为空,unavailable=true。"""

        async def boom(stock_code: str, count: int = 120, **kwargs):
            raise flow_svc.FundFlowUnavailable("模拟资金流不可用")

        monkeypatch.setattr("app.api.kline.fetch_flow_daily", boom)

        resp = client.get("/api/kline/600519.SH/indicators?period=daily&limit=130")
        assert resp.status_code == 200
        data = resp.json()
        assert data["behavior_markers"] == []
        assert data["behavior_markers_unavailable"] is True
        # 既有指标完全不受影响
        assert data["indicators"].get("ma") is not None
        assert data["count"] == 130

    def test_markers_shape(self, client, stub_klines, stub_flows):
        """标注点结构:kind/date/date_index/text/position/color/reason/metrics。"""
        resp = client.get("/api/kline/600519.SH/indicators?period=daily&limit=130")
        assert resp.status_code == 200
        markers = resp.json()["behavior_markers"]
        for m in markers:
            assert set(m.keys()) >= {
                "kind", "date", "date_index", "text", "position", "color", "reason",
            }
            assert m["kind"] in {
                "main_force_move", "dip_buy", "lock_position", "distribute",
            }
            assert m["position"] in {"aboveBar", "belowBar"}
            assert m["reason"]  # 必须带依据

    def test_non_daily_period_no_markers(self, client, stub_klines, stub_flows):
        """非日线周期 → 不产出标注(口径不同,不误导)。"""
        resp = client.get("/api/kline/600519.SH/indicators?period=weekly&limit=130")
        assert resp.status_code == 200
        assert resp.json()["behavior_markers"] == []

    def test_insufficient_klines_degrades(self, client, monkeypatch):
        """K 线不足 120 根 → 不产出标注,但端点仍 200。"""

        async def fake_fetch(stock_code: str, period: str, count: int):
            return _klines(60)

        monkeypatch.setattr("app.api.kline.fetch_klines", fake_fetch)

        resp = client.get("/api/kline/600519.SH/indicators?period=daily&limit=130")
        assert resp.status_code == 200
        assert resp.json()["behavior_markers"] == []


class TestLookbackWindow:
    """K 线路径的回看窗口必须与找股路径一致(闸 2 完备闸)。

    实测:旧版 K 线只回看 60 日历天,找股页用 120 根 K 线(≈168 日历天)
    → 61% 的信号「找股页有、K 线上找不到」。

    ⚠️ **基准日取不到时必须返回空标注**(本组测试的核心):
    旧实现是「`last` 解析失败 → **不过滤,全量返回**」——
    基准日都算不出来还把全部历史标注倒给前端,等于窗口闸门形同虚设。
    新实现统一走 `filter_markers_by_window`,基准日取不到 → 不产出标注。
    """

    @staticmethod
    def _days(n: int) -> list[str]:
        import datetime as _dt

        out: list[str] = []
        d = _dt.date(2026, 1, 1)
        while len(out) < n:
            if d.weekday() < 5:
                out.append(d.isoformat())
            d += _dt.timedelta(days=1)
        return out

    class _M:
        """最小的标注替身(只需 date 与 to_dict)。"""

        def __init__(self, date_: str):
            self.date = date_
            self.kind = "main_force_move"
            self.date_index = 0
            self.text = "⚡ 主力异动"
            self.position = "aboveBar"
            self.color = "#f59e0b"
            self.reason = "依据"

        def to_dict(self):
            return {
                "kind": self.kind, "date": self.date,
                "date_index": self.date_index, "text": self.text,
                "position": self.position, "color": self.color,
                "reason": self.reason, "metrics": {},
            }

    async def test_markers_outside_120_days_are_filtered(self, monkeypatch):
        """距基准日远超 120 日历天的标记 → 剔除;基准日当天的 → 保留。"""
        from app.api import kline as kline_api

        days = self._days(200)
        base = days[-1]
        old = days[0]
        items = [
            {
                "date": dd, "open": "10.0", "high": "10.1", "low": "9.9",
                "close": "10.0", "volume": 100000,
            }
            for dd in days
        ]

        async def fake_flows(code, count=120, **k):
            return [{"date": dd, "net_amount": 1.0} for dd in days]

        class _Res:
            markers = [TestLookbackWindow._M(old), TestLookbackWindow._M(base)]
            degraded = []

        def fake_detect(ks, flows, **k):
            return _Res()

        monkeypatch.setattr("app.api.kline.fetch_flow_daily", fake_flows)
        monkeypatch.setattr("app.api.kline.detect_behavior_markers", fake_detect)

        markers, unavailable = await kline_api._build_behavior_markers(
            "600519.SH", items, "daily"
        )
        assert unavailable is False
        # 200 个工作日 ≈ 280 日历天前 → 被过滤掉
        assert all(m["date"] != old for m in markers)
        # 基准日当天保留
        assert any(m["date"] == base for m in markers)

    async def test_unparsable_base_date_yields_no_markers(self, monkeypatch):
        """⚠️ **本组测试的核心** —— 基准日取不到 → **不产出标注**。

        旧实现:基准日解析失败 → 走 `return [m.to_dict() for m in result.markers], False`
        → **全量返回,窗口闸门形同虚设**。新实现必须返回空。
        """
        from app.api import kline as kline_api

        days = self._days(200)
        items = [
            {
                "date": dd, "open": "10.0", "high": "10.1", "low": "9.9",
                "close": "10.0", "volume": 100000,
            }
            for dd in days
        ]
        # 末根日期不可解析 → 基准日取不到
        items[-1] = {**items[-1], "date": "不是日期"}

        async def fake_flows(code, count=120, **k):
            return [{"date": dd, "net_amount": 1.0} for dd in days]

        class _Res:
            markers = [TestLookbackWindow._M(days[0]), TestLookbackWindow._M(days[-1])]
            degraded = []

        def fake_detect(ks, flows, **k):
            return _Res()

        monkeypatch.setattr("app.api.kline.fetch_flow_daily", fake_flows)
        monkeypatch.setattr("app.api.kline.detect_behavior_markers", fake_detect)

        markers, unavailable = await kline_api._build_behavior_markers(
            "600519.SH", items, "daily"
        )
        assert unavailable is False
        assert markers == [], "基准日取不到时不得回传任何标注"
