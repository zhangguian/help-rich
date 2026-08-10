"""scoring.py 纯函数单测(v2.6)

评分公式是选股模块的核心 — 所有边界 + 触发规则必须钉死,
避免后续调阈值时出现"阈值改了但某只股漏了"的回归。
"""
import pytest

from app.services.scoring import (
    ScoreBreakdown,
    StockFeatures,
    _score_main_inflow,
    _score_momentum,
    _score_sector_strength,
    _score_volume_ratio,
    apply_sector_cluster_bonus,
    passes_filter,
    score_stock,
)


# === _score_main_inflow ===

def test_main_inflow_below_threshold_zero():
    """净流入 < 1 亿 → 0 分"""
    score, chips = _score_main_inflow(0.5)
    assert score == 0.0
    assert chips == []


def test_main_inflow_at_threshold_base():
    """刚好 1 亿 → 基础 30 分"""
    score, chips = _score_main_inflow(1.0)
    assert score == 30.0
    assert "主力净流入≥1.0亿" in chips


def test_main_inflow_2yi_strong():
    """2 亿 → 30 + 2*5 = 40 分 + 强标记"""
    score, chips = _score_main_inflow(2.0)
    assert score == 40.0
    assert any("强" in c for c in chips)


def test_main_inflow_caps_at_max():
    """3 亿+ → 60 分封顶"""
    score, chips = _score_main_inflow(5.0)
    assert score == 60.0
    assert score <= 60.0


# === _score_volume_ratio ===

def test_volume_ratio_below_lowest_zero():
    """量比 < 1.5 → 0 分"""
    score, chips = _score_volume_ratio(1.2)
    assert score == 0.0
    assert chips == []


def test_volume_ratio_first_breakpoint():
    """量比 1.5 → 20 分"""
    score, chips = _score_volume_ratio(1.5)
    assert score == 20.0
    assert "量比≥1.5" in chips


def test_volume_ratio_all_breakpoints():
    """量比 3.5 → 20+10+10 = 40 封顶"""
    score, chips = _score_volume_ratio(3.5)
    assert score == 40.0
    assert "量比≥1.5" in chips
    assert "量比≥2.0" in chips
    assert "爆量" in chips[-1]


# === _score_momentum ===

def test_momentum_in_range_full():
    """涨幅 3~7% + 连涨 0 → 20 分"""
    score, chips = _score_momentum(5.0, 0)
    assert score == 20.0
    assert "涨幅3.0~7.0%" in chips


def test_momentum_high_chase_risk():
    """涨幅 >7% 折半"""
    score, chips = _score_momentum(9.0, 0)
    assert score == 10.0  # baseline 一半
    assert "折半" in chips[0]


def test_momentum_mild_up():
    """温和上涨 0~3%"""
    score, chips = _score_momentum(2.0, 0)
    assert score == 10.0
    assert "温和" in chips[0]


def test_momentum_consecutive_up_bonus():
    """连涨 ≥2 天 +10"""
    score, chips = _score_momentum(5.0, 3)
    assert score == 30.0  # 20 + 10
    assert any("连涨" in c for c in chips)


# === _score_sector_strength ===

def test_sector_top5_full():
    """Top5 → 15"""
    score, chips = _score_sector_strength(3)
    assert score == 15.0
    assert "Top3" in chips[0]


def test_sector_top6_20():
    """6~20 → 8"""
    score, chips = _score_sector_strength(15)
    assert score == 8.0
    assert "Top15" in chips[0]


def test_sector_below_20_zero():
    """20 开外 → 0"""
    score, chips = _score_sector_strength(50)
    assert score == 0.0


def test_sector_no_rank_zero():
    """未上榜 → 0"""
    score, chips = _score_sector_strength(None)
    assert score == 0.0


# === apply_sector_cluster_bonus ===

def test_cluster_bonus_two_in_top():
    """同板块 2 只入榜 +5"""
    bd = ScoreBreakdown(
        main_inflow_score=0, volume_ratio_score=0,
        momentum_score=0, sector_strength_score=10.0, total=10.0,
    )
    apply_sector_cluster_bonus(bd, n_in_top=2)
    assert bd.sector_strength_score == 15.0
    assert bd.total == 15.0
    assert any("入榜" in r for r in bd.triggered_rules)


def test_cluster_bonus_one_no_bonus():
    """同板块 1 只入榜无奖励"""
    bd = ScoreBreakdown(
        main_inflow_score=0, volume_ratio_score=0,
        momentum_score=0, sector_strength_score=10.0, total=10.0,
    )
    apply_sector_cluster_bonus(bd, n_in_top=1)
    assert bd.sector_strength_score == 10.0


# === score_stock(主入口) ===

