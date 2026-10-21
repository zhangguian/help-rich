"""作战计划编排层测试(外部 IO 全部 mock)"""
from __future__ import annotations

from datetime import date

import pytest

from app.services import battle_plan_service as svc


def _stock(code="001896.SZ", name="豫能控股", price=9.92, shares=600, avg_cost=15.578):
    return {
        "stock_code": code, "stock_name": name, "in_position": True,
        "is_favorite": False, "shares": shares, "avg_cost": avg_cost,
        "current_price": price,
    }


@pytest.mark.asyncio
async def test_resolve_scope_merges_positions_and_favorites(monkeypatch):
    async def _pos():
        return [_stock("001896.SZ"), _stock("000807.SZ", "云铝股份", 24.93, 100, 8.977)]
    async def _fav():
        return [{"stock_code": "001896.SZ", "stock_name": "豫能控股"},
                {"stock_code": "300394.SZ", "stock_name": "天孚通信"}]
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    scope = await svc.resolve_target_stocks()
    codes = {s["stock_code"] for s in scope}
    assert codes == {"001896.SZ", "000807.SZ", "300394.SZ"}
    by_code = {s["stock_code"]: s for s in scope}
    assert by_code["001896.SZ"]["in_position"] is True
    assert by_code["001896.SZ"]["is_favorite"] is True
    assert by_code["300394.SZ"]["in_position"] is False


@pytest.mark.asyncio
async def test_resolve_scope_merges_without_truncating(monkeypatch):
    """resolve_target_stocks 只做**合并去重**,不做上限截断。

    为什么:截断与「是否真的截断」这个标志必须由同一处产出。
    若这里先切一刀,build_plan 里再切一次就永远切不动(len 恰好 == MAX_SCOPE),
    meta["truncated"] 恒为 False —— 等于向用户谎称「一只票都没砍掉」。
    """
    async def _pos():
        return [_stock(f"00000{i}.SZ", f"票{i}", 10.0, 100, 9.0) for i in range(25)]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)
    scope = await svc.resolve_target_stocks()
    assert len(scope) == 25
    # 截断标志必须精确:只有真的砍掉了票才为 True
    cut, truncated = svc._truncate_scope(scope)
    assert len(cut) == svc.MAX_SCOPE
    assert truncated is True
    _exact, not_truncated = svc._truncate_scope(
        [_stock(f"00000{i}.SZ") for i in range(svc.MAX_SCOPE)]
    )
    assert not_truncated is False


@pytest.mark.asyncio
async def test_build_plan_degrades_when_one_stock_fails(monkeypatch):
    async def _pos():
        return [_stock("001896.SZ"), _stock("000807.SZ", "云铝股份", 24.93, 100, 8.977)]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    async def _one(code, *a, **kw):
        if code == "000807.SZ":
            raise RuntimeError("K 线不可用")
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _one)

    def _ind(klines):
        """⚠️ `compute_indicators` 是**同步**函数(ta_service.py: `def compute_indicators`),
        这里必须用同步 mock —— 写成 async 会让 indicators 变成协程对象,
        build_decision 访问 ctx.indicators.xxx 时炸 AttributeError。"""
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 8.26,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)

    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 50, "down_total": 50}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)

    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    codes = {i["stock_code"] for i in plan["items"]}
    assert "000807.SZ" not in codes
    assert plan["meta"]["degraded"] is True
    assert any("000807.SZ" in r for r in plan["meta"]["degraded_reason"])


@pytest.mark.asyncio
async def test_build_plan_returns_three_sections(monkeypatch):
    async def _pos():
        return [_stock()]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)
    async def _k(code, *a, **kw):
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _k)
    def _ind(klines):
        """⚠️ `compute_indicators` 是**同步**函数(ta_service.py: `def compute_indicators`),
        这里必须用同步 mock —— 写成 async 会让 indicators 变成协程对象,
        build_decision 访问 ctx.indicators.xxx 时炸 AttributeError。"""
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 8.26,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)
    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 60, "down_total": 40}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    assert {"plan_date", "outlook", "review", "items", "meta"} <= set(plan)
    assert plan["outlook"]["stance"] in ("bullish", "bearish", "neutral", "unknown")
    assert len(plan["outlook"]["dims"]) == 4
    assert plan["meta"]["scope_count"] >= 1


