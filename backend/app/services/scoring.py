"""盘后选股评分公式(v2.6)

纯函数:输入候选股因子 → 输出综合分 + 各项明细 + 触发规则 chip。
无 IO,便于单测 + 回测。

设计原则:
- 每个因子有边界(0..max),便于阈值调参与回溯
- 触发条件以 chip 形式落库,前端可解释"为什么被选中"
- 资金驱动主线:主力净流入 + 量比 + 涨幅 + 板块强度
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.config import (
    SCREENER_CHANGE_PCT_RANGE,
    SCREENER_CONSECUTIVE_UP_BONUS,
    SCREENER_MAIN_INFLOW_MAX,
    SCREENER_MAIN_INFLOW_POINTS_STEP,
    SCREENER_MAIN_INFLOW_STEP_YI,
    SCREENER_MAIN_INFLOW_THRESHOLD_YI,
    SCREENER_MOMENTUM_BASELINE,
    SCREENER_MOMENTUM_MAX,
    SCREENER_SECTOR_CLUSTER_BONUS,
    SCREENER_SECTOR_MAX,
    SCREENER_SECTOR_TOP5_POINTS,
    SCREENER_SECTOR_TOP6_20_POINTS,
    SCREENER_VOLUME_RATIO_BREAKPOINTS,
    SCREENER_VOLUME_RATIO_MAX,
)

logger = logging.getLogger(__name__)

# 综合分上限(各因子 max 之和;写在常量便于改)
SCREENER_MAX_SCORE = (
    SCREENER_MAIN_INFLOW_MAX
    + SCREENER_VOLUME_RATIO_MAX
    + SCREENER_MOMENTUM_MAX
    + SCREENER_SECTOR_MAX
)


@dataclass
class StockFeatures:
    """单只候选股评分输入"""

    stock_code: str
    stock_name: str
    # 板块主力净流入(亿元)— 来自 sector_fund_flow 排行
    main_net_inflow_yi: float = 0.0
    # 量比(今日量 / 近 5 日均量)— K 线计算
    volume_ratio: float = 0.0
    # 当日涨跌幅(%)
    change_pct: float = 0.0
    # 成交额(亿元)
    turnover_yi: float = 0.0
    # 连涨天数(收盘价连续上涨天数)
    consecutive_up_days: int = 0
    # 所属行业(可选,用于板块强度)
    sector: str | None = None
    # 该股所在板块在板块资金榜的排名(1-based,None 表示未上榜)
    sector_inflow_rank: int | None = None


@dataclass
class ScoreBreakdown:
    """评分明细输出"""

    main_inflow_score: float
    volume_ratio_score: float
    momentum_score: float
    sector_strength_score: float
    total: float
    triggered_rules: list[str] = field(default_factory=list)


def _score_main_inflow(yi: float) -> tuple[float, list[str]]:
    """主力净流入 → 分(0..60)+ 触发规则"""
    chips: list[str] = []
    if yi < SCREENER_MAIN_INFLOW_THRESHOLD_YI:
        return 0.0, chips
    base = 30  # 阈值线上基础分
    extra_steps = (yi - SCREENER_MAIN_INFLOW_THRESHOLD_YI) / SCREENER_MAIN_INFLOW_STEP_YI
    extra = int(extra_steps) * SCREENER_MAIN_INFLOW_POINTS_STEP
    score = min(base + extra, SCREENER_MAIN_INFLOW_MAX)
    chips.append(f"主力净流入≥{SCREENER_MAIN_INFLOW_THRESHOLD_YI}亿")
    if yi >= 2.0:
        chips.append("主力净流入≥2亿(强)")
    return float(score), chips


def _score_volume_ratio(ratio: float) -> tuple[float, list[str]]:
    """量比 → 分(0..40)+ 触发规则"""
    chips: list[str] = []
    bp1, bp2, bp3 = SCREENER_VOLUME_RATIO_BREAKPOINTS
    score = 0.0
    if ratio >= bp1:
        score += 20
        chips.append(f"量比≥{bp1}")
    if ratio >= bp2:
        score += 10
        chips.append(f"量比≥{bp2}")
    if ratio >= bp3:
        score += 10
        chips.append(f"量比≥{bp3}(爆量)")
    return min(score, SCREENER_VOLUME_RATIO_MAX), chips


def _score_momentum(change_pct: float, consecutive_up: int) -> tuple[float, list[str]]:
    """涨幅 + 连涨 → 分(0..30)+ 触发规则"""
    chips: list[str] = []
    low, high = SCREENER_CHANGE_PCT_RANGE
    score = 0.0
    if low <= change_pct <= high:
        score += SCREENER_MOMENTUM_BASELINE
        chips.append(f"涨幅{low}~{high}%")
    elif change_pct > high:
        # 涨幅过大有追高风险,只给一半
        score += SCREENER_MOMENTUM_BASELINE / 2
        chips.append(f"涨幅>{high}%(高位,折半)")
    elif 0 < change_pct < low:
        # 涨幅 < 3% 也有"温和上涨"奖励,鼓励真正启动的
        score += SCREENER_MOMENTUM_BASELINE / 2
        chips.append(f"涨幅0~{low}%(温和)")
    if consecutive_up >= 2:
        score += SCREENER_CONSECUTIVE_UP_BONUS
        chips.append(f"连涨{consecutive_up}天")
    return min(score, SCREENER_MOMENTUM_MAX), chips


def _score_sector_strength(rank: int | None) -> tuple[float, list[str]]:
    """板块资金榜排名 → 分(0..25)+ 触发规则"""
    chips: list[str] = []
    if rank is None or rank <= 0:
        return 0.0, chips
    if rank <= 5:
        score = float(SCREENER_SECTOR_TOP5_POINTS)
        chips.append(f"板块资金榜 Top{rank}")
    elif rank <= 20:
        score = float(SCREENER_SECTOR_TOP6_20_POINTS)
        chips.append(f"板块资金榜 Top{rank}")
    else:
        score = 0.0
    return min(score, SCREENER_SECTOR_MAX), chips


def apply_sector_cluster_bonus(breakdown: ScoreBreakdown, n_in_top: int) -> None:
    """同板块多只入榜 → +5(在 service 层批量调用)

    n_in_top: 该板块在 Top N 候选里出现的次数(>=2 触发)
    同时刷新 total。
    """
    if n_in_top >= 2:
        delta = min(
            SCREENER_SECTOR_CLUSTER_BONUS,
            SCREENER_SECTOR_MAX - breakdown.sector_strength_score,
        )
        if delta > 0:
            breakdown.sector_strength_score += delta
            breakdown.total += delta
            breakdown.triggered_rules.append(f"同板块{n_in_top}只入榜(+{delta})")


def score_stock(features: StockFeatures) -> ScoreBreakdown:
    """单只候选股评分主入口(纯函数)

    Returns:ScoreBreakdown(total 是 0..SCREENER_MAX_SCORE)
    """
    mi_score, mi_chips = _score_main_inflow(features.main_net_inflow_yi)
    vr_score, vr_chips = _score_volume_ratio(features.volume_ratio)
    mo_score, mo_chips = _score_momentum(features.change_pct, features.consecutive_up_days)
    se_score, se_chips = _score_sector_strength(features.sector_inflow_rank)

    total = mi_score + vr_score + mo_score + se_score
    return ScoreBreakdown(
        main_inflow_score=mi_score,
        volume_ratio_score=vr_score,
        momentum_score=mo_score,
        sector_strength_score=se_score,
        total=total,
        triggered_rules=mi_chips + vr_chips + mo_chips + se_chips,
    )


def passes_filter(features: StockFeatures, max_drop_pct_5d: float) -> tuple[bool, str | None]:
    """入库过滤:流动性 + 5 日跌幅防雷

    Returns: (是否通过, 拒绝原因)
    """
    if features.turnover_yi < 1.0:
        return False, f"成交额 {features.turnover_yi:.2f}亿 < 1亿(流动性差)"
    if max_drop_pct_5d <= -15.0:
        return False, f"近 5 日跌幅 {max_drop_pct_5d:.1f}% (避雷)"
    return True, None


def build_reason(features: StockFeatures, bd: ScoreBreakdown | None = None) -> str:
    """规则拼接的中文入选理由(1-2 句话, ≤ 100 字符)。

    拼接策略:按优先级"主力→量比→涨幅+连涨→板块"挑非零项拼。
    高位涨幅 / 低涨幅 / 回调涨幅 给风险提示。
    bd 参数可选(旧 backfill 时没有 ScoreBreakdown 也能调用)。

    Returns: 完整 1-2 句中文 + 句号;或"无明显入选信号(评分边缘)。"
    """
    parts: list[str] = []

    # 1) 板块主力净流入
    yi = features.main_net_inflow_yi or 0.0
    if yi >= 2.0:
        parts.append(f"板块资金净流入{yi:.1f}亿(主力强)")
    elif yi >= 1.0:
        parts.append(f"板块资金净流入{yi:.1f}亿")

    # 2) 量比
    vr = features.volume_ratio or 0.0
    if vr >= 3.0:
        parts.append(f"量比{vr:.1f}(爆量)")
    elif vr >= 2.0:
        parts.append(f"量比{vr:.1f}(放量)")
    elif vr >= 1.5:
        parts.append(f"量比{vr:.1f}(温和放量)")

    # 3) 涨幅 + 连涨
    cp = features.change_pct or 0.0
    cu = features.consecutive_up_days or 0
    if cu >= 2 and 0 < cp <= 7:
        parts.append(f"涨幅{cp:.1f}%(连涨{cu}天)")
    elif cp > 7:
        parts.append(f"涨幅{cp:.1f}%(高位,折半追高风险)")
    elif 0 < cp < 3:
        parts.append(f"涨幅{cp:.1f}%(温和)")
    elif cp < 0:
        parts.append(f"涨幅{cp:.1f}%(注意回调)")

    # 4) 板块强度
    rank = features.sector_inflow_rank
    sector = features.sector
    if rank is not None and rank <= 5 and sector:
        parts.append(f"{sector}板块资金Top{rank}")
    elif rank is not None and rank <= 20 and sector:
        parts.append(f"{sector}板块资金Top{rank}")

    # 5) 板块聚集奖励(从 bd 提取)
    if bd is not None:
        for rule in bd.triggered_rules:
            if "同板块" in rule and "只入榜" in rule:
                parts.append(rule)
                break

    if not parts:
        return "无明显入选信号(评分边缘)。"
    reason = "，".join(parts) + "。"
    if len(reason) <= 100:
        return reason
    # 截断:前 4 段 + "等。"
    truncated = "，".join(parts[:4]) + "等。"
    if len(truncated) <= 100:
        return truncated
    return truncated[:97] + "..."