"""决策 → 明日预案转换(纯函数、零 IO)设计文档 §4.4"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.plan_item_builder import build_items, build_todos


def _action(kind="entry", status="armed", price=10.0, label="支撑企稳建仓",
            condition="回踩 10.00 元不破时首仓建仓", basis=None):
    return {
        "kind": kind, "label": label, "condition": condition,
        "price": price, "basis": basis if basis is not None else [f"依据 {price}"],
        "status": status,
    }


class _Pos:
    """持仓视图(属性形状,与 services/position_status.resolve_position_status 同契约)"""

    def __init__(self, shares=0, avg_cost=0.0):
        self.shares = shares
        self.avg_cost = avg_cost


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
    items = build_items(d, _Pos(600, 15.578))
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
    """用**动作身份**(label + condition)判不重叠,不用价格。

    为什么不用价格:同一个价位可能同时出现在「今日待办」与「明日预案」
    (如止损动作 status=now 与 stop_loss 字段同价) —— 价格集合会误判成重叠,
    这条测试就永远抓不到真正的动作级回归。

    ⚠️ 比较前必须把 item 侧的「明日」前缀去掉:预案项的 label 带「明日」(那是明日预案),
    待办的不带(那是今日待办)。不剥前缀的话,同一动作在两个出口的 label 必然不等 →
    集合交恒为空 → 这条测试对「同一动作同时出现在两个出口」完全免疫,失去判别力。
    """
    d = _decision([_action(status="now", price=1.0, label="分批止盈"),
                   _action(status="armed", price=2.0, label="支撑企稳建仓")])
    item_keys = {(i["label"].removeprefix("明日"), i["trigger_condition"])
                 for i in build_items(d, None)}
    todo_keys = {(t["label"], t["condition"]) for t in build_todos(d)}
    assert not (item_keys & todo_keys)


def test_todos_and_items_never_overlap_even_with_same_price():
    """同价位、不同动作 → 仍必须不重叠(价格集合法在这里会误判)"""
    d = _decision([_action(status="now", price=9.62, label="分批止盈"),
                   _action(status="armed", price=9.62, label="支撑企稳建仓")])
    item_keys = {(i["label"].removeprefix("明日"), i["trigger_condition"])
                 for i in build_items(d, None)}
    todo_keys = {(t["label"], t["condition"]) for t in build_todos(d)}
    assert not (item_keys & todo_keys)
    assert len(item_keys) == 1 and len(todo_keys) == 1


def test_same_action_in_both_exports_is_detected():
    """判别力自检:同一个动作若同时出现在两个出口,身份键集合**必须**相交

    (这条测试保证上面两条不会因为「前缀/字段不一致」而恒真)
    """
    same = _action(status="now", price=9.62, label="分批止盈")
    d = _decision([same, dict(same, status="armed")])
    item_keys = {(i["label"].removeprefix("明日"), i["trigger_condition"])
                 for i in build_items(d, None)}
    todo_keys = {(t["label"], t["condition"]) for t in build_todos(d)}
    assert item_keys & todo_keys, "同一动作同时出现在两个出口时,身份键必须相交"


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
        items = build_items(d, _Pos(100, 10.0))
        assert items and items[0]["direction"] == "buy", kind


def test_direction_mapping_sell_kinds():
    for kind in ("exit", "stop", "t_sell"):
        d = _decision([_action(kind=kind, status="armed")])
        items = build_items(d, _Pos(100, 10.0))
        assert items and items[0]["direction"] == "sell", kind


def test_watch_action_direction_none():
    d = _decision([_action(kind="watch", status="armed", price=None)])
    items = build_items(d, None)
    assert items[0]["direction"] == "none"


# ---------------- 止损 / 做T / 别动 ----------------

def test_stop_loss_item_only_when_has_position():
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    assert build_items(d, None) == []
    items = build_items(d, _Pos(600, 15.578))
    kinds = [i["item_kind"] for i in items]
    assert "stop" in kinds


def test_stop_loss_item_invalid_if():
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    items = build_items(d, _Pos(600, 15.578))
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
    items = build_items(d, _Pos(600, 15.578))
    tp = [i for i in items if i["item_kind"] in ("t_sell", "t_buyback")]
    assert len(tp) == 2
    sell = next(i for i in tp if i["item_kind"] == "t_sell")
    buy = next(i for i in tp if i["item_kind"] == "t_buyback")
    assert sell["direction"] == "sell" and sell["trigger_price"] == 10.5
    assert buy["direction"] == "buy" and buy["trigger_price"] == 9.2


def test_t_plan_skipped_when_not_suitable():
    d = _decision()   # suitable=False
    items = build_items(d, _Pos(600, 15.578))
    assert [i for i in items if i["item_kind"].startswith("t_")] == []


def test_t_plan_skipped_when_no_position():
    d = _decision(t_plan={
        "suitable": True, "t_high": 10.5, "t_low": 9.2, "amplitude_pct": 12.0,
        "sell_trigger": "s", "buyback_trigger": "b", "base_position_pct": "≥50%",
        "unsuitable_signals": "", "needs_position": False,
    })
    items = build_items(d, None)
    assert [i for i in items if i["item_kind"].startswith("t_")] == []


def test_dict_position_raises_instead_of_silently_skipping_position_items():
    """传 dict 必须**响亮失败**:静默当空仓会让持仓票的止损/做T子项整条消失"""
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    with pytest.raises(TypeError):
        build_items(d, {"shares": 600, "avg_cost": 15.578})


def test_none_position_is_not_an_error():
    """position=None 是合法输入(该票没持仓) —— 不能抛异常"""
    d = _decision([_action(status="armed", price=9.62)])
    assert build_items(d, None) != []


def test_do_not_items():
    d = _decision(do_not=["下跌通道中不要抄底", "距上次卖出仅 1 天,勿频繁操作"])
    items = build_items(d, _Pos(600, 15.578))
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
    items = build_items(d, _Pos(100, 10.0))
    assert "12.39" in items[0]["invalid_if"]


def test_invalid_if_present_on_every_item():
    d = _decision(
        [_action(kind="entry", status="armed", price=10.0)],
        stop_loss={"price": 9.62, "basis": "b"},
        do_not=["别动"],
    )
    items = build_items(d, _Pos(100, 10.0))
    for it in items:
        assert it["invalid_if"], it


# ---------------- 边界 ----------------

def test_empty_actions_returns_empty_list():
    assert build_items(_decision([]), _Pos(100, 10.0)) == []


def test_action_with_none_price_yields_none_trigger():
    d = _decision([_action(kind="watch", status="armed", price=None)])
    items = build_items(d, None)
    assert items[0]["trigger_price"] is None


def test_basis_preserved_verbatim():
    basis = ["企稳价 9.62 元(现价 9.920 +3.1%)", "stabilize.state=true"]
    d = _decision([_action(status="armed", price=9.62, basis=basis)])
    items = build_items(d, None)
    assert items[0]["basis"] == basis


def test_unlock_uses_explicit_missing_when_provided():
    """决策层给了 missing → 解锁依据必须是**真正没满足的条件**,不是 basis 里的事实"""
    a = _action(status="blocked", price=9.92, label="补仓摊薄",
                basis=["持仓 600 股 @ 成本 15.58 元", "补 100 股后均价 9.87 元"])
    a["missing"] = ["下跌通道(趋势未破条件不成立)", "尚无企稳信号"]
    d = _decision([a])
    it = build_items(d, None)[0]
    assert it["item_kind"] == "unlock"
    assert "下跌通道" in it["invalid_if"]
    assert "尚无企稳信号" in it["invalid_if"]
    assert "均价" not in it["invalid_if"]      # ← 事实不是条件


def test_unlock_invalid_if_has_no_duplicate_suffix():
    """缺失依据里已含「未达」就别再叠一句「未满足则不解锁」"""
    a = _action(status="blocked", price=12.5,
                basis=["压力位 12.50 元", "量能仅 0.90 倍,未达 1.50 倍确认标准"])
    a["missing"] = ["量能仅 0.90 倍,未达 1.50 倍确认标准"]
    it = build_items(_decision([a]), None)[0]
    assert it["invalid_if"].count("未满足") == 0
    assert it["invalid_if"].endswith("则不解锁")


def test_stop_item_wording_reflects_already_triggered_stop():
    """止损位今天已被击穿 → 明日预案不能写「跌破 X 元无条件减仓」(那是过期建议)"""
    now_stop = _action(kind="stop", status="now", price=9.62, label="无条件止损")
    d = _decision([now_stop], stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    items = build_items(d, _Pos(600, 15.578))
    stop = next(i for i in items if i["item_kind"] == "stop")
    assert "已跌破 9.62" in stop["trigger_condition"]
    assert "跌破 9.62 元无条件减仓" not in stop["trigger_condition"]


def test_stop_item_wording_normal_when_stop_not_yet_triggered():
    """止损位未击穿 → 正常写「跌破 X 元无条件减仓」"""
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    items = build_items(d, _Pos(600, 15.578))
    stop = next(i for i in items if i["item_kind"] == "stop")
    assert stop["trigger_condition"] == "跌破 9.62 元无条件减仓"


def test_every_item_carries_source():
    """溯源字段(spec §4.4.4):每条预案都要能说清来自决策引擎的哪一块"""
    blocked = _action(status="blocked", price=12.5, label="放量突破追进",
                      basis=["压力位 12.50 元", "量能仅 0.90 倍,未达 1.50 倍确认标准"])
    d = _decision([_action(status="armed", price=9.62), blocked],
                  stop_loss={"price": 9.62, "basis": "b"},
                  t_plan={"suitable": True, "t_high": 10.5, "t_low": 9.2,
                          "amplitude_pct": 12.0, "sell_trigger": "s", "buyback_trigger": "b",
                          "base_position_pct": "≥50%", "unsuitable_signals": "",
                          "needs_position": False},
                  do_not=["下跌通道中不要抄底"])
    items = build_items(d, _Pos(600, 15.578))
    assert items, "至少要有一条"
    assert all(i.get("source") for i in items)
    by_kind = {i["item_kind"]: i["source"] for i in items}
    assert by_kind["entry"] == "decision.actions"
    assert by_kind["stop"] == "decision.stop_loss"
    assert by_kind["t_sell"] == "decision.t_plan"
    assert by_kind["do_not"] == "decision.do_not"
    assert by_kind["unlock"] == "decision.actions"


def test_item_labels_use_mingri_wording():
    """spec §4.4.5:预案项措辞统一用「明日」,避免与生成时点混淆"""
    d = _decision([_action(status="armed", price=9.62)],
                  stop_loss={"price": 9.62, "basis": "b"},
                  t_plan={"suitable": True, "t_high": 10.5, "t_low": 9.2,
                          "amplitude_pct": 12.0, "sell_trigger": "s", "buyback_trigger": "b",
                          "base_position_pct": "≥50%", "unsuitable_signals": "",
                          "needs_position": False},
                  do_not=["下跌通道中不要抄底"])
    items = build_items(d, _Pos(600, 15.578))
    assert all(i["label"].startswith("明日") for i in items)


def test_decimal_shares_accepted_like_position_status():
    """Decimal 股数必须被接受 —— 与 `position_status.resolve_position_status` **同契约**。

    为什么:position_status 的契约明写「int / float / bool / Decimal 实测均可」;
    若本模块只收 (int, float),同一个 Decimal 持仓在两个模块里结论不同 ——
    契约分裂,谁也不认谁的账。选定的契约:数值(int / float / bool / Decimal)一律接受。
    """
    d = _decision(stop_loss={"price": 9.62, "basis": "b"})
    items = build_items(d, _Pos(Decimal("600"), 15.578))
    assert any(i["item_kind"] == "stop" for i in items)


def test_malformed_shares_raises_instead_of_silently_no_position():
    """形状对但值畸形(如 'abc')→ 响亮失败,不能静默当成空仓(否则止损/做T整条消失)"""
    d = _decision(stop_loss={"price": 9.62, "basis": "b"})
    with pytest.raises(TypeError):
        build_items(d, _Pos("abc", 15.578))


def test_nan_shares_raises_instead_of_silently_no_position():
    """NaN 与任何数比较都是 False → 会被静默当成「无持仓」,必须响亮失败"""
    d = _decision(stop_loss={"price": 9.62, "basis": "b"})
    with pytest.raises(TypeError):
        build_items(d, _Pos(float("nan"), 15.578))
