"""作战计划 API 测试"""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_plan_404_when_not_generated():
    r = client.get("/api/battle-plan", params={"date": "1999-01-01"})
    assert r.status_code == 404
    assert "尚未生成" in r.json()["detail"]


def test_scope_endpoint_returns_object(monkeypatch):
    """`/scope` 2026-10-25 起返回对象 `{watchlist, pool, universe}`(作战计划 v2)

    ⚠️ 破坏性变更:从 `list[dict]` 改成对象。前端只有一处调用点(作战计划空态),
    已同批改完。
    """
    from app.api import battle_plan as bp

    async def _scope():
        return [{"stock_code": "001896.SZ", "stock_name": "豫能控股",
                 "in_position": True, "is_favorite": False,
                 "shares": 100, "avg_cost": 9.5}]
    monkeypatch.setattr(bp, "resolve_target_stocks", _scope)

    async def _pool():
        return [{"stock_code": "600519.SH", "stock_name": "贵州茅台",
                 "miss_streak": 0, "last_status": "touched",
                 "last_score": 72.4, "joined_on": "2026-10-20"}]
    monkeypatch.setattr(bp, "get_current_pool", _pool)

    async def _universe():
        return {"total": 5568, "main_board": 3193, "non_st": 3053,
                "after_filters": 1941, "min_amount_yi": 1.0}
    monkeypatch.setattr(bp, "get_universe_stats", _universe)

    r = client.get("/api/battle-plan/scope")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    assert set(data) == {"watchlist", "pool", "universe"}
    assert data["watchlist"][0]["stock_code"] == "001896.SZ"
    # ⚠️ 真实持仓成本(shares / avg_cost)不得扩散到出参
    assert "shares" not in data["watchlist"][0]
    assert "avg_cost" not in data["watchlist"][0]
    assert data["pool"][0]["stock_code"] == "600519.SH"
    assert data["universe"]["after_filters"] == 1941


def test_generate_endpoint_returns_plan(monkeypatch):
    from app.api import battle_plan as bp

    async def _gen(plan_date: date):
        return {
            "plan_date": plan_date.isoformat(),
            "target_date": "2026-10-22",
            "outlook": {"stance": "neutral", "stance_label": "震荡", "score": 0,
                        "dims_total": 4, "dims_effective": 4, "dims": [],
                        "key_levels": {"close": 3713.03, "ma5": None, "ma10": None,
                                       "ma20": None, "support": [], "resistance": []},
                        "disclaimer": "基于 4/4 维度规则推断，非预测；仅作明日操作参考。",
                        "degraded": False, "degraded_reason": []},
            "review": None,
            "items": [],
            "meta": {"scope_count": 1, "scope": [], "truncated": False,
                     "degraded": False, "degraded_reason": [],
                     "generated_at": "2026-10-21T15:00:00+08:00",
                     "target_date": "2026-10-22", "target_date_estimated": True},
        }
    monkeypatch.setattr(bp, "build_plan", _gen)
    r = client.post("/api/battle-plan/generate", json={})
    assert r.status_code == 200
    assert r.json()["outlook"]["stance_label"] == "震荡"


def test_get_plan_fills_degraded_outlook_when_missing(monkeypatch):
    """落库日报缺 outlook 时,端点补一个**降级**空 outlook。

    前端契约里 `outlook` 是必填非 null(组件直接读 `outlook.stance`),
    所以兜底放在端点层 —— 前端不必到处判 null。
    """
    from app.api import battle_plan as bp

    async def _get(plan_date: date):
        return {
            "plan_date": plan_date.isoformat(), "target_date": None,
            "outlook": None, "review": None, "items": [], "meta": {},
        }

    monkeypatch.setattr(bp, "get_plan", _get)
    r = client.get("/api/battle-plan", params={"date": "2026-10-21"})
    assert r.status_code == 200
    o = r.json()["outlook"]
    assert o["stance"] == "unknown"
    assert o["degraded"] is True
    assert o["dims"] == []