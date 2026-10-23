"""盘中复盘决策层(纯函数、零 IO、零 LLM)

**铁律**:
- 只做「现价 vs 触发价」的显式比较,**不重算任何价格**;
- 不引入新判断 —— `action_hint` 只复述该条预案已有的 `basis` / `invalid_if`;
- 缺数据 → `None` + `degraded=True` + `degraded_reason`,**不猜**。

**`action_state` 与兑现五态是不同域,别混用**:

| 域 | 取值 | 回答的问题 | 判定依据 |
| --- | --- | --- | --- |
| 兑现五态(`services/fulfillment_checker`) | executed / touched / missed / n_a / no_data | 「昨天那条预案,今天到底做没做到」 | 当日成交流水 + 当日 K 线 |
| 本模块的 `action_state` | 数据不足 / 不适用 / 已到价待执行 / 未到价 | 「此刻这条预案的价格条件成立了没有」 | 只有实时报价 vs 触发价 |

⚠️ **本模块不判「已执行」,也不判「已过价」**:
- 「已执行」必须由**当日成交流水**比对判定,那是兑现模块的职责。本轮盘中复盘
  没有流水上下文,若在此处判「已执行」,同一个字段会有两个来源 → 与阶段 9 的
  兑现模块**双写冲突**(必然对不上),所以宁可少判也不猜。
- 「已过价」需要知道「前面的动作是否已被消耗」,那是**跨条配对**的全局职责
  (同一只票可能有多条预案),同样不在本模块实现。

⚠️ **每条预案各自出一行**,不做跨票 / 跨条合并 —— 跨条去重是兑现模块的全局
配对职责,这里重复实现会把两套口径搅在一起。
"""
from __future__ import annotations

import math
from typing import Any

# 阈值比较的浮点容差:与 `services/fulfillment_checker._EPS` 同口径
# (9.2 × 1.02 = 9.383999999999999 < 9.384,不加容差会漏判「恰好按计划价位成交」)
_EPS = 1e-9

# 纪律类预案:不产生方向性价格动作
DISCIPLINE_KINDS = frozenset({"do_not", "unlock"})

# ---- action_state 取值域(与兑现五态不同域) ----
STATE_NO_DATA = "数据不足"
STATE_NA = "不适用"
STATE_TRIGGERED = "已到价待执行"
STATE_NOT_TRIGGERED = "未到价"

# 市场意见口径:盘前四维度规则推断,盘中**不重算**
MARKET_BASIS = "盘前四维度规则推断（非盘中重算）"

STANCE_LABEL = {
    "bullish": "偏多",
    "bearish": "偏空",
    "neutral": "震荡",
    "unknown": "数据不足",
}


def _f(v: Any) -> float | None:
    """转 float;NaN / ±inf 一律当无效(与 outlook_service / fulfillment_checker 同口径)"""
    try:
        if v is None:
            return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _quote(quotes: dict[str, Any], code: str) -> dict[str, Any]:
    q = (quotes or {}).get(code)
    return q if isinstance(q, dict) else {}


def _quote_price(quotes: dict[str, Any], code: str) -> float | None:
    """实时价(取不到 → None)。兼容 `price` / `current_price` 两种键名。"""
    q = _quote(quotes, code)
    price = _f(q.get("price"))
    if price is None:
        price = _f(q.get("current_price"))
    return price


def _fmt_levels(values: Any) -> str:
    out: list[str] = []
    for v in values or []:
        f = _f(v)
        out.append(f"{f:.2f}" if f is not None else str(v))
    return "/".join(out) if out else "无"


def _market_opinion(outlook: dict[str, Any]) -> dict[str, Any]:
    """市场意见:**沿用**作战计划的 outlook,盘中不重算。"""
    stance = str(outlook.get("stance") or "unknown")
    stance_label = str(outlook.get("stance_label") or STANCE_LABEL.get(stance, "数据不足"))
    dims = [d for d in (outlook.get("dims") or []) if isinstance(d, dict)]
    key_levels = outlook.get("key_levels")
    key_levels = key_levels if isinstance(key_levels, dict) else {}
    effective = sum(1 for d in dims if d.get("state") != "missing")
    total = len(dims)

    summary = f"盘前四维度规则推断:倾向{stance_label}({effective}/{total} 维有效)"
    support = key_levels.get("support") or []
    resistance = key_levels.get("resistance") or []
    if support:
        summary += f",支撑 {_fmt_levels(support)}"
    if resistance:
        summary += f",压力 {_fmt_levels(resistance)}"

    return {
        "stance": stance,
        "stance_label": stance_label,
        "basis": MARKET_BASIS,
        "dims": dims,
        "key_levels": key_levels,
        "summary": summary,
        # 沿用 outlook 自身的降级标记(缺维度的维度),不重算
        "degraded": bool(outlook.get("degraded")),
        "degraded_reason": list(outlook.get("degraded_reason") or []),
    }


