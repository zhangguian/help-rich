"""找股模块的**纯函数**层(behavior_screener)

设计约束(与项目既有判定层一致):
- **零 IO、零 LLM、零 DB** —— 输入全是已取好的数据,输出是结论
- **缺数据 → 降级**,绝不编数字
- 每个函数都能被单测钉死

与 `screener` 模块的**口径区别**(两者都在 NavRail「决策」组,极易混淆):
- `screener`:按**因子打分**(主力净流入/量比/动能/板块强度/事件热度)排 Top 20
- 本模块:按 **K 线行为信号命中**(主力异动/低吸/锁仓/高抛)分组 + 排序
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import BEHAVIOR_SCREENER_KIND_WEIGHTS
from app.services.behavior_signal_service import (
    KIND_META,
    KIND_ORDER,
    BehaviorMarker,
    main_force_strength_progress,
)

# 信号新鲜度衰减:每过 1 天,得分乘以该系数(信号越久远,参考价值越低)
_FRESHNESS_DECAY = 0.85
# 新鲜度衰减的下限(最多衰减到 30%)
_FRESHNESS_FLOOR = 0.3
# 打分放大倍数:三个系数相乘落在 0.4~2.0,乘 100 后落在 40~200,
# 前端显示与排序都有可辨差异(否则只能看到「1.3 vs 1.5」)
_SCORE_SCALE = 100.0
# 强度系数的下限与跨度:0.5(刚过线) ~ 2.0(全面达到强线)
_STRENGTH_FLOOR = 0.5
_STRENGTH_SPAN = 1.5


@dataclass(frozen=True, slots=True)
class SignalHit:
    """一只票命中的一条行为信号。"""

    stock_code: str
    stock_name: str | None
    kind: str
    signal_date: str
    days_ago: int
    reason: str
    metrics: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    change_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "stock_name": self.stock_name,
            "kind": self.kind,
            "kind_label": KIND_META.get(self.kind, {}).get("label", self.kind),
            "signal_date": self.signal_date,
            "days_ago": self.days_ago,
            "reason": self.reason,
            "metrics": self.metrics,
            "score": round(self.score, 2),
            "change_pct": self.change_pct,
        }


def _freshness(days_ago: int) -> float:
    """信号新鲜度系数:越久远越低(有下限,不让老信号完全归零)。"""
    if days_ago <= 0:
        return 1.0
    factor = _FRESHNESS_DECAY ** days_ago
    return max(_FRESHNESS_FLOOR, factor)


def score_hit(
    marker: BehaviorMarker,
    *,
    days_ago: int,
) -> float:
    """给一条命中信号打分。

    口径:`信号类型权重 × 新鲜度系数 × 强度系数 × 100`

    - **信号类型权重**:来自 `BEHAVIOR_SCREENER_KIND_WEIGHTS`(可配置)
    - **新鲜度系数**:信号越近,分越高
    - **强度系数**:按信号类型的可观测强度归一(见下),**不编数字** ——
      没有可用的强度指标时取 1.0(即只吃类型权重与新鲜度)
    - **×100**:把结果放大到 0~200 的量级 —— 三个系数相乘后落在 0.4~2.0,
      直接展示只能看到「1.3 vs 1.5」这种看不出差别的数字。乘 100 后
      前端显示「强度 147.1」,排序差异也肉眼可辨。

    ⚠️ **涨跌不参与打分**:早期版本给 `score_hit` 留了 `change_pct` 入参,
    但公式里从来没用它 —— 留着就是「接口看起来能用、实际没生效」的坑。
    涨跌属于**展示**信息(且必须取信号当日,见 service 层的口径说明),
    放在 `SignalHit.change_pct` 单独存,不打分。
    """
    kind_weight = BEHAVIOR_SCREENER_KIND_WEIGHTS.get(marker.kind, 1.0)
    strength = _strength_factor(marker)
    return kind_weight * _freshness(days_ago) * strength * _SCORE_SCALE


def _main_force_strength_factor(metrics: dict[str, Any]) -> float:
    """主力异动的**连续**强度系数(0.5 ~ 2.0)。

    ⚠️ **为什么不能按等级给固定加成**:真机实测发现,一旦把「强」的票
    统一加成到上限,同一天所有「强」的主力异动会**分数完全并列**
    (实测前 5 名全是 170.0),排序形同虚设。改成连续系数后,
    「刚过线」和「全面强势」之间拉得开,同档内部也能分先后。

    强度进度由判定层计算(与展示的「强/一般」等级**同源**),
    这里只做线性映射 —— 等级和分数不会出现自相矛盾。
    """
    progress, _ = main_force_strength_progress(
        metrics.get("r0x_ratio"),
        metrics.get("change_pct"),
        metrics.get("volume_ratio"),
        metrics.get("r0_net_yi"),
    )
    if progress is None:
        return 1.0
    return max(_STRENGTH_FLOOR, min(2.0, _STRENGTH_FLOOR + _STRENGTH_SPAN * progress))


def _strength_factor(marker: BehaviorMarker) -> float:
    """按信号的可观测强度归一(0.5 ~ 2.0)。

    缺对应指标 → 返回 1.0(不猜、不编)。
    """
    metrics = marker.metrics or {}
    if marker.kind == "main_force_move":
        return _main_force_strength_factor(metrics)
    if marker.kind == "dip_buy":
        ratio = metrics.get("volume_ratio")
        if ratio is None:
            return 1.0
        # 缩量越明显 → 承接越干净(0.6 量比 → 1.3)
        return max(0.5, min(1.5, 1.5 - abs(1.0 - float(ratio)) * 0.6))
    if marker.kind == "lock_position":
        total = metrics.get("total_main_net_yi")
        if total is None:
            return 1.0
        return max(0.5, min(1.5, 0.5 + abs(float(total)) / 4.0))
    if marker.kind == "distribute":
        distance = metrics.get("high_distance_pct")
        if distance is None:
            return 1.0
        # 越贴近高位高点 → 越典型(0% → 1.5;5% → 1.0)
        return max(0.5, min(1.5, 1.5 - abs(float(distance)) / 10.0))
    return 1.0


def group_hits(hits: list[SignalHit]) -> list[dict[str, Any]]:
    """按信号类型分组(组内按分数降序)。"""
    groups: list[dict[str, Any]] = []
    for kind in KIND_ORDER:
        subset = [h for h in hits if h.kind == kind]
        if not subset:
            continue
        subset.sort(key=lambda h: (-h.score, h.stock_code))
        groups.append(
            {
                "kind": kind,
                "kind_label": KIND_META.get(kind, {}).get("label", kind),
                "count": len(subset),
                "picks": [h.to_dict() for h in subset],
            }
        )
    return groups


def sort_hits(hits: list[SignalHit]) -> list[SignalHit]:
    """综合排序:分数降序 → 信号更近的优先 → 代码升序(稳定)。"""
    return sorted(hits, key=lambda h: (-h.score, h.days_ago, h.stock_code))


__all__ = [
    "SignalHit",
    "group_hits",
    "score_hit",
    "sort_hits",
]
