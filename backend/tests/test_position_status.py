"""持仓盈亏状态判定(共享口径)的契约测试

`app/services/position_status.py` 是全项目**唯一**的持仓盈亏判定口径
(决策卡 / 作战计划 / 复盘共用)。2026-10-22 阶段 9 收尾回填 (a):
把 docstring 的契约文字从「`shares` 须为 int」改成「`shares` 须为**数值**」,
本文件就是这条契约文字的**实证**(别让文档与实现漂移)。

**为什么单独建文件**:原先只有 `test_decision_api.py` / `test_stock_advice.py`
经 `api/stock.py` 的别名间接覆盖本模块,**没有直接针对服务层契约的用例**。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.position_status import (
    kline_fallback_price,
    resolve_position_status,
    sanitize_current_price,
)


class _Pos:
    """最小持仓对象(只需 .shares / .avg_cost 两个属性)"""

    def __init__(self, shares, avg_cost):
        self.shares = shares
        self.avg_cost = avg_cost


# ---------------- (a) shares 契约:须为**数值**,不是"须为 int" ----------------

@pytest.mark.parametrize("shares", [100, 100.0, Decimal("100"), True])
def test_shares_accepts_any_numeric_type(shares):
    """(a) int / float / Decimal / bool 都是数值 → 判定成立,不抛异常

    契约文字原写「`shares` 须为 int」,但实测 float / bool / Decimal 都能过
    (判定只做 `shares <= 0` 比较),只有字符串才 TypeError。
    """
    status, pct = resolve_position_status(_Pos(shares, "10.0"), "11.0")
    assert status == "profit"
    assert pct == pytest.approx(0.1)


def test_shares_as_str_raises_type_error():
    """(a) 字符串仍抛 TypeError(比较运算不成立)—— 这就是「须为数值」的边界"""
    with pytest.raises(TypeError):
        resolve_position_status(_Pos("100", "10.0"), "11.0")


def test_position_as_dict_raises_attribute_error():
    """契约要求传**属性对象**,不接 dict(否则 AttributeError)"""
    with pytest.raises(AttributeError):
        resolve_position_status({"shares": 100, "avg_cost": "10.0"}, "11.0")


# ---------------- 判定口径(§5) ----------------

def test_zero_shares_is_empty():
    assert resolve_position_status(_Pos(0, "10.0"), "11.0") == ("empty", None)


def test_none_position_is_empty():
    assert resolve_position_status(None, "11.0") == ("empty", None)


def test_breakeven_is_profit_not_empty():
    """持平归 profit —— 归 empty 会让决策卡给出「首仓 30%」这种误导"""
    status, pct = resolve_position_status(_Pos(100, "10.0"), "10.0")
    assert status == "profit"
    assert pct == pytest.approx(0.0)


def test_fallback_price_used_when_quote_missing():
    """报价缺失 → 用 K 线最新收盘价兜底(§5 effective_price)"""
    status, pct = resolve_position_status(_Pos(100, "10.0"), None, "11.0")
    assert status == "profit"
    assert pct == pytest.approx(0.1)


def test_no_price_at_all_is_loss_not_empty():
    """有持仓但连兜底价都没有 → 保守取 loss,绝不给 empty"""
    assert resolve_position_status(_Pos(100, "10.0"), None, None) == ("loss", None)


def test_avg_cost_accepts_numeric_string():
    """`avg_cost` 允许数字字符串(会被 float() 正常转换,不抛异常)"""
    status, pct = resolve_position_status(_Pos(100, "10.0"), "11.0")
    assert status == "profit"


# ---------------- 兜底价与报价校验 ----------------

def test_kline_fallback_price_returns_last_close():
    assert kline_fallback_price([{"close": "10.1"}, {"close": "10.2"}]) == "10.2"


def test_kline_fallback_price_none_on_empty():
    assert kline_fallback_price([]) is None
    assert kline_fallback_price(None) is None


class _Quote:
    def __init__(self, price, ts="2026-10-21T15:00:00"):
        self.current_price = price
        self.timestamp = None
        self._ts = ts


def test_sanitize_current_price_degrades_on_big_deviation():
    """报价与 K 线收盘偏离 > 10% → 降级为 None(数据源异常)"""
    q = _Quote("100")
    assert sanitize_current_price(q, [{"close": "50.0"}]) == (None, None)


def test_sanitize_current_price_keeps_reasonable_price():
    q = _Quote("11.0")
    assert sanitize_current_price(q, [{"close": "10.2"}])[0] == "11.0"


def test_sanitize_current_price_none_when_quote_missing():
    assert sanitize_current_price(None, [{"close": "10.2"}]) == (None, None)
