"""昨日预案 × 今日行情/流水 → 兑现状态(纯函数、零 IO)设计文档 §4.5"""
from __future__ import annotations

from app.services.fulfillment_checker import check_fulfillment, summarize_fulfillment


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


def test_no_data_when_target_day_has_no_kline():
    """目标日**没有该票的行情数据** → `no_data`,不是 `missed`。

    为什么这条最要紧:盘前/盘中 `fetch_klines` 缓存里往往还没有当天日 K,
    拿不到 K 线时判 `missed` 等于把「没拿到数据」永久写进复盘档案 —— 用无知冒充事实。
    """
    out = check_fulfillment([_item(direction="buy", price=9.62)], {}, [])
    assert out[0]["fulfillment"] == "no_data"
    assert "未判定" in out[0]["fulfillment_note"]


def test_no_data_when_buy_side_low_missing():
    """buy 项判定靠 low;low 缺失 → 无从判定 → no_data(不是 missed)"""
    items = [_item(direction="buy", price=9.62)]
    out = check_fulfillment(items, {"001896.SZ": [{"date": "2026-10-22",
                                                     "open": 9.7, "high": 10.5,
                                                     "low": None, "close": 10.0}]}, [])
    assert out[0]["fulfillment"] == "no_data"


def test_sell_side_only_needs_high():
    """sell 项判定靠 high;low 缺失但 high 在 → 正常判定(不因另一半缺而 no_data)"""
    items = [_item(kind="exit", direction="sell", price=12.03)]
    out = check_fulfillment(items, {"001896.SZ": [{"date": "2026-10-22",
                                                     "open": 11.0, "high": 12.5,
                                                     "low": None, "close": 12.2}]}, [])
    assert out[0]["fulfillment"] == "touched"


def test_no_data_not_counted_in_statistics():
    """`no_data` 不落进任何统计桶;且 verdict 不允许因为它说成「按计划执行」"""
    checked = check_fulfillment([_item(direction="buy", price=9.62)], {}, [])
    s = summarize_fulfillment(checked)
    assert s["no_data"] == 1
    # 「没判定」既不是触及也不是未触及,更不是不计入的 n_a
    assert (s["executed"], s["touched"], s["missed"], s["na"]) == (0, 0, 0, 0)
    assert s["verdict_label"] == "数据不足"
    assert s["verdict_level"] == "warn"
    # 有一笔真实执行也不能被 no_data 盖成「按计划执行」—— 没判定不是做对了
    with_exec = checked + [{**_item(direction="buy", price=9.62), "fulfillment": "executed"}]
    s2 = summarize_fulfillment(with_exec)
    assert s2["executed"] == 1
    assert s2["verdict_label"] == "数据不足"


def test_transaction_proves_execution_even_without_kline():
    """当日**有流水** → `executed`,不受日 K 缺失影响(流水自证执行)"""
    out = check_fulfillment([_item(direction="buy", price=9.62)], {},
                            [_txn(action="buy", price=9.62)])
    assert out[0]["fulfillment"] == "executed"


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
    # ⚠️ 脚手架数字必须是 low=9.5(<= 触发价 9.62 → 触及):写 9.7 会与
    # test_buy_missed_when_low_above_trigger(同 9.70 → missed)构成同输入两期望的互斥断言
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


def test_t_item_without_trigger_price_does_not_raise():
    """T 子项没有触发价时不能炸:price×容差 会 TypeError,必须先判 price is None"""
    items = [_item(kind="t_sell", direction="sell", price=None, label="做T减仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline()]}, [])
    assert out[0]["fulfillment"] == "n_a"


# ---------------- 流水归属规则(spec §4.5.2.1:一条流水只归一条预案) ----------------

def test_single_transaction_consumed_by_only_one_plan():
    """同票两条同向预案 + 一笔流水 → 只能有一条 executed,另一条不许白嫖"""
    items = [
        _item(kind="entry", direction="buy", price=9.62, label="建仓"),
        _item(kind="add", direction="buy", price=9.90, label="加仓"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.95)]},
                            [_txn(action="buy", price=9.62)])
    assert out[0]["fulfillment"] == "executed"
    assert out[1]["fulfillment"] == "missed"


def test_t_item_price_match_takes_priority_over_plain_plan():
    """T 子项按价格区间硬匹配 → 优先于同向的普通预案拿走流水"""
    items = [
        _item(kind="entry", direction="buy", price=9.60, label="建仓"),
        _item(kind="t_buyback", direction="buy", price=9.20, label="做T回补"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.7)]},
                            [_txn(action="buy", price=9.10)])
    by_kind = {i["item_kind"]: i for i in out}
    assert by_kind["t_buyback"]["fulfillment"] == "executed"
    assert by_kind["entry"]["fulfillment"] == "missed"


def test_multiple_candidates_pick_closest_price():
    """同票同向多笔流水 → 取成交价与触发价最接近的那笔"""
    items = [_item(kind="entry", direction="buy", price=8.60, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=9.2, low=8.0)]},
                            [_txn(action="buy", price=8.30),
                             _txn(action="buy", price=8.00)])
    assert out[0]["fulfillment"] == "executed"
    assert "8.30" in out[0]["fulfillment_note"]
    assert "8.00" not in out[0]["fulfillment_note"]


