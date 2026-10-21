"""明日市场预期规则(纯函数、零 IO、零 LLM)

设计文档 §4.3
"""
from __future__ import annotations

import pytest

from app.services.outlook_service import build_market_snapshot, build_outlook


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


def test_flow_neutral_when_float_sum_is_zero():
    """浮点零和:[38.6, -12.4, -26.2] 的和是 3.55e-15 而非精确 0,必须归一到 0 → 中性"""
    flows = [{"name": "A", "netamount_yi": 38.6}, {"name": "B", "netamount_yi": -12.4},
             {"name": "C", "netamount_yi": -26.2}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    d = _dim(out, "flow")
    assert d["score"] == 0
    assert d["state"] == "flat"


def test_flow_missing_when_all_netamount_are_none():
    """全部板块净额为 None = 根本没有板块资金数据 → missing(不能算 flat)"""
    flows = [{"name": "A", "netamount_yi": None}, {"name": "B", "netamount_yi": None}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    d = _dim(out, "flow")
    assert d["state"] == "missing"
    assert d["score"] == 0


def test_flow_bear_detail_has_no_double_negative():
    """净流出文案用绝对值,不出现「净流出合计 -3.00 亿」这种双重否定"""
    flows = [{"name": "煤炭", "netamount_yi": -1.0}, {"name": "钢铁", "netamount_yi": -2.0}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    detail = _dim(out, "flow")["detail"]
    assert "-3.00" not in detail
    assert "3.00" in detail


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


# ---------------- 指数实况快照(spec §4.7 review.market) ----------------

def _snap_klines(rows: list[dict]) -> list[dict]:
    """按日期造最小日K;rows = [{date, close, amount?}]"""
    return [{"date": r["date"], "close": r["close"], "amount": r.get("amount")} for r in rows]


def test_market_snapshot_returns_target_day_close():
    """取目标日收盘,并用**前一根**收盘算涨跌幅"""
    ks = _snap_klines([
        {"date": "2026-10-20", "close": 3000.0},
        {"date": "2026-10-21", "close": 3030.0, "amount": 4.2e9},
    ])
    snap = build_market_snapshot(ks, "2026-10-21")
    assert snap["index_close"] == 3030.0
    assert snap["change_pct"] == 1.0          # (3030-3000)/3000
    assert snap["volume_note"] == "成交额 42 亿"


def test_market_snapshot_returns_none_when_target_day_missing():
    """目标日无 K 线(盘前/停牌/节假日)→ None,不编造"""
    ks = _snap_klines([{"date": "2026-10-20", "close": 3000.0}])
    assert build_market_snapshot(ks, "2026-10-21") is None
    assert build_market_snapshot([], "2026-10-21") is None
    assert build_market_snapshot(None, "2026-10-21") is None


def test_market_snapshot_volume_note_none_when_amount_missing():
    """没有成交额字段 → volume_note 如实留空(不许写「成交额 0 亿」)"""
    ks = _snap_klines([{"date": "2026-10-21", "close": 3030.0}])
    snap = build_market_snapshot(ks, "2026-10-21")
    assert snap["volume_note"] is None
    assert snap["index_close"] == 3030.0


def test_market_snapshot_handles_string_amount():
    """amount 是**字符串**(见 K 线数据契约)→ 正确转 float,别炸也别当 0"""
    ks = [{"date": "2026-10-21", "close": "3030.0", "amount": "35550000000"}]
    snap = build_market_snapshot(ks, "2026-10-21")
    assert snap["volume_note"] == "成交额 356 亿"
    assert snap["change_pct"] is None         # 没有前收 → 不编造涨跌幅


# ---------------- 回填项 (d)(e)(2026-10-22 阶段 9 收尾) ----------------

def test_flow_missing_when_netamount_is_inf():
    """(d) ±inf 必须被 _f 滤掉

    修复前 `_f` 只滤 NaN(`f == f`),±inf 会通过 → `[inf, -inf]` 求和得 NaN →
    落进 flat 档对外宣称「多空抵消,无明确主攻方向」——
    **数据已损坏却宣称中性**,属误导性结论。
    """
    flows = [{"name": "A", "netamount_yi": float("inf")},
             {"name": "B", "netamount_yi": float("-inf")}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    d = _dim(out, "flow")
    assert d["state"] == "missing"
    assert d["score"] == 0
    assert "抵消" not in d["detail"]          # 不许宣称中性


def test_flow_ignores_inf_entries_and_keeps_valid_ones():
    """(d) inf 条目被丢弃,其余有效条目照常参与合计(不许整档作废)"""
    flows = [{"name": "A", "netamount_yi": float("inf")},
             {"name": "B", "netamount_yi": 2.0}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    d = _dim(out, "flow")
    assert d["score"] == 1
    assert d["state"] == "bull"
    assert "2.00 亿" in d["detail"]


def test_flow_detail_uses_wan_when_total_below_0_01_yi():
    """(e) 净额 0.004 亿(40 万)→ 改用「万元」表述,不许出现「0.00 亿」

    真实 `netamount_yi` 是新浪原始元/1e8 的全精度 float,残差可达几十万元级;
    2 位小数会把它渲染成「0.00 亿」——把「几乎没有资金流」说成「零」。
    """
    flows = [{"name": "A", "netamount_yi": 0.004}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    detail = _dim(out, "flow")["detail"]
    assert "0.00 亿" not in detail
    assert "40 万元" in detail


def test_flow_detail_uses_wan_for_main_sector_too():
    """(e) 主攻板块那一处也走同一个 helper(同族漏网:total 与 top[0] 两个数)"""
    flows = [{"name": "电子元件", "netamount_yi": 0.004}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    detail = _dim(out, "flow")["detail"]
    assert detail.count("0.00 亿") == 0
    assert detail.count("40 万元") == 2      # 合计 + 主攻


def test_market_snapshot_volume_note_not_zero_for_50m():
    """(e) 成交额 5000 万不得渲染成「成交额 0 亿」(数值直接消失)"""
    ks = [{"date": "2026-10-21", "close": "3030.0", "amount": 5e7}]
    snap = build_market_snapshot(ks, "2026-10-21")
    assert snap["volume_note"] == "成交额 0.50 亿"


def test_market_snapshot_volume_note_none_when_amount_is_inf():
    """(d) amount 为 ±inf → 如实留空,不许渲染出「成交额 inf 亿」"""
    ks = [{"date": "2026-10-21", "close": "3030.0", "amount": float("inf")}]
    snap = build_market_snapshot(ks, "2026-10-21")
    assert snap["volume_note"] is None
    assert snap["index_close"] == 3030.0
