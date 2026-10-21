"""决策 → 明日预案转换(纯函数、零 IO)设计文档 §4.4"""
from __future__ import annotations

from app.services.plan_item_builder import build_items, build_todos


def _action(kind="entry", status="armed", price=10.0, label="支撑企稳建仓",
            condition="回踩 10.00 元不破时首仓建仓", basis=None):
    return {
        "kind": kind, "label": label, "condition": condition,
        "price": price, "basis": basis if basis is not None else [f"依据 {price}"],
        "status": status,
    }


def _decision(actions=None, **kw):
    d = {
        "stock_code": "001896.SZ", "stock_name": "豫能控股",
        "verdict": "hold", "headline": "现价 9.92,等触发",
        "confidence": "medium", "role": "解套参考", "position_status": "loss",
        "actions": actions if actions is not None else [],
        "stop_loss": None, "position_pct": "解套优先",
        "do_not": [], "t_plan": {"suitable": False, "t_high": None, "t_low": None,
                                "amplitude_pct": None, "sell_trigger": "", "buyback_trigger": "",
                                "base_position_pct": "", "unsuitable_signals": "不合适",
                                "needs_position": False},
        "trend_state": {}, "market_env": {}, "data_quality": {"degraded": False},
    }
    d.update(kw)
    return d


# ---------------- 三路分流 ----------------

def test_armed_action_becomes_plan_item():
    d = _decision([_action(status="armed", price=9.62)])
    items = build_items(d, {"shares": 600, "avg_cost": 15.578})
    assert len(items) == 1
    it = items[0]
    assert it["item_kind"] == "entry"
    assert it["direction"] == "buy"
    assert it["trigger_price"] == 9.62
    assert it["status_now"] == "armed"
    assert it["basis"]


def test_now_action_does_not_enter_plan_items():
    d = _decision([_action(status="now", price=9.62)])
    assert build_items(d, None) == []


def test_now_action_goes_to_todos():
    d = _decision([_action(status="now", price=9.62, label="分批止盈")])
    todos = build_todos(d)
    assert len(todos) == 1
    assert todos[0]["label"] == "分批止盈"
    assert todos[0]["price"] == 9.62
    assert todos[0]["condition"]


def test_todos_and_items_never_overlap():
    d = _decision([_action(status="now", price=1.0), _action(status="armed", price=2.0)])
    item_prices = {i["trigger_price"] for i in build_items(d, None)}
    todo_prices = {t["price"] for t in build_todos(d)}
    assert not (item_prices & todo_prices)


def test_blocked_action_becomes_unlock_item():
    d = _decision([_action(status="blocked", price=12.5,
                            basis=["压力位 12.50 元", "量能仅 0.90 倍,未达 1.50 倍确认标准"])])
    items = build_items(d, None)
    assert len(items) == 1
    it = items[0]
    assert it["item_kind"] == "unlock"
    assert it["status_now"] == "blocked"
    assert "量能" in it["invalid_if"]


# ---------------- 方向映射 ----------------

def test_direction_mapping_buy_kinds():
    for kind in ("entry", "add", "t_buyback"):
        d = _decision([_action(kind=kind, status="armed")])
        items = build_items(d, {"shares": 100, "avg_cost": 10.0})
        assert items and items[0]["direction"] == "buy", kind


def test_direction_mapping_sell_kinds():
    for kind in ("exit", "stop", "t_sell"):
        d = _decision([_action(kind=kind, status="armed")])
        items = build_items(d, {"shares": 100, "avg_cost": 10.0})
        assert items and items[0]["direction"] == "sell", kind


def test_watch_action_direction_none():
    d = _decision([_action(kind="watch", status="armed", price=None)])
    items = build_items(d, None)
    assert items[0]["direction"] == "none"


# ---------------- 止损 / 做T / 别动 ----------------

def test_stop_loss_item_only_when_has_position():
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    assert build_items(d, None) == []
    items = build_items(d, {"shares": 600, "avg_cost": 15.578})
    kinds = [i["item_kind"] for i in items]
    assert "stop" in kinds


