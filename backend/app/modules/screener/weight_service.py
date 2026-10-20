"""选股权重用例层(阶段2)。

对外提供:读当前权重(有 DB 用 DB,无则默认)、保存权重(校验+夹取)、
重置为默认。评分调用方通过 `get_effective_weights()` 拿一套可传进
`score_stock` 的权重。
"""
from __future__ import annotations

from app.modules.screener.weight_repository import screener_weight_repo
from app.modules.screener.scoring import (
    FACTOR_KEYS,
    FACTOR_META,
    MAX_WEIGHT,
    MIN_WEIGHT,
    ScoringWeights,
    build_weights,
    clamp_weight,
    default_weights,
)

# 模块级缓存,避免每次评分都查库;改权重时主动失效
_cached: ScoringWeights | None = None


class WeightValidationError(ValueError):
    """权重配置非法(给用户明确反馈)。"""


async def get_effective_weights(refresh: bool = False) -> ScoringWeights:
    """当前生效权重。评分热路径调用,带进程内缓存。"""
    global _cached
    if _cached is None or refresh:
        rows = await screener_weight_repo.list_rows()
        _cached = build_weights(rows)
    return _cached


def invalidate_cache() -> None:
    """改权重后调用,使下次评分重新读库。"""
    global _cached
    _cached = None


async def get_weights_view() -> dict:
    """给设置页的完整视图:每个因子的当前值/范围/说明/上限。"""
    weights = await get_effective_weights(refresh=True)
    return {
        "factors": [
            {
                "key": k,
                "label": FACTOR_META[k][0],
                "description": FACTOR_META[k][2],
                "weight": round(float(getattr(weights, k)), 2),
                "enabled": k not in weights.disabled,
                "min": MIN_WEIGHT,
                "max": MAX_WEIGHT,
            }
            for k in FACTOR_KEYS
        ],
        "max_total": round(weights.max_total, 2),
    }


async def save_weights(items: list[dict]) -> dict:
    """保存一组权重(items: [{key/factor_name, weight, enabled}])。

    - 未知因子忽略
    - 数值夹到 [MIN, MAX]
    - 全部停用则拒绝
    """
    weights = default_weights()
    disabled: set[str] = set()
    payload: list[dict] = []
    seen: set[str] = set()

    for item in items:
        key = item.get("key") or item.get("factor_name")
        if key not in FACTOR_META:
            continue
        seen.add(key)
        w = clamp_weight(item.get("weight"))
        enabled = bool(item.get("enabled", True))
        setattr(weights, key, w)
        if not enabled:
            disabled.add(key)
        payload.append({"factor_name": key, "weight": w, "enabled": enabled})

    if not payload:
        raise WeightValidationError("没有可识别的因子")
    weights.disabled = frozenset(disabled)
    problems = weights.validate()
    if problems:
        raise WeightValidationError(";".join(problems))

    await screener_weight_repo.upsert_many(payload)
    invalidate_cache()
    return await get_weights_view()


async def reset_weights() -> dict:
    """清空自定义,回落 config 默认。"""
    await screener_weight_repo.reset_to_default()
    invalidate_cache()
    return await get_weights_view()


__all__ = [
    "WeightValidationError",
    "get_effective_weights",
    "get_weights_view",
    "invalidate_cache",
    "reset_weights",
    "save_weights",
]