def _features(**kw) -> StockFeatures:
    base = dict(
        stock_code="600519.SH", stock_name="贵州茅台",
        main_net_inflow_yi=0.0, volume_ratio=0.0,
        change_pct=0.0, turnover_yi=5.0,
        consecutive_up_days=0, sector=None, sector_inflow_rank=None,
    )
    base.update(kw)
    return StockFeatures(**base)


def test_score_stock_strong_all_factors():
    """全因子拉满(主力 3 亿 + 量比 3.5 + 涨幅 5% 连涨 3 天 + 板块 Top3)→ 135 分附近"""
    bd = score_stock(_features(
        main_net_inflow_yi=3.0, volume_ratio=3.5,
        change_pct=5.0, consecutive_up_days=3,
        sector="白酒", sector_inflow_rank=3,
    ))
    # 3 亿 → 30 + 2*10 = 50(从 1 亿起算,每 0.5 亿 +5; 2 个 0.5 = 10)
    assert bd.main_inflow_score == 50.0
    assert bd.volume_ratio_score == 40.0  # cap
    assert bd.momentum_score == 30.0      # 20 + 10
    assert bd.sector_strength_score == 15.0  # Top5
    assert bd.total == 135.0
    assert len(bd.triggered_rules) >= 6


def test_score_stock_zero():
    """零输入 → 0 分"""
    bd = score_stock(_features())
    assert bd.total == 0.0
    assert bd.triggered_rules == []


# === passes_filter ===

def test_filter_low_liquidity_reject():
    ok, reason = passes_filter(_features(turnover_yi=0.5), max_drop_pct_5d=-5.0)
    assert ok is False
    assert "流动性" in reason


def test_filter_drop_5d_reject():
    ok, reason = passes_filter(_features(turnover_yi=5.0), max_drop_pct_5d=-20.0)
    assert ok is False
    assert "避雷" in reason


def test_filter_pass():
    ok, reason = passes_filter(_features(turnover_yi=5.0), max_drop_pct_5d=-5.0)
    assert ok is True
    assert reason is None


# === build_reason(规则拼接的中文入选理由) ===

from app.services.scoring import build_reason


def test_build_reason_full_factors():
    """满因子 → 4 段拼接,长度 ≤ 100"""
    r = build_reason(_features(
        main_net_inflow_yi=2.5, volume_ratio=2.5,
        change_pct=5.2, consecutive_up_days=3,
        sector="白酒", sector_inflow_rank=3,
    ))
    assert "板块资金净流入" in r
    assert "主力强" in r
    assert "量比2.5" in r
    assert "放量" in r
    assert "涨幅5.2%" in r
    assert "连涨3天" in r
    assert "白酒板块资金Top3" in r
    assert len(r) <= 100
    assert r.endswith("。")


def test_build_reason_single_factor():
    """只有量比 → 仅写量比段"""
    r = build_reason(_features(volume_ratio=2.0))
    assert "量比2.0" in r
    assert "板块资金" not in r
    assert "涨幅" not in r


def test_build_reason_high_price_warning():
    """涨幅 >7% → 含"高位,折半追高风险"提示"""
    r = build_reason(_features(change_pct=9.5))
    assert "高位" in r
    assert "折半" in r
    assert "追高风险" in r


def test_build_reason_sector_top5():
    """板块 Top5 → 含板块名 + 排名"""
    r = build_reason(_features(sector="半导体", sector_inflow_rank=3))
    assert "半导体板块资金Top3" in r


def test_build_reason_cluster_bonus_from_bd():
    """bd.triggered_rules 含「同板块 N 只入榜(+N)」→ 加入理由"""
    bd = ScoreBreakdown(
        main_inflow_score=0, volume_ratio_score=0,
        momentum_score=0, sector_strength_score=10.0, total=10.0,
        triggered_rules=["同板块2只入榜(+5)"],
    )
    r = build_reason(_features(sector="半导体", sector_inflow_rank=5), bd=bd)
    assert "同板块2只入榜(+5)" in r


def test_build_reason_zero_factors():
    """零因子 → 返「无明显入选信号」"""
    r = build_reason(_features())
    assert r == "无明显入选信号(评分边缘)。"


def test_build_reason_length_cap():
    """极端输入 → 长度截断到 ≤ 100"""
    # 强行构造大 sector 名触发截断
    r = build_reason(_features(
        main_net_inflow_yi=5.0, volume_ratio=5.0,
        change_pct=12.0, consecutive_up_days=10,
        sector="非常非常长的行业名称板块资金Top1", sector_inflow_rank=1,
    ))
    assert len(r) <= 100
    assert r.endswith("。") or r.endswith("...")


def test_build_reason_negative_change_warning():
    """回调涨幅 → 含「注意回调」"""
    r = build_reason(_features(change_pct=-2.5))
    assert "注意回调" in r