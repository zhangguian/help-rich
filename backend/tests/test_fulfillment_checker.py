"""昨日预案 × 今日行情/流水 → 兑现状态(纯函数、零 IO)设计文档 §4.5"""
from __future__ import annotations

from app.services.fulfillment_checker import check_fulfillment


def _item(code="001896.SZ", kind="entry", direction="buy", price=9.62, label="建仓"):
    return {
        "stock_code": code, "stock_name": "豫能控股", "item_kind": kind,
        "direction": direction, "label": label, "trigger_price": price,
        "trigger_condition": "c", "basis": ["b"], "invalid_if": "i",
        "status_now": "armed", "fulfillment": "pending", "fulfillment_note": "",
    }


def _kline(high=10.0, low=9.0, close=9.5, open_=9.2):
    return {"date": "2026-10-22", "open": open_, "high": high, "low": low, "close": close}


def _txn(code="001896.SZ", action="buy", price=9.5, shares=100):
    return {"stock_code": code, "action": action, "shares": shares,
            "price": price, "trade_date": "2026-10-22"}


# ---------------- 触及判定 ----------------

def test_buy_touched_when_low_reaches_trigger():
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.5)]}, [])
    assert out[0]["fulfillment"] == "touched"


def test_buy_missed_when_low_above_trigger():
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.70)]}, [])
    assert out[0]["fulfillment"] == "missed"


def test_sell_touched_when_high_reaches_trigger():
    out = check_fulfillment([_item(kind="exit", direction="sell", price=12.03)],
                            {"001896.SZ": [_kline(high=12.5)]}, [])
    assert out[0]["fulfillment"] == "touched"


def test_sell_missed_when_high_below_trigger():
    out = check_fulfillment([_item(kind="exit", direction="sell", price=12.03)],
                            {"001896.SZ": [_kline(high=11.9)]}, [])
    assert out[0]["fulfillment"] == "missed"


def test_none_direction_is_na():
    out = check_fulfillment([_item(kind="do_not", direction="none", price=None)],
                            {"001896.SZ": [_kline()]}, [])
    assert out[0]["fulfillment"] == "n_a"


def test_no_kline_data_treated_as_missed_not_touched():
    out = check_fulfillment([_item(direction="buy", price=9.62)], {}, [])
    assert out[0]["fulfillment"] == "missed"


# ---------------- 执行判定(优先于触及) ----------------

def test_executed_when_buy_transaction_present():
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.7)]},
                            [_txn(action="buy")])
    assert out[0]["fulfillment"] == "executed"


def test_executed_when_sell_transaction_present():
    out = check_fulfillment([_item(kind="exit", direction="sell", price=12.03)],
                            {"001896.SZ": [_kline(high=11.0)]},
                            [_txn(action="sell")])
    assert out[0]["fulfillment"] == "executed"


def test_transaction_for_other_stock_ignored():
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.5)]},
                            [_txn(code="000807.SZ", action="buy")])
    assert out[0]["fulfillment"] == "touched"


# ---------------- T 计划双子项 ----------------

def test_t_plan_sell_and_buyback_checked_independently():
    items = [
        _item(kind="t_sell", direction="sell", price=10.5, label="做T减仓"),
        _item(kind="t_buyback", direction="buy", price=9.2, label="做T回补"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.8, low=9.5)]}, [])
    by_kind = {i["item_kind"]: i for i in out}
    assert by_kind["t_sell"]["fulfillment"] == "touched"
    assert by_kind["t_buyback"]["fulfillment"] == "missed"


def test_t_plan_buyback_executed_by_buy_transaction():
    items = [
        _item(kind="t_sell", direction="sell", price=10.5, label="做T减仓"),
        _item(kind="t_buyback", direction="buy", price=9.2, label="做T回补"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.5)]},
                            [_txn(action="buy", price=9.1)])
    by_kind = {i["item_kind"]: i for i in out}
    assert by_kind["t_buyback"]["fulfillment"] == "executed"
    assert by_kind["t_sell"]["fulfillment"] == "missed"


# ---------------- 纪律问题 ----------------

def test_discipline_violation_flagged_when_do_not_but_traded():
    items = [_item(kind="do_not", direction="none", price=None, label="别动")]
    out = check_fulfillment(items, {"001896.SZ": [_kline()]}, [_txn(action="buy")])
    assert out[0]["fulfillment"] == "executed"
    assert "纪律问题" in out[0]["fulfillment_note"]


def test_discipline_violation_flagged_when_unlock_blocked_but_traded():
    items = [_item(kind="unlock", direction="buy", price=12.5, label="解锁后建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline()]}, [_txn(action="buy")])
    assert out[0]["fulfillment"] == "executed"
    assert "纪律问题" in out[0]["fulfillment_note"]


def test_do_not_with_sell_operation_also_flagged():
    """别动项:买卖任一方向的操作都算违规(spec §4.5 第四步:「有该票的买卖操作」)"""
    items = [_item(kind="do_not", direction="none", price=None, label="别动")]
    out = check_fulfillment(items, {"001896.SZ": [_kline()]}, [_txn(action="sell")])
    assert out[0]["fulfillment"] == "executed"
    assert "纪律问题" in out[0]["fulfillment_note"]


def test_unlock_without_operation_is_not_counted_as_gap():
    """解锁类(未解锁)本来就不该执行 —— 没操作记 n_a,不计入统计(spec §4.5.4)"""
    items = [_item(kind="unlock", direction="buy", price=12.5, label="解锁后建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(low=9.0)]}, [])
    assert out[0]["fulfillment"] == "n_a"


def test_t_buyback_not_executed_when_bought_above_target_price():
    """T 回补按**价格区间**匹配(spec §4.5):买价高于下沿×1.02 → 不算按计划回补"""
    items = [_item(kind="t_buyback", direction="buy", price=9.2, label="做T回补")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.4)]},
                            [_txn(action="buy", price=9.5)])
    assert out[0]["fulfillment"] == "missed"


# ---------------- 其它 ----------------

def test_input_items_not_mutated():
    items = [_item(direction="buy", price=9.62)]
    snapshot = [dict(i) for i in items]
    check_fulfillment(items, {"001896.SZ": [_kline(low=9.5)]}, [])
    assert items == snapshot


def test_empty_items_returns_empty():
    assert check_fulfillment([], {}, []) == []


def test_transaction_without_price_still_counts_as_executed():
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.7)]},
                            [{"stock_code": "001896.SZ", "action": "buy", "shares": 100,
                              "price": None, "trade_date": "2026-10-22"}])
    assert out[0]["fulfillment"] == "executed"