def test_transaction_without_price_fallback_disclosed():
    """成交价缺失 → 兜底消费并在 note 披露(不能装作知道是哪条预案)"""
    items = [_item(kind="entry", direction="buy", price=9.62, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.3)]},
                            [{"stock_code": "001896.SZ", "action": "buy",
                              "shares": 100, "price": None,
                              "trade_date": "2026-10-22"}])
    assert out[0]["fulfillment"] == "executed"
    assert "成交价缺失" in out[0]["fulfillment_note"]


def test_discipline_item_does_not_consume_transaction():
    """纪律类不参与流水归属 —— 同一笔操作可同时构成纪律违规与别的预案的执行。

    ⚠️ 必须用 **unlock**(direction=buy + 有触发价)而不是 do_not(direction=none):
    do_not 本来就会被方向过滤排除,删掉纪律守卫它照样绿 —— 那是假锁。
    """
    items = [
        _item(kind="unlock", direction="buy", price=12.50, label="解锁后建仓"),
        _item(kind="entry", direction="buy", price=9.62, label="建仓"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.3)]},
                            [_txn(action="buy", price=9.62)])
    by_kind = {i["item_kind"]: i for i in out}
    assert by_kind["unlock"]["fulfillment"] == "executed"
    assert "纪律问题" in by_kind["unlock"]["fulfillment_note"]
    assert by_kind["entry"]["fulfillment"] == "executed"


def test_t_buyback_ignores_other_stock_transaction():
    """T 回补的同票过滤:别的票的买入不能算本票的回补"""
    items = [_item(kind="t_buyback", direction="buy", price=9.20, label="做T回补")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.4)]},
                            [_txn(code="000807.SZ", action="buy", price=9.10)])
    assert out[0]["fulfillment"] == "missed"


def test_deviation_beyond_3pct_disclosed_in_note():
    """成交价与触发价偏离 >3% → note 里看得见(追高买/提前卖)"""
    items = [_item(kind="entry", direction="buy", price=10.00, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.5, low=9.9)]},
                            [_txn(action="buy", price=10.40)])
    assert out[0]["fulfillment"] == "executed"
    assert "不符" in out[0]["fulfillment_note"]


def test_deviation_within_3pct_not_disclosed():
    """偏离在 3% 以内 → 不披露(避免把按计划执行也标成不符)"""
    items = [_item(kind="entry", direction="buy", price=10.00, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.5, low=9.9)]},
                            [_txn(action="buy", price=10.20)])
    assert out[0]["fulfillment"] == "executed"
    assert "不符" not in out[0]["fulfillment_note"]


def test_deviation_exactly_3pct_not_disclosed():
    """恰好 3% 偏离 → 不披露(**浮点边界**,正是 `_EPS` 存在的原因)

    触发价 10.00 / 成交 10.30:数学上正好 3%,但浮点表示下
    `abs(10.30 - 10.00) = 0.30000000000000071` > `10.00 * 0.03 = 0.29999999999999999`。
    没有 `_EPS` 就会把它误判成「超过 3%」而披露 —— 恰好 3% 不该披露。
    """
    items = [_item(kind="entry", direction="buy", price=10.00, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.5, low=9.9)]},
                            [_txn(action="buy", price=10.30)])
    assert out[0]["fulfillment"] == "executed"
    assert "不符" not in out[0]["fulfillment_note"]


def test_t_buyback_boundary_price_within_epsilon_counts_as_executed():
    """浮点容差:买价 9.384 与下沿 9.2×1.02(=9.383999999999999) 差 1e-15 → 算按计划回补"""
    items = [_item(kind="t_buyback", direction="buy", price=9.20, label="做T回补")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.4)]},
                            [_txn(action="buy", price=9.384)])
    assert out[0]["fulfillment"] == "executed"


# ---------------- 统计口径 ----------------

def test_summarize_counts_every_state():
    """统计口径:四态各计各的(spec §4.5.4)"""
    items = [
        {**(_item(direction="buy", price=9.62)), "fulfillment": "executed"},
        {**(_item(direction="sell", price=12.0)), "fulfillment": "touched"},
        {**(_item(direction="buy", price=9.9)), "fulfillment": "missed"},
        {**(_item(kind="do_not", direction="none", price=None)), "fulfillment": "n_a"},
    ]
    s = summarize_fulfillment(items)
    assert s["total"] == 4
    assert s["executed"] == 1
    assert s["touched"] == 1
    assert s["missed"] == 1
    assert s["na"] == 1
    assert s["discipline"] == 0


def test_summarize_flags_discipline_as_most_severe():
    """纪律问题优先级最高(spec §4.5.4)"""
    items = [
        {**(_item(direction="buy", price=9.62)), "fulfillment": "executed",
         "fulfillment_note": "⚠️ 纪律问题:昨日标记别动/未解锁,今日仍有操作"},
        {**(_item(direction="sell", price=12.0)), "fulfillment": "touched"},
    ]
    s = summarize_fulfillment(items)
    assert s["discipline"] == 1
    assert s["verdict_label"] == "存在纪律问题"
    assert s["verdict_level"] == "danger"
