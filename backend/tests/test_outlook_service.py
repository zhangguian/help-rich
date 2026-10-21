"""明日市场预期规则(纯函数、零 IO、零 LLM)

设计文档 §4.3
"""
from __future__ import annotations

import pytest

from app.services.outlook_service import build_outlook


def _klines(closes: list[float], volumes: list[float] | None = None,
            highs: list[float] | None = None, lows: list[float] | None = None) -> list[dict]:
    """构造升序日K;volumes/highs/lows 缺省时用 close 派生"""
    n = len(closes)
    vols = volumes if volumes is not None else [100.0] * n
    his = highs if highs is not None else list(closes)
    los = lows if lows is not None else list(closes)
    return [
        {
            "date": f"2026-01-{i + 1:02d}",
            "open": c, "high": his[i], "low": los[i], "close": c, "volume": int(vols[i]),
        }
        for i, c in enumerate(closes)
    ]


def _dim(outlook: dict, key: str) -> dict:
    return next(d for d in outlook["dims"] if d["key"] == key)


# ---------------- 量能维度 ----------------

def test_volume_bull_when_today_110pct_of_avg5():
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]  # 今日 110,前5日均 100
    out = build_outlook(_klines(closes, volumes), None, None)
    d = _dim(out, "volume")
    assert d["score"] == 1
    assert d["state"] == "bull"


def test_volume_bear_when_today_90pct_of_avg5():
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 90.0]
    out = build_outlook(_klines(closes, volumes), None, None)
    assert _dim(out, "volume")["score"] == -1


def test_volume_neutral_between_90_and_110():
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 105.0]
    out = build_outlook(_klines(closes, volumes), None, None)
    assert _dim(out, "volume")["score"] == 0


def test_volume_missing_when_klines_lt_6():
    out = build_outlook(_klines([10.0] * 3), None, None)
    assert _dim(out, "volume")["state"] == "missing"
    assert _dim(out, "volume")["score"] == 0


# ---------------- 涨跌家数维度 ----------------

def test_sentiment_bull_when_up_ratio_ge_60pct():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 60, "down_total": 40}, None)
    assert _dim(out, "sentiment")["score"] == 1


def test_sentiment_bear_when_up_ratio_le_40pct():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 30, "down_total": 70}, None)
    assert _dim(out, "sentiment")["score"] == -1


def test_sentiment_neutral_between_40_and_60():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 50, "down_total": 50}, None)
    assert _dim(out, "sentiment")["score"] == 0


def test_sentiment_missing_when_zero_total():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 0, "down_total": 0}, None)
    assert _dim(out, "sentiment")["state"] == "missing"


def test_sentiment_missing_when_none():
    out = build_outlook(_klines([10.0] * 30), None, None)
    assert _dim(out, "sentiment")["state"] == "missing"


# ---------------- 均线维度 ----------------

def test_ma_bull_when_close_above_ma5_above_ma10():
    closes = [10.0] * 10 + [12.0]
    out = build_outlook(_klines(closes), None, None)
    assert _dim(out, "ma")["score"] == 1


def test_ma_bear_when_close_below_ma5_below_ma10():
    closes = [12.0] * 10 + [10.0]
    out = build_outlook(_klines(closes), None, None)
    assert _dim(out, "ma")["score"] == -1


def test_ma_missing_when_klines_lt_11():
    out = build_outlook(_klines([10.0] * 10), None, None)
    assert _dim(out, "ma")["state"] == "missing"


# ---------------- 板块资金维度 ----------------

def test_flow_bull_when_net_total_positive():
    """净流入总额为正(+3.2 - 1.0 = +2.2)→ 偏多"""
    flows = [{"name": "电子元件", "netamount_yi": 3.2}, {"name": "煤炭", "netamount_yi": -1.0}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    assert _dim(out, "flow")["score"] == 1


def test_flow_bear_when_all_negative():
    flows = [{"name": "煤炭", "netamount_yi": -1.0}, {"name": "钢铁", "netamount_yi": -2.0}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    assert _dim(out, "flow")["score"] == -1


def test_flow_neutral_when_mixed():
    """净流入与净流出抵消(+1.0 - 1.0 = 0)→ 中性"""
    flows = [{"name": "电子元件", "netamount_yi": 1.0}, {"name": "煤炭", "netamount_yi": -1.0}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    assert _dim(out, "flow")["score"] == 0


def test_flow_missing_when_empty_list():
    out = build_outlook(_klines([10.0] * 30), None, [])
    assert _dim(out, "flow")["state"] == "missing"


# ---------------- 结论合成 ----------------

def test_unknown_when_all_dims_missing():
    out = build_outlook([], None, None)
    assert out["stance"] == "unknown"
    assert out["dims_effective"] == 0
    assert out["degraded"] is True


def test_bullish_requires_at_least_2_effective_dims():
    """只靠单一维度不得判偏多(过度自信)"""
    # 只有量能 +1,其余全缺
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]
    out = build_outlook(_klines(closes, volumes), None, None)
    assert out["dims_effective"] == 1
    assert out["stance"] == "neutral"


def test_bullish_when_2_dims_and_score_ge_1():
    # 10 根 K:均线维度因不足 11 根而 missing,有效维度恰为 2(量能 + 涨跌家数)
    closes = [10.0] * 10
    volumes = [100.0] * 9 + [110.0]
    out = build_outlook(_klines(closes, volumes), {"up_total": 60, "down_total": 40}, None)
    assert out["dims_effective"] == 2
    assert out["score"] == 2
    assert out["stance"] == "bullish"


def test_bearish_allows_single_dim():
    """偏空判定不对称:单条强证据即可成立(风险侧保守优于激进)"""
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 90.0]
    out = build_outlook(_klines(closes, volumes), None, None)
    assert out["dims_effective"] == 1
    assert out["stance"] == "bearish"


def test_stance_label_mapping():
    out = build_outlook([], None, None)
    assert out["stance_label"] == "数据不足"


# ---------------- 关键位 ----------------

def test_support_only_below_close():
    closes = [10.0] * 10 + [12.0]
    highs = [11.0] * 10 + [13.0]
    lows = [9.0] * 10 + [11.5]
    out = build_outlook(_klines(closes, highs=highs, lows=lows), None, None)
    kl = out["key_levels"]
    assert 12.0 not in kl["support"]          # 收盘价本身不作支撑
    assert all(v < 12.0 for v in kl["support"])
    assert all(v > 12.0 for v in kl["resistance"])


def test_key_levels_include_close_and_ma():
    out = build_outlook(_klines([10.0] * 30), None, None)
    kl = out["key_levels"]
    assert kl["close"] == 10.0
    assert kl["ma5"] == 10.0
    assert kl["ma10"] == 10.0
    assert kl["ma20"] == 10.0


def test_disclaimer_always_present_and_says_not_prediction():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 60, "down_total": 40}, None)
    assert "非预测" in out["disclaimer"]


def test_dims_always_four_items():
    out = build_outlook(_klines([10.0] * 30), None, None)
    assert len(out["dims"]) == 4
    assert {d["key"] for d in out["dims"]} == {"volume", "sentiment", "ma", "flow"}