"""盘中信号判定层测试(纯函数,零 IO)。

覆盖:
- 急速拉升/下跌:样本不足 → None;恰好等于阈值 → 触发;窗口太短 → None
- 突破:阈值边界;迟滞(回落 0.5% 内不重复触发,跌破迟滞带才解除)
- 到价:≥ / ≤ 边界;缺价位 → 不出信号
- 触发价抽取:只取数值;不适合做T → 不产出价位(不编数字)
"""
from __future__ import annotations

from app.modules.signal.engine import (
    TriggerLevel,
    detect_breakout,
    detect_level_hits,
    detect_velocity,
    extract_trigger_levels,
    extract_unsuitable_notes,
)


def _window(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return points


# ============================================================
# 急速拉升 / 下跌
# ============================================================


def test_velocity_insufficient_samples_returns_none() -> None:
    """样本不足(< 5 帧)→ None,不猜。"""
    window = _window([(0.0, 10.0), (2.0, 10.1), (4.0, 10.5)])
    assert detect_velocity(
        "002185.SZ", "x", window, now_ts=4.0, window_sec=60, velocity_pct=1.5
    ) is None


def test_velocity_span_too_short_returns_none() -> None:
    """窗口跨度不足 60% 目标时长 → None(样本太稀,涨跌幅不可信)。"""
    window = _window([(0.0, 10.0), (2.0, 10.1), (4.0, 10.2), (6.0, 10.3), (8.0, 10.4)])
    assert detect_velocity(
        "002185.SZ", "x", window, now_ts=8.0, window_sec=60, velocity_pct=1.5
    ) is None


def test_velocity_up_at_threshold_fires() -> None:
    """恰好等于阈值 → 触发(边界含)。"""
    window = _window(
        [(i * 2.0, 10.0 * (1 + 0.015 * i / 30)) for i in range(31)]
    )
    # 首尾价差刚好 1.5%
    window = _window([(0.0, 10.0)] + [(i * 2.0, 10.0 + 0.05 * i) for i in range(31)])
    signal = detect_velocity(
        "002185.SZ", "测试股", window, now_ts=60.0, window_sec=60, velocity_pct=1.5
    )
    assert signal is not None
    assert signal.kind == "velocity_up"
    assert signal.value is not None and signal.value >= 1.5
    assert "急速拉升" in signal.title


def test_velocity_below_threshold_returns_none() -> None:
    # 60 秒内 10.00 → 10.12(+1.2%),低于 1.5% 阈值
    window = _window([(0.0, 10.0)] + [(i * 2.0, 10.0 + 0.004 * i) for i in range(31)])
    assert detect_velocity(
        "002185.SZ", "x", window, now_ts=60.0, window_sec=60, velocity_pct=1.5
    ) is None


def test_velocity_down_kind() -> None:
    window = _window([(0.0, 10.0)] + [(i * 2.0, 10.0 - 0.05 * i) for i in range(31)])
    signal = detect_velocity(
        "002185.SZ", "x", window, now_ts=60.0, window_sec=60, velocity_pct=1.5
    )
    assert signal is not None
    assert signal.kind == "velocity_down"
    assert signal.value is not None and signal.value < 0


# ============================================================
# 涨幅突破 / 跌幅突破
# ============================================================


def test_breakout_up_at_threshold_fires() -> None:
    signal, state = detect_breakout(
        "002185.SZ", "x", 10.5, 10.0, up_pct=5.0, down_pct=-5.0, state=None
    )
    assert signal is not None
    assert signal.kind == "breakout_up"
    assert state == "up"


def test_breakout_missing_prev_close_returns_none() -> None:
    """缺昨收 → None(不编涨跌幅)。"""
    signal, state = detect_breakout(
        "002185.SZ", "x", 10.5, None, up_pct=5.0, down_pct=-5.0, state=None
    )
    assert signal is None
    assert state is None


def test_breakout_hysteresis_no_refire_within_band() -> None:
    """已达突破态后,回落到 阈值-0.5% 以内(+4.6% ≥ 4.5%)→ 不重复触发,状态保持。"""
    signal, state = detect_breakout(
        "002185.SZ", "x", 10.46, 10.0, up_pct=5.0, down_pct=-5.0, state="up"
    )
    assert signal is None
    assert state == "up"


def test_breakout_state_cleared_after_hysteresis_band() -> None:
    """跌破迟滞带 → 解除"已达突破态",下次重新突破可以再提醒。"""
    signal, state = detect_breakout(
        "002185.SZ", "x", 10.3, 10.0, up_pct=5.0, down_pct=-5.0, state="up"
    )
    assert signal is None
    assert state is None


def test_breakout_down_and_back() -> None:
    signal, state = detect_breakout(
        "002185.SZ", "x", 9.4, 10.0, up_pct=5.0, down_pct=-5.0, state=None
    )
    assert signal is not None
    assert signal.kind == "breakout_down"
    assert state == "down"


# ============================================================
# 到价类
# ============================================================


def test_level_hit_sell_boundary_inclusive() -> None:
    """现价 ≥ 触发价 → 卖点信号(边界含)。"""
    levels = [TriggerLevel(kind="t_sell_point", level=12.0, label="T 卖出点")]
    hits = detect_level_hits("002185.SZ", "x", 12.0, levels)
    assert len(hits) == 1
    assert hits[0].kind == "t_sell_point"
    assert hits[0].level == 12.0
    assert hits[0].dedup_by_level is True


def test_level_hit_buy_boundary_inclusive() -> None:
    levels = [TriggerLevel(kind="t_buyback_point", level=11.0, label="T 买回点")]
    hits = detect_level_hits("002185.SZ", "x", 11.0, levels)
    assert len(hits) == 1
    assert hits[0].kind == "t_buyback_point"


def test_level_hit_not_reached_returns_empty() -> None:
    levels = [TriggerLevel(kind="t_sell_point", level=12.0, label="T 卖出点")]
    assert detect_level_hits("002185.SZ", "x", 11.9, levels) == []


def test_level_hit_missing_price_returns_empty() -> None:
    levels = [TriggerLevel(kind="t_sell_point", level=12.0, label="T 卖出点")]
    assert detect_level_hits("002185.SZ", "x", None, levels) == []


def test_same_level_same_fingerprint_different_level_differs() -> None:
    """同价位同指纹(当日只提醒一次);不同价位不同指纹。"""
    a = detect_level_hits(
        "002185.SZ", "x", 12.0, [TriggerLevel(kind="t_sell_point", level=12.0, label="L")]
    )[0]
    b = detect_level_hits(
        "002185.SZ", "x", 12.01, [TriggerLevel(kind="t_sell_point", level=12.004, label="L")]
    )[0]
    c = detect_level_hits(
        "002185.SZ", "x", 12.6, [TriggerLevel(kind="t_sell_point", level=12.5, label="L")]
    )[0]
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != c.fingerprint


# ============================================================
# 触发价抽取(决策卡 → 触发线)
# ============================================================


def test_extract_levels_from_t_plan() -> None:
    decision = {
        "t_plan": {
            "suitable": True,
            "t_high": 12.5,
            "t_low": 11.0,
            "sell_trigger": "上冲到 12.50",
            "buyback_trigger": "回落到 11.00",
        }
    }
    levels = extract_trigger_levels(decision)
    kinds = {lv.kind for lv in levels}
    assert kinds == {"t_sell_point", "t_buyback_point"}
    sell = next(lv for lv in levels if lv.kind == "t_sell_point")
    assert sell.level == 12.5
    assert sell.condition == "上冲到 12.50"


def test_extract_levels_skips_unsuitable_t_plan() -> None:
    """不适合做T → 不产出价位(不替用户编一个价)。"""
    decision = {
        "t_plan": {"suitable": False, "t_high": 12.5, "t_low": 11.0, "reason": "波动太小"}
    }
    assert extract_trigger_levels(decision) == []
    notes = extract_unsuitable_notes(decision)
    assert any("波动太小" in n for n in notes)


def test_extract_levels_from_grid_plan() -> None:
    decision = {
        "grid_plan": {"suitable": True, "range_low": 11.2, "range_high": 12.8, "reason": "区间震荡"}
    }
    kinds = {lv.kind for lv in extract_trigger_levels(decision)}
    assert kinds == {"buy_point", "grid_sell_point"}


def test_extract_levels_from_armed_add_action() -> None:
    decision = {
        "actions": [
            {
                "kind": "add",
                "label": "回踩加仓",
                "condition": "回落到 10.80",
                "price": 10.8,
                "basis": ["均线支撑"],
                "status": "armed",
            },
            {"kind": "entry", "label": "建仓", "price": 10.0, "status": "armed"},
            {"kind": "add", "label": "现在加仓", "price": 11.5, "status": "now"},
        ]
    }
    levels = extract_trigger_levels(decision)
    assert len(levels) == 1
    assert levels[0].kind == "buy_point"
    assert levels[0].level == 10.8
    assert levels[0].basis == "均线支撑"


def test_extract_levels_from_bad_decision_returns_empty() -> None:
    assert extract_trigger_levels(None) == []
    assert extract_trigger_levels({"t_plan": "not-a-dict"}) == []
