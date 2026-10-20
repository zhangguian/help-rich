"""选股权重(阶段2)。

解决的问题:`app/core/config.py` 里 50 行 `SCREENER_*` 常量把各因子满分写死,
用户想"更看资金还是更看量比"必须改代码重启。本模块把**因子满分**外置成
可配置项,做到:

- **有配置用配置,无配置回落常量** —— 老用户零改动,历史评分版本完全可复现
- **纯函数** —— 权重计算不碰 DB,便于单测与回测复现
- **版本化** —— 每次改权重写一条 `scoring_version`,供回测对比

四个因子(与 `services/scoring.py` 一一对应):
    main_inflow / volume_ratio / momentum / sector_strength
外加事件因子 event(由 `event_score()` 单独加)。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import (
    SCREENER_EVENT_FACTOR_WEIGHT,
    SCREENER_MAIN_INFLOW_MAX,
    SCREENER_MOMENTUM_MAX,
    SCREENER_SECTOR_MAX,
    SCREENER_VOLUME_RATIO_MAX,
)

# 因子 key → (中文名, 默认满分, 说明)
FACTOR_META: dict[str, tuple[str, float, str]] = {
    "main_inflow": ("主力净流入", SCREENER_MAIN_INFLOW_MAX, "板块资金流入强度,资金驱动主力"),
    "volume_ratio": ("量比", SCREENER_VOLUME_RATIO_MAX, "放量程度,量能启动信号"),
    "momentum": ("动能", SCREENER_MOMENTUM_MAX, "当日涨幅 + 连涨天数,趋势确认"),
    "sector_strength": ("板块强度", SCREENER_SECTOR_MAX, "个股所属板块在资金榜的排名"),
    "event": ("事件热度", SCREENER_EVENT_FACTOR_WEIGHT, "当日热门事件相关股加权"),
}

FACTOR_KEYS = tuple(FACTOR_META)

# 权重上下限:防止用户把某因子拉到 0(丢失信号)或拉爆(单一因子主导)
MIN_WEIGHT = 0.0
MAX_WEIGHT = 200.0


def default_weights() -> "ScoringWeights":
    """默认权重 = config 常量(向后兼容的唯一真源)。"""
    return ScoringWeights(
        **{k: meta[1] for k, meta in FACTOR_META.items()}
    )


@dataclass(slots=True)
class ScoringWeights:
    """一套因子满分配置。"""

    main_inflow: float = SCREENER_MAIN_INFLOW_MAX
    volume_ratio: float = SCREENER_VOLUME_RATIO_MAX
    momentum: float = SCREENER_MOMENTUM_MAX
    sector_strength: float = SCREENER_SECTOR_MAX
    event: float = SCREENER_EVENT_FACTOR_WEIGHT
    # 被停用的因子不参与加分(置 0),但保留配置值以便随时恢复
    disabled: frozenset[str] = field(default_factory=frozenset)

    def get(self, key: str) -> float:
        """取某因子的有效满分(已考虑 disabled)。"""
        if key in self.disabled:
            return 0.0
        return float(getattr(self, key, 0.0))

    @property
    def max_total(self) -> float:
        """这套权重下的综合分上限。"""
        return sum(self.get(k) for k in FACTOR_KEYS)

    def to_dict(self) -> dict:
        return {
            k: {"value": float(getattr(self, k)), "enabled": k not in self.disabled}
            for k in FACTOR_KEYS
        }

    def validate(self) -> list[str]:
        """返回问题列表(空表示合法)。"""
        problems: list[str] = []
        for k in FACTOR_KEYS:
            v = float(getattr(self, k))
            if not (MIN_WEIGHT <= v <= MAX_WEIGHT):
                name = FACTOR_META[k][0]
                problems.append(
                    f"{name}({k}) 权重 {v} 超出允许范围 "
                    f"[{MIN_WEIGHT}, {MAX_WEIGHT}]"
                )
        # 全部关掉会让评分完全失效
        if all(k in self.disabled for k in FACTOR_KEYS):
            problems.append("至少要启用一个因子")
        return problems


def clamp_weight(value) -> float:
    """把外部输入夹到合法区间。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(MIN_WEIGHT, min(MAX_WEIGHT, v))


def build_weights(rows: list[dict] | None) -> ScoringWeights:
    """从 DB 行构造权重对象;无行/非法行自动回落默认值。

    rows 形如 `[{"factor_name": "momentum", "weight": 45.0, "enabled": True}, ...]`
    """
    if not rows:
        return default_weights()

    weights = default_weights()
    disabled: set[str] = set()
    known: set[str] = set()
    for row in rows:
        key = row.get("factor_name")
        if key not in FACTOR_META:
            continue  # 未知因子(旧版本残留)忽略,不报错
        setattr(weights, key, clamp_weight(row.get("weight")))
        if row.get("enabled") is False:
            disabled.add(key)
        known.add(key)

    if not known:  # 全是未知行 → 等同于没配置
        return default_weights()
    weights.disabled = frozenset(disabled)
    return weights


def weights_from_mapping(mapping: dict | None) -> "ScoringWeights":
    """从 `{factor_name: weight}` 映射构造权重。

    与 `build_weights` 的区别:`build_weights` 吃的是 **DB 行**
    (`[{"factor_name":..., "weight":..., "enabled":...}]`),而回测 API
    传的是**扁平映射**(`{"main_inflow": 120}`)。两者混用会得到
    `'str' object has no attribute 'get'`,因此单独提供本函数。

    未出现的因子保持默认值;未知 key 忽略;数值自动夹取。
    """
    weights = default_weights()
    if not mapping:
        return weights
    for key, value in mapping.items():
        if key not in FACTOR_META:
            continue
        setattr(weights, key, clamp_weight(value))
    return weights


__all__ = [
    "FACTOR_KEYS",
    "FACTOR_META",
    "MAX_WEIGHT",
    "MIN_WEIGHT",
    "ScoringWeights",
    "build_weights",
    "clamp_weight",
    "default_weights",
    "weights_from_mapping",
]
