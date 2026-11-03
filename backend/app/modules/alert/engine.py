"""价格提醒条件引擎(纯函数,无 IO)。

设计要点:
- **纯函数**:只吃行情快照 + 条件树,吐 bool。方便单测,也方便未来换数据源。
- **AND/OR 可嵌套**:对齐 PanWatch 的条件组合能力。
- **不抛错**:未知 metric / op 一律判 False(宁可漏提醒,不要因为
  配置写错把整个调度器带崩)。

条件树 JSON 结构::

    {"op": "and",
     "conditions": [
        {"metric": "price", "op": "<=", "value": 12.5},
        {"op": "or", "conditions": [
            {"metric": "volume_ratio", "op": ">", "value": 2.0},
            {"metric": "change_pct", "op": "<=", "value": -3.0}
        ]}
     ]}
"""
from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# === 比较算子 ===
_COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

# === 可用指标 ===
SUPPORTED_METRICS = ("price", "change_pct", "volume_ratio", "turnover")
SUPPORTED_OPS = tuple(_COMPARATORS)


class AlertConditionError(ValueError):
    """条件配置非法(创建/更新时抛出,让用户立刻看到)。"""


@dataclass(slots=True)
class AlertContext:
    """一次评估所依据的行情快照。缺失的指标为 None(对应条件判 False)。"""

    price: float | None = None
    change_pct: float | None = None
    volume_ratio: float | None = None
    turnover: float | None = None

    def get(self, metric: str) -> float | None:
        return getattr(self, metric, None)


def _eval_leaf(condition: dict, ctx: AlertContext) -> bool:
    metric = condition.get("metric")
    op = condition.get("op")
    value = condition.get("value")

    if metric not in SUPPORTED_METRICS or op not in _COMPARATORS:
        return False
    if value is None:
        return False

    actual = ctx.get(metric)
    if actual is None:
        return False

    try:
        return _COMPARATORS[op](float(actual), float(value))
    except (TypeError, ValueError):
        return False


def evaluate(node: dict | None, ctx: AlertContext) -> bool:
    """递归求值条件树。

    - 叶子:{"metric","op","value"}
    - 分组:{"op": "and"|"or", "conditions": [...]}
    - 空条件树 → False(不视为"恒真",避免误推送)
    """
    if not node:
        return False

    if "metric" in node:
        return _eval_leaf(node, ctx)

    op = node.get("op", "and")
    children = node.get("conditions") or []
    if not children:
        return False

    if op == "or":
        return any(evaluate(child, ctx) for child in children)
    # 默认 AND
    return all(evaluate(child, ctx) for child in children)


def fingerprint(node: dict | None, ctx: AlertContext) -> str:
    """触发指纹:条件树 + 当前价格分桶。

    同一规则在价格未跨越同一分桶前重复触发会被去重冷却拦住,
    避免价格在阈值附近来回抖动导致刷屏。
    """
    price_bucket = "na"
    if ctx.price is not None:
        price_bucket = f"{round(float(ctx.price), 1)}"
    change_bucket = "na"
    if ctx.change_pct is not None:
        change_bucket = f"{round(float(ctx.change_pct))}"
    import hashlib
    import json

    raw = json.dumps(
        {"conditions": node, "price": price_bucket, "change": change_bucket},
        sort_keys=True,
        ensure_ascii=False,
    )
    # 仅用于「同一条件树 + 同一行情」的指纹去重,不是安全用途
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def describe(node: dict | None) -> str:
    """把条件树渲染成一句中文,用于通知正文与前端预览。"""
    if not node:
        return "无条件"
    if "metric" in node:
        metric_label = {
            "price": "价格",
            "change_pct": "涨跌幅(%)",
            "volume_ratio": "量比",
            "turnover": "换手率(%)",
        }.get(node.get("metric"), node.get("metric", "?"))
        return f"{metric_label} {node.get('op')} {node.get('value')}"
    joiner = " 或 " if node.get("op") == "or" else " 且 "
    children = node.get("conditions") or []
    return joiner.join(describe(child) for child in children)


def notification_meta(node: dict | None) -> dict:
    """读取条件树**顶层**的提醒元信息。

    引擎不认识这两个字段,只负责透传 —— 这样「这条提醒是什么性质」由建规则的人说,
    而求值逻辑不必知道具体业务含义:

    - `kind`: 提醒种类(如 `"pre_alert"` 预警)。进 SSE 负载,前端据此区分徽章。
    - `once`: `True` = **一次性**提醒 —— 命中后自动停用。
      用于「预警」:进了一次准备区就不该反复提醒,价格离开预警区再回来时重新武装。

    顶层字段(不写进叶子)→ `evaluate` / `validate` / `describe` 全都不受影响。
    """
    if not isinstance(node, dict):
        return {}
    kind = node.get("kind")
    once = node.get("once")
    return {
        "kind": kind if isinstance(kind, str) and kind else None,
        "once": once is True,
    }


# ============================================================
# 条件树校验(创建/更新时用)
# ============================================================

def validate(node: dict | None, depth: int = 0) -> None:
    """校验条件树结构,非法直接抛 AlertConditionError。

    限制嵌套深度 3 层,防止用户写出无法维护的巨型条件。
    """
    if depth > 3:
        raise AlertConditionError("条件嵌套过深(最多 3 层)")
    if not node:
        raise AlertConditionError("条件不能为空")
    if not isinstance(node, dict):
        raise AlertConditionError("条件必须是对象")

    if "metric" in node:
        if node.get("metric") not in SUPPORTED_METRICS:
            raise AlertConditionError(
                f"不支持的指标 {node.get('metric')},可用:{', '.join(SUPPORTED_METRICS)}"
            )
        if node.get("op") not in _COMPARATORS:
            raise AlertConditionError(
                f"不支持的比较符 {node.get('op')},可用:{', '.join(SUPPORTED_OPS)}"
            )
        try:
            float(node.get("value"))
        except (TypeError, ValueError):
            raise AlertConditionError("条件的 value 必须是数字") from None
        return

    if node.get("op") not in ("and", "or"):
        raise AlertConditionError("分组 op 只能是 and 或 or")
    children = node.get("conditions")
    if not isinstance(children, list) or not children:
        raise AlertConditionError("分组必须包含非空 conditions 数组")
    for child in children:
        validate(child, depth + 1)


__all__ = [
    "AlertConditionError",
    "AlertContext",
    "SUPPORTED_METRICS",
    "SUPPORTED_OPS",
    "describe",
    "evaluate",
    "fingerprint",
    "notification_meta",
    "validate",
]
