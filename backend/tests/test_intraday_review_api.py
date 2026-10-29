"""盘中复盘 API 测试(阶段 T2.3)

覆盖:四个端点 / 幂等覆盖(同日同档重跑不产生第二行)/ 缺作战计划时响亮失败。

**不打桩真实网络**:行情、作战计划、异动扫描、交易日历全部在边界处替换。
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.modules.analysis import intraday_review as ir

client = TestClient(app)

TODAY = date.today().isoformat()

FAKE_OUTLOOK = {
    "stance": "bearish",
    "stance_label": "偏空",
    "score": -2,
    "dims_total": 4,
    "dims_effective": 4,
    "dims": [
        {"key": "volume", "label": "量能", "score": -1, "state": "bear", "detail": "缩量"},
    ],
    "key_levels": {
        "close": 3713.03, "ma5": 3700.0, "ma10": 3690.0, "ma20": 3680.0,
        "support": [3690.0], "resistance": [3720.0],
    },
    "degraded": False,
    "degraded_reason": [],
}

FAKE_ITEMS = [
    {
        "stock_code": "600519.SH", "stock_name": "贵州茅台",
        "item_kind": "stop", "direction": "sell", "label": "明日止损",
        "trigger_price": 12.39, "trigger_condition": "跌破 12.39 元无条件减仓",
        "basis": ["跌破 12.39 元无条件减仓"],
        "invalid_if": "收盘站回 12.39 元上方则不看止损",
        "status_now": "armed", "source": "decision.stop_loss",
    },
    {
        "stock_code": "000001.SZ", "stock_name": "平安银行",
        "item_kind": "entry", "direction": "buy", "label": "明日建仓",
        "trigger_price": 10.0, "trigger_condition": "站上 10.0 元",
        "basis": ["站上 10.0 元"], "invalid_if": "跌破 9.70 则本条作废",
        "status_now": "armed", "source": "decision.actions",
    },
]


def _fake_plan(plan_date: date):
    return {
        "plan_date": plan_date.isoformat(),
        "target_date": plan_date.isoformat(),
        "outlook": FAKE_OUTLOOK,
        "review": None,
        "items": [dict(i) for i in FAKE_ITEMS],
        "meta": {},
    }


async def _fake_scope():
    return [
        {"stock_code": "600519.SH", "stock_name": "贵州茅台"},
        {"stock_code": "000001.SZ", "stock_name": "平安银行"},
    ]


class _FakeQuoteService:
    async def get_quotes(self, codes):
        # 000001.SZ 故意取不到 → 该票判「数据不足」
        out = []
        for c in codes:
            if c == "600519.SH":
                out.append(SimpleNamespace(
                    code=c, name="贵州茅台",
                    current_price=12.30, change_pct=-1.2,
                ))
        return out


class _FakeWorkflow:
    async def scan_intraday_moves(self):
        return ["🚀 600519.SH 贵州茅台 -1.2%"], ["600519.SH"]


@pytest.fixture
def _wired(monkeypatch):
    """把复盘编排层的外部依赖全部替换掉(不打桩真实网络)"""
    from app.api import intraday_review as api

    async def _get_plan(plan_date):
        return _fake_plan(plan_date)

    async def _trading_day_meta(target=None):
        return {
            "is_trading_day": True,
            "trade_date_source": "index_kline",
            "trading_day_estimated": False,
            "trade_date": TODAY,
        }

    monkeypatch.setattr(ir, "get_plan", _get_plan)
    monkeypatch.setattr(ir, "resolve_target_stocks", _fake_scope)
    monkeypatch.setattr(ir, "QuoteService", _FakeQuoteService)
    monkeypatch.setattr(ir, "workflow_agent_service", _FakeWorkflow())
    monkeypatch.setattr(api, "trading_day_meta", _trading_day_meta)


def _row_count(trade_date: str, slot: str | None = None) -> int:
    url = os.environ["DATABASE_URL"]
    path = url.split("///")[-1]
    conn = sqlite3.connect(path)
    try:
        if slot:
            cur = conn.execute(
                "SELECT COUNT(*) FROM intraday_review WHERE trade_date=? AND slot=?",
                (trade_date, slot),
            )
        else:
            cur = conn.execute(
                "SELECT COUNT(*) FROM intraday_review WHERE trade_date=?", (trade_date,)
            )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


# ---------------- 四个端点 ----------------

def test_schedule_endpoint_returns_today_state(_wired):
    r = client.get("/api/intraday-review/schedule")
    assert r.status_code == 200
    data = r.json()
    assert data["date"] == TODAY
    assert data["is_trading_day"] is True
    assert data["trade_date_source"] == "index_kline"
    assert data["trading_day_estimated"] is False
    assert data["slots"] == ["11:30", "14:00"]
    assert data["produced_slots"] == []
    assert data["next_slot"] in ("11:30", "14:00")
    assert isinstance(data["next_slot_minutes_left"], int)


def test_generate_endpoint_returns_review(_wired):
    r = client.post("/api/intraday-review/generate", json={"slot": "11:30"})
    assert r.status_code == 200
    data = r.json()
    assert data["trade_date"] == TODAY
    assert data["slot"] == "11:30"
    assert data["market_opinion"]["stance"] == "bearish"
    assert len(data["actions"]) == 2
    # 600519.SH 现价 12.30 ≤ 触发价 12.39 → 已到价待执行
    states = {a["stock_code"]: a["action_state"] for a in data["actions"]}
    assert states["600519.SH"] == "已到价待执行"
    # 000001.SZ 取不到报价 → 数据不足
    assert states["000001.SZ"] == "数据不足"
    assert data["degraded"] is True
    assert "000001.SZ" in (data["degraded_reason"] or "")
    # 异动扫描作为补充段并入(不丢既有能力)
    assert data["extra_lines"] == ["🚀 600519.SH 贵州茅台 -1.2%"]


def test_get_review_matches_generate_field_by_field(_wired):
    generated = client.post("/api/intraday-review/generate", json={"slot": "11:30"}).json()
    r = client.get("/api/intraday-review", params={"date": TODAY})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["reviews"][0] == generated


def test_get_review_by_slot_returns_single_payload(_wired):
    client.post("/api/intraday-review/generate", json={"slot": "11:30"})
    r = client.get("/api/intraday-review", params={"date": TODAY, "slot": "11:30"})
    assert r.status_code == 200
    data = r.json()
    assert data["slot"] == "11:30"
    assert data["market_opinion"]["stance"] == "bearish"


def test_dispatch_endpoint_generates_and_pushes(_wired, monkeypatch):
    from app.api import intraday_review as api

    calls = {}

    async def _fake_dispatch(payload):
        calls["payload"] = payload
        return [SimpleNamespace(channel="console", ok=True, detail="ok")]

    monkeypatch.setattr(api, "dispatch_intraday_review", _fake_dispatch)
    r = client.post("/api/intraday-review/dispatch", json={"slot": "14:00"})
    assert r.status_code == 200
    data = r.json()
    assert data["slot"] == "14:00"
    assert data["delivered"] == [{"channel": "console", "ok": True, "detail": "ok"}]
    assert calls["payload"]["slot"] == "14:00"


# ---------------- 幂等 ----------------

def test_regenerate_same_slot_does_not_create_second_row(_wired):
    first = client.post("/api/intraday-review/generate", json={"slot": "11:30"})
    assert first.status_code == 200
    assert _row_count(TODAY, "11:30") == 1

    second = client.post("/api/intraday-review/generate", json={"slot": "11:30"})
    assert second.status_code == 200
    assert _row_count(TODAY, "11:30") == 1
    assert _row_count(TODAY) == 1

    # 另一个档位是**新的一行**(不是覆盖)
    client.post("/api/intraday-review/generate", json={"slot": "14:00"})
    assert _row_count(TODAY) == 2


# ---------------- 查不到 / 失败 ----------------

def test_get_review_404_when_not_generated(_wired):
    r = client.get("/api/intraday-review", params={"date": "1999-01-01"})
    assert r.status_code == 404
    assert "尚未生成" in r.json()["detail"] or "还没有任何" in r.json()["detail"]


def test_get_review_404_for_missing_slot(_wired):
    client.post("/api/intraday-review/generate", json={"slot": "11:30"})
    r = client.get("/api/intraday-review", params={"date": TODAY, "slot": "14:00"})
    assert r.status_code == 404


def test_generate_fails_loudly_without_today_plan(monkeypatch):
    """今日作战计划缺失 → **响亮失败**,不产出半成品建议"""
    from app.api import intraday_review as api

    async def _no_plan(plan_date):
        return None

    async def _trading_day_meta(target=None):
        return {
            "is_trading_day": True,
            "trade_date_source": "index_kline",
            "trading_day_estimated": False,
            "trade_date": TODAY,
        }

    monkeypatch.setattr(ir, "get_plan", _no_plan)
    monkeypatch.setattr(api, "trading_day_meta", _trading_day_meta)

    r = client.post("/api/intraday-review/generate", json={"slot": "11:30"})
    assert r.status_code == 422
    assert "今日作战计划还没生成" in r.json()["detail"]
    # 没有产出任何行
    assert _row_count(TODAY) == 0


def test_invalid_slot_returns_422(_wired):
    r = client.post("/api/intraday-review/generate", json={"slot": "09:00"})
    assert r.status_code == 422
    assert "不支持的档位" in r.json()["detail"]


def test_invalid_date_returns_422(_wired):
    r = client.get("/api/intraday-review", params={"date": "not-a-date"})
    assert r.status_code == 422


# ---------------- missing_slots(2026-10-27) ----------------

def _frozen_datetime(target: datetime):
    """造一个 now() 被冻结的 datetime 子类(只为测「哪些档位已过时刻」)"""

    class _F(datetime):
        @classmethod
        def now(cls, tz=None):
            return target

    return _F


def test_schedule_reports_missing_slots(_wired, monkeypatch):
    """⚠️ 2026-10-27 新增:已到触发时刻、但**还没产出**的档位必须说出来。

    没有这个字段时,前端只能显示「下一次盘中复盘 11:30,还有 1287 分钟」——
    用户完全看不出今天 11:30 / 14:00 这两档**已经到点却没产出**。
    """
    from app.api import intraday_review as api

    async def _only_am(_d):
        return [{"slot": "11:30"}]

    monkeypatch.setattr(api, "get_reviews", _only_am)
    monkeypatch.setattr(api, "datetime", _frozen_datetime(datetime(2026, 10, 27, 14, 30)))

    data = client.get("/api/intraday-review/schedule").json()
    assert data["produced_slots"] == ["11:30"]
    # 11:30 已产出 → 不算缺;14:00 已到点但没产出 → 算缺
    assert data["missing_slots"] == ["14:00"]
    # 两档时刻都过了 → 下一档是明天上午
    assert data["next_slot"] == "11:30"


def test_schedule_missing_slots_empty_before_first_window(_wired, monkeypatch):
    """还没到 11:30 → 没有任何档位算缺"""
    from app.api import intraday_review as api

    async def _none(_d):
        return []

    monkeypatch.setattr(api, "get_reviews", _none)
    monkeypatch.setattr(api, "datetime", _frozen_datetime(datetime(2026, 10, 27, 9, 0)))

    data = client.get("/api/intraday-review/schedule").json()
    assert data["missing_slots"] == []
    assert data["next_slot"] == "11:30"


def test_schedule_missing_slots_never_contains_produced(_wired, monkeypatch):
    """已产出的档位绝不能出现在 missing 里"""
    from app.api import intraday_review as api

    async def _both(_d):
        return [{"slot": "11:30"}, {"slot": "14:00"}]

    monkeypatch.setattr(api, "get_reviews", _both)
    monkeypatch.setattr(api, "datetime", _frozen_datetime(datetime(2026, 10, 27, 15, 0)))

    data = client.get("/api/intraday-review/schedule").json()
    assert data["produced_slots"] == ["11:30", "14:00"]
    assert data["missing_slots"] == []
