"""盘中复盘决策层测试(阶段 T2.1 · 纯函数)

覆盖:四类 `action_state` 边界(含 `_EPS` 口径)/ 缺报价 → 数据不足 /
纪律类 → 不适用 / **不得重算价格**(输出的价格与输入逐位相同)。
"""
from __future__ import annotations

import pytest

from app.services.intraday_advice import (
    STATE_NOT_TRIGGERED,
    STATE_NO_DATA,
    STATE_NA,
    STATE_TRIGGERED,
    build_intraday_advice,
)

OUTLOOK = {
    "stance": "bearish",
    "stance_label": "偏空",
    "score": -2,
    "dims_total": 4,
    "dims_effective": 4,
    "dims": [
        {"key": "volume", "label": "量能", "score": -1, "state": "bear", "detail": "缩量"},
        {"key": "sentiment", "label": "涨跌家数", "score": -1, "state": "bear", "detail": "跌多涨少"},
        {"key": "ma", "label": "指数均线", "score": 0, "state": "flat", "detail": "均线纠缠"},
        {"key": "flow", "label": "板块资金", "score": 0, "state": "flat", "detail": "多空抵消"},
    ],
    "key_levels": {
        "close": 3713.03,
        "ma5": 3700.0,
        "ma10": 3690.0,
        "ma20": 3680.0,
        "support": [3690.0],
        "resistance": [3720.0],
    },
    "degraded": False,
    "degraded_reason": [],
}

NOW = "2026-10-22T11:30:00"


def _item(**kw):
    base = {
        "stock_code": "600519.SH",
        "stock_name": "贵州茅台",
        "item_kind": "stop",
        "direction": "sell",
        "label": "明日止损",
        "trigger_price": 12.39,
        "trigger_condition": "跌破 12.39 元无条件减仓",
        "basis": ["跌破 12.39 元无条件减仓"],
        "invalid_if": "收盘站回 12.39 元上方则不看止损",
        "status_now": "armed",
        "source": "decision.stop_loss",
    }
    base.update(kw)
    return base


def _advice(items, quotes):
    return build_intraday_advice(OUTLOOK, items, quotes, NOW)


# ---------------- 已到价待执行 / 未到价 ----------------

def test_sell_triggered_when_price_below_trigger():
    out = _advice([_item()], {"600519.SH": {"price": 12.30, "change_pct": -1.2}})
    a = out["actions"][0]
    assert a["action_state"] == STATE_TRIGGERED
    assert a["gap_pct"] == pytest.approx((12.30 - 12.39) / 12.39 * 100.0)


def test_sell_not_triggered_when_price_above_trigger():
    out = _advice([_item()], {"600519.SH": {"price": 12.80, "change_pct": 0.5}})
    assert out["actions"][0]["action_state"] == STATE_NOT_TRIGGERED


def test_buy_triggered_when_price_above_trigger():
    out = _advice(
        [_item(item_kind="entry", direction="buy", trigger_price=10.0, label="明日建仓")],
        {"600519.SH": {"price": 10.5, "change_pct": 2.0}},
    )
    assert out["actions"][0]["action_state"] == STATE_TRIGGERED


def test_buy_not_triggered_when_price_below_trigger():
    out = _advice(
        [_item(item_kind="entry", direction="buy", trigger_price=10.0, label="明日建仓")],
        {"600519.SH": {"price": 9.8, "change_pct": -1.0}},
    )
    assert out["actions"][0]["action_state"] == STATE_NOT_TRIGGERED


# ---------------- 等于触发价:_EPS 口径 ----------------

def test_price_exactly_equal_to_trigger_is_triggered_both_directions():
    """恰好等于触发价 → 判「已到价待执行」(浮点容差 1e-9,与兑现模块同口径)"""
    out_sell = _advice([_item()], {"600519.SH": {"price": 12.39, "change_pct": 0.0}})
    assert out_sell["actions"][0]["action_state"] == STATE_TRIGGERED

    out_buy = _advice(
        [_item(item_kind="entry", direction="buy", trigger_price=10.0, label="明日建仓")],
        {"600519.SH": {"price": 10.0, "change_pct": 0.0}},
    )
    assert out_buy["actions"][0]["action_state"] == STATE_TRIGGERED


def test_within_epsilon_counts_as_equal():
    """浮点误差量级(1e-12)不该被判成「未到价」"""
    out_sell = _advice([_item()], {"600519.SH": {"price": 12.39 + 1e-12, "change_pct": 0.0}})
    assert out_sell["actions"][0]["action_state"] == STATE_TRIGGERED

    out_buy = _advice(
        [_item(item_kind="entry", direction="buy", trigger_price=10.0, label="明日建仓")],
        {"600519.SH": {"price": 10.0 - 1e-12, "change_pct": 0.0}},
    )
    assert out_buy["actions"][0]["action_state"] == STATE_TRIGGERED