def test_stop_loss_item_invalid_if():
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    items = build_items(d, {"shares": 600, "avg_cost": 15.578})
    stop = next(i for i in items if i["item_kind"] == "stop")
    assert stop["direction"] == "sell"
    assert stop["trigger_price"] == 9.62
    assert "9.62" in stop["invalid_if"]


def test_t_plan_splits_into_two_items():
    d = _decision(t_plan={
        "suitable": True, "t_high": 10.5, "t_low": 9.2, "amplitude_pct": 12.0,
        "sell_trigger": "冲高至 10.50 元附近卖出 T 仓", "buyback_trigger": "回落至 9.20 元附近买回",
        "base_position_pct": "≥50%", "unsuitable_signals": "", "needs_position": False,
    })
    items = build_items(d, {"shares": 600, "avg_cost": 15.578})
    tp = [i for i in items if i["item_kind"] in ("t_sell", "t_buyback")]
    assert len(tp) == 2
    sell = next(i for i in tp if i["item_kind"] == "t_sell")
    buy = next(i for i in tp if i["item_kind"] == "t_buyback")
    assert sell["direction"] == "sell" and sell["trigger_price"] == 10.5
    assert buy["direction"] == "buy" and buy["trigger_price"] == 9.2


def test_t_plan_skipped_when_not_suitable():
    d = _decision()   # suitable=False
    items = build_items(d, {"shares": 600, "avg_cost": 15.578})
    assert [i for i in items if i["item_kind"].startswith("t_")] == []


def test_t_plan_skipped_when_no_position():
    d = _decision(t_plan={
        "suitable": True, "t_high": 10.5, "t_low": 9.2, "amplitude_pct": 12.0,
        "sell_trigger": "s", "buyback_trigger": "b", "base_position_pct": "≥50%",
        "unsuitable_signals": "", "needs_position": False,
    })
    items = build_items(d, None)
    assert [i for i in items if i["item_kind"].startswith("t_")] == []


def test_do_not_items():
    d = _decision(do_not=["下跌通道中不要抄底", "距上次卖出仅 1 天,勿频繁操作"])
    items = build_items(d, {"shares": 600, "avg_cost": 15.578})
    dn = [i for i in items if i["item_kind"] == "do_not"]
    assert len(dn) == 2
    assert all(i["direction"] == "none" for i in dn)
    assert all(i["trigger_price"] is None for i in dn)


# ---------------- 失效条件计算 ----------------

def test_entry_invalid_if_uses_097():
    d = _decision([_action(kind="entry", status="armed", price=10.0)])
    items = build_items(d, None)
    assert "9.70" in items[0]["invalid_if"]


def test_exit_invalid_if_uses_103():
    d = _decision([_action(kind="exit", status="armed", price=12.03)])
    items = build_items(d, {"shares": 100, "avg_cost": 10.0})
    assert "12.39" in items[0]["invalid_if"]


def test_invalid_if_present_on_every_item():
    d = _decision(
        [_action(kind="entry", status="armed", price=10.0)],
        stop_loss={"price": 9.62, "basis": "b"},
        do_not=["别动"],
    )
    items = build_items(d, {"shares": 100, "avg_cost": 10.0})
    for it in items:
        assert it["invalid_if"], it


# ---------------- 边界 ----------------

def test_empty_actions_returns_empty_list():
    assert build_items(_decision([]), {"shares": 100, "avg_cost": 10.0}) == []


def test_action_with_none_price_yields_none_trigger():
    d = _decision([_action(kind="watch", status="armed", price=None)])
    items = build_items(d, None)
    assert items[0]["trigger_price"] is None


def test_basis_preserved_verbatim():
    basis = ["企稳价 9.62 元(现价 9.920 +3.1%)", "stabilize.state=true"]
    d = _decision([_action(status="armed", price=9.62, basis=basis)])
    items = build_items(d, None)
    assert items[0]["basis"] == basis