@pytest.mark.asyncio
async def test_build_plan_puts_now_actions_into_review_pending_todos(monkeypatch):
    """status=="now" 的动作必须进 review.pending_todos(今日未执行待办)

    这是 spec §4.4.2 三路分流的核心:now 不进明日预案,只进复盘待办。
    mock 让止损位(9.95)高于现价(9.9)→ 决策引擎产出 status=="now" 的 stop 动作。
    """
    async def _pos():
        return [_stock()]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    async def _k(code, *a, **kw):
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _k)

    def _ind(klines):
        """⚠️ `compute_indicators` 是**同步**函数(ta_service.py: `def compute_indicators`),
        这里必须用同步 mock —— 写成 async 会让 indicators 变成协程对象,
        build_decision 访问 ctx.indicators.xxx 时炸 AttributeError。"""
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 9.95,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)

    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 50, "down_total": 50}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    todos = plan["review"]["pending_todos"]
    assert len(todos) >= 1
    assert todos[0]["stock_code"] == "001896.SZ"
    assert todos[0]["label"]
    # now 动作不得出现在明日预案里
    assert all(i["status_now"] != "now" for i in plan["items"])


@pytest.mark.asyncio
async def test_build_plan_meta_truncated_flag_is_true_when_scope_exceeds_max(monkeypatch):
    """端到端:股票池超上限时 meta["truncated"] 必须为 True —— 不许谎称没砍票"""
    async def _pos():
        return [_stock(f"00000{i}.SZ", f"票{i}", 10.0, 100, 9.0) for i in range(25)]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    async def _k(code, *a, **kw):
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _k)

    def _ind(klines):
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 8.26,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)

    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 50, "down_total": 50}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    assert plan["meta"]["truncated"] is True
    assert plan["meta"]["scope_count"] == svc.MAX_SCOPE


@pytest.mark.asyncio
async def test_fulfillment_uses_only_target_day_kline(monkeypatch):
    """兑现比对只能用**目标日那一根** K 线。

    check_fulfillment 会把传入 K 线的 high/low 合成为当日极值 ——
    一次给 5 根等于把「5 天极值」当成「单日极值」→ 昨天没到位的价位
    会被说成目标日触及了。这里造一根「前一天击穿、目标日没击穿」的 K 线锁死该行为。
    """
    prev_plan = {
        "id": 1, "plan_date": "2026-10-21",
        "outlook": None, "review": None,
        "meta": {"target_date": "2026-10-22"},
    }
    prev_items = [{
        "id": 1, "stock_code": "001896.SZ", "item_kind": "entry", "direction": "buy",
        "trigger_price": 9.62, "status_now": "armed", "label": "建仓",
    }]

    class _Repo:
        async def get_plan(self, plan_date):
            return prev_plan if plan_date == "2026-10-21" else None

        async def get_items(self, plan_id):
            return prev_items

        async def update_item_fulfillment(self, item_id, fulfillment, note=""):
            return None

    monkeypatch.setattr(svc, "battle_plan_repo", _Repo())

    async def _k(code, *a, **kw):
        return [
            {"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.80,
             "close": 9.9, "volume": 100},
            {"date": "2026-10-22", "open": 9.0, "high": 9.90, "low": 9.70,
             "close": 9.8, "volume": 100},
        ]
    monkeypatch.setattr(svc, "fetch_klines", _k)

    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)

    review = await svc._build_review("2026-10-21", "2026-10-22", [])
    assert review["fulfillment"]["items"][0]["fulfillment"] == "missed"