def test_beyond_epsilon_is_not_triggered():
    out_sell = _advice([_item()], {"600519.SH": {"price": 12.39 + 1e-6, "change_pct": 0.0}})
    assert out_sell["actions"][0]["action_state"] == STATE_NOT_TRIGGERED

    out_buy = _advice(
        [_item(item_kind="entry", direction="buy", trigger_price=10.0, label="明日建仓")],
        {"600519.SH": {"price": 10.0 - 1e-6, "change_pct": 0.0}},
    )
    assert out_buy["actions"][0]["action_state"] == STATE_NOT_TRIGGERED


# ---------------- 数据不足 ----------------

def test_missing_quote_is_data_insufficient():
    out = _advice([_item()], {})
    a = out["actions"][0]
    assert a["action_state"] == STATE_NO_DATA
    assert a["current_price"] is None
    assert a["gap_pct"] is None
    assert out["degraded"] is True
    assert "600519.SH" in (out["degraded_reason"] or "")


def test_quote_without_price_is_data_insufficient():
    out = _advice([_item()], {"600519.SH": {"price": None, "change_pct": None}})
    assert out["actions"][0]["action_state"] == STATE_NO_DATA


def test_item_without_trigger_price_is_data_insufficient():
    """有方向但没有触发价 → 数据不足(不猜)"""
    out = _advice(
        [_item(item_kind="stop", direction="sell", trigger_price=None)],
        {"600519.SH": {"price": 12.39, "change_pct": 0.0}},
    )
    a = out["actions"][0]
    assert a["action_state"] == STATE_NO_DATA
    assert a["trigger_price"] is None
    assert out["degraded"] is True


# ---------------- 不适用(纪律类) ----------------

def test_do_not_item_is_not_applicable():
    out = _advice(
        [_item(item_kind="do_not", direction="none", trigger_price=None, label="明日别动")],
        {"600519.SH": {"price": 12.39, "change_pct": 0.0}},
    )
    a = out["actions"][0]
    assert a["action_state"] == STATE_NA
    assert a["gap_pct"] is None


def test_unlock_item_is_not_applicable():
    out = _advice(
        [_item(item_kind="unlock", direction="buy", trigger_price=11.0, label="明日解锁后:建仓")],
        {"600519.SH": {"price": 12.39, "change_pct": 0.0}},
    )
    assert out["actions"][0]["action_state"] == STATE_NA


def test_watch_item_without_direction_is_not_applicable():
    out = _advice(
        [_item(item_kind="watch", direction="none", trigger_price=13.0, label="明日观察")],
        {"600519.SH": {"price": 12.39, "change_pct": 0.0}},
    )
    assert out["actions"][0]["action_state"] == STATE_NA


# ---------------- 不得重算价格 ----------------

def test_prices_are_passed_through_untouched():
    """输出的价格必须与输入**逐位相同**(不得四舍五入、不得重算)"""
    trigger = 12.39123456789
    price = 12.37555555555
    out = _advice(
        [_item(trigger_price=trigger)],
        {"600519.SH": {"price": price, "change_pct": -0.13}},
    )
    a = out["actions"][0]
    assert repr(a["trigger_price"]) == repr(trigger)
    assert repr(a["current_price"]) == repr(price)
    # gap_pct 是显式四则运算的结果(允许与输入不同)
    assert a["gap_pct"] == (price - trigger) / trigger * 100.0


def test_action_hint_only_restates_basis_and_invalid_if():
    out = _advice([_item()], {"600519.SH": {"price": 12.30, "change_pct": -1.2}})
    hint = out["actions"][0]["action_hint"]
    assert "跌破 12.39 元无条件减仓" in hint
    assert "收盘站回 12.39 元上方则不看止损" in hint


# ---------------- 结构 / 每条预案一行 ----------------

def test_each_item_gets_its_own_row():
    items = [
        _item(item_kind="stop", direction="sell", trigger_price=12.39, label="明日止损"),
        _item(item_kind="t_sell", direction="sell", trigger_price=13.10, label="明日做T减仓"),
        _item(item_kind="t_buyback", direction="buy", trigger_price=11.80, label="明日做T回补"),
    ]
    out = _advice(items, {"600519.SH": {"price": 12.30, "change_pct": -1.2}})
    assert len(out["actions"]) == 3
    assert [a["item_kind"] for a in out["actions"]] == ["stop", "t_sell", "t_buyback"]
    # 同票多条预案 → 不合并
    assert len({a["stock_code"] for a in out["actions"]}) == 1


def test_market_opinion_reuses_outlook_without_recomputation():
    out = _advice([_item()], {"600519.SH": {"price": 12.30, "change_pct": -1.2}})
    mo = out["market_opinion"]
    assert mo["stance"] == "bearish"
    assert mo["stance_label"] == "偏空"
    assert mo["basis"] == "盘前四维度规则推断（非盘中重算）"
    assert mo["dims"] == OUTLOOK["dims"]
    assert mo["key_levels"] == OUTLOOK["key_levels"]
    assert "偏空" in mo["summary"]
    assert "3690.00" in mo["summary"]


def test_missing_outlook_is_degraded():
    out = build_intraday_advice({}, [], {}, NOW)
    assert out["degraded"] is True
    assert out["market_opinion"]["stance"] == "unknown"
    assert out["actions"] == []


def test_as_of_is_recorded():
    out = _advice([], {})
    assert out["as_of"] == NOW