def _hint(
    state: str,
    label: str,
    kind: str,
    direction: str,
    code: str,
    price: float | None,
    trigger: float | None,
    gap_pct: float | None,
    basis: list[str],
    invalid_if: str,
) -> str:
    """一句面向小白的中文建议。

    **只复述该条预案已有的 basis / invalid_if**,不新增任何判断。
    """
    if state == STATE_NA:
        if kind in DISCIPLINE_KINDS:
            return f"「{label}」是纪律类预案,不产生价格动作,照做即可。"
        return f"「{label}」是观察类预案,不产生价格动作,盯住条件即可。"

    if state == STATE_NO_DATA:
        if trigger is None:
            return f"「{label}」没有触发价,无法判断是否到价(先补齐这条预案的触发价)。"
        return f"「{label}」没有拿到 {code} 的实时报价,先核对行情再决定是否动手。"

    if price is None or trigger is None or gap_pct is None:
        return f"「{label}」数据不足,先补齐行情再判断。"

    if state == STATE_TRIGGERED:
        verb = "跌至" if direction == "sell" else "涨至"
        core = (
            f"现价 {price:.2f} 元已{verb}触发价 {trigger:.2f} 元({gap_pct:+.2f}%),按预案执行"
        )
    else:
        core = (
            f"现价 {price:.2f} 元,距触发价 {trigger:.2f} 元还差 {abs(gap_pct):.2f}%,"
            f"未到价,等到位再动"
        )
    if basis:
        core += f";依据:{basis[0]}"
    if invalid_if:
        core += f";失效条件:{invalid_if}"
    return core


def build_intraday_advice(
    outlook: dict[str, Any],
    items: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    now_iso: str,
) -> dict[str, Any]:
    """盘中复盘决策(纯函数、零 IO、零 LLM)。

    Args:
        outlook: 作战计划的 outlook(stance / dims / key_levels)—— **沿用,不重算**。
        items: 逐票预案(作战计划的 items)—— 每条各出一行,不做跨条合并。
        quotes: `code -> {"price": float|None, "change_pct": float|None}`。
        now_iso: 判定时点(`YYYY-MM-DDTHH:MM:SS`),原样带进产出的 `as_of`。

    Returns:
        `{market_opinion, actions, degraded, degraded_reason, as_of}`
    """
    outlook = outlook if isinstance(outlook, dict) else {}
    item_list = [it for it in (items or []) if isinstance(it, dict)]
    quote_map = quotes if isinstance(quotes, dict) else {}

    degraded_reasons: list[str] = []
    actions: list[dict[str, Any]] = []

    for item in item_list:
        code = str(item.get("stock_code") or "")
        name = item.get("stock_name")
        kind = str(item.get("item_kind") or "")
        direction = str(item.get("direction") or "none")
        label = str(item.get("label") or "")
        basis = [str(b) for b in (item.get("basis") or [])]
        invalid_if = str(item.get("invalid_if") or "")

        trigger = _f(item.get("trigger_price"))
        price = _quote_price(quote_map, code)

        # ---- 1) 纪律类 / 无方向 → 不适用(不产生方向性价格动作) ----
        if kind in DISCIPLINE_KINDS or direction not in ("buy", "sell"):
            state = STATE_NA
        # ---- 2) 缺触发价 / 缺实时报价 → 数据不足(不猜) ----
        elif trigger is None:
            state = STATE_NO_DATA
            degraded_reasons.append(f"{code} 的预案「{label}」没有触发价")
        elif price is None:
            state = STATE_NO_DATA
            degraded_reasons.append(f"{code} 没有实时报价")
        # ---- 3) 现价 vs 触发价(显式比较,EPS 容差与兑现模块同口径) ----
        elif direction == "sell":
            state = STATE_TRIGGERED if price <= trigger + _EPS else STATE_NOT_TRIGGERED
        else:  # buy
            state = STATE_TRIGGERED if price >= trigger - _EPS else STATE_NOT_TRIGGERED

        # gap_pct:显式除法(现价相对触发价的偏离百分比);只在有价格动作时才有意义
        gap_pct: float | None = None
        if (
            state in (STATE_TRIGGERED, STATE_NOT_TRIGGERED)
            and price is not None
            and trigger is not None
            and trigger != 0
        ):
            gap_pct = (price - trigger) / trigger * 100.0

        actions.append({
            "stock_code": code,
            "stock_name": name,
            "item_kind": kind,
            "direction": direction,
            "label": label,
            "trigger_price": trigger,
            "current_price": price,
            "gap_pct": gap_pct,
            "action_state": state,
            "action_hint": _hint(
                state, label, kind, direction, code, price, trigger, gap_pct, basis, invalid_if,
            ),
            "basis": basis,
            "invalid_if": invalid_if,
        })

    if not outlook:
        degraded_reasons.append("作战计划缺少市场预期(outlook),无法给出市场意见")

    market_opinion = _market_opinion(outlook)

    return {
        "market_opinion": market_opinion,
        "actions": actions,
        "degraded": bool(degraded_reasons),
        "degraded_reason": "; ".join(degraded_reasons) if degraded_reasons else None,
        "as_of": now_iso,
    }


__all__ = [
    "DISCIPLINE_KINDS",
    "MARKET_BASIS",
    "STATE_NOT_TRIGGERED",
    "STATE_NO_DATA",
    "STATE_NA",
    "STATE_TRIGGERED",
    "build_intraday_advice",
]
