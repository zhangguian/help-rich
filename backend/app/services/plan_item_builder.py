"""决策输出 → 明日操作预案(纯函数、零 IO、零 LLM)

设计文档 §4.4。

**核心分流规则**:
| 决策输出 | 去向 |
|---|---|
| actions status="now"    | **不进明日预案** → 今日复盘「未执行待办」(条件已过期) |
| actions status="armed"  | 明日预案主力 |
| actions status="blocked"| 明日预案「解锁条件」 |
| stop_loss               | 明日预案(仅持仓票) |
| t_plan                  | 明日预案(仅持仓票,拆上沿/下沿两条) |
| do_not[]                | 明日预案「别动」 |

**为什么 now 不进明日预案**:它的语义是「此刻条件已满足,此刻就该做」。
写进明日预案就是一条**已经过期的建议**——这正是股民复盘里最常见的自欺
("我有个计划"但其实条件早就到了没做)。必须显式推到复盘待办,逼用户面对。
"""
from __future__ import annotations

from typing import Any

# 决策引擎 kind → 预案方向
# ⚠️ 只列**会被查询**的 kind。unlock / do_not 不在此表:
# unlock 项的 direction 继承被它派生的原动作 kind;do_not 项恒为 none(直接写死)。
KIND_DIRECTION: dict[str, str] = {
    "entry": "buy",
    "add": "buy",
    "t_buyback": "buy",
    "exit": "sell",
    "stop": "sell",
    "t_sell": "sell",
    "watch": "none",
}

# 失效条件系数(显式四则运算,不是拍脑袋的魔法数)
ENTRY_INVALID_FACTOR = 0.97   # 跌破 触发价×0.97 → 建仓预案作废
EXIT_INVALID_FACTOR = 1.03    # 回落至 触发价×1.03 以上未达成 → 不追高


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _has_position(position) -> bool:
    """持仓判定:`position` 须为含 `.shares` **属性**的对象。

    ⚠️ 契约统一(2026-10-21 跨任务裁决):本模块与
    `services/position_status.resolve_position_status` **统一用属性形状**,
    不用 dict —— 后者的契约已写进 docstring 并通过 Task 1 复审,
    改它要动既有代码(且 `api/diagnose.py` 在用);而本模块是新代码,改它零成本。
    接线层(Task 6)造一个 PositionView 同时传给两者。

    **传 dict 抛 TypeError(不静默降级)**:dict 没有 `.shares` 属性,
    会被读成 0 股 → 持仓票的「止损」与两条「做T」子项被**静默漏掉** →
    用户拿到的计划里根本没有止损,复盘时却显示「按计划执行」。
    这种漏项比报错更难发现,所以这里选择**响亮地失败**
    (与 `position_status.resolve_position_status` 的契约处理一致)。
    """
    if position is None:
        return False
    if not hasattr(position, "shares"):
        raise TypeError(
            "position 须为含 .shares 属性的对象(如 PositionView / Position),"
            f"收到 {type(position).__name__} —— 传 dict 会静默漏掉止损与做T子项"
        )
    try:
        return int(getattr(position, "shares", 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def _invalid_if(item_kind: str, direction: str, price: float | None,
                label: str) -> str:
    """算失效条件(不得为空,除非是恒成立的别动项)"""
    if item_kind == "do_not":
        return "该别动项恒成立,明日仍然有效"
    if price is None:
        return f"触发价未知,{label}不执行"
    if direction == "buy":
        cut = round(price * ENTRY_INVALID_FACTOR, 2)
        return f"跌破 {cut:.2f} 则本条作废(不接下跌中的刀)"
    if direction == "sell":
        back = round(price * EXIT_INVALID_FACTOR, 2)
        return f"回落至 {back:.2f} 以上未达成,明日不追高"
    return f"{label}条件不满足则不执行"


def _item(
    stock_code: str,
    stock_name: str | None,
    item_kind: str,
    direction: str,
    label: str,
    trigger_price: float | None,
    trigger_condition: str,
    basis: list[str],
    invalid_if: str,
    status_now: str,
) -> dict[str, Any]:
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "item_kind": item_kind,
        "direction": direction,
        "label": label,
        "trigger_price": trigger_price,
        "trigger_condition": trigger_condition,
        "basis": basis,
        "invalid_if": invalid_if,
        "status_now": status_now,
        "fulfillment": "pending",
        "fulfillment_note": "",
    }


def _split_actions(decision: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """把 actions 按 status 拆成 (now, armed, blocked)三组"""
    now: list[dict] = []
    armed: list[dict] = []
    blocked: list[dict] = []
    for a in decision.get("actions") or []:
        if not isinstance(a, dict):
            continue
        st = a.get("status")
        if st == "now":
            now.append(a)
        elif st == "armed":
            armed.append(a)
        elif st == "blocked":
            blocked.append(a)
    return now, armed, blocked


def build_todos(decision: dict) -> list[dict]:
    """今日复盘的「未执行待办」:条件已满足(now)但用户还没做的动作"""
    now, _, _ = _split_actions(decision)
    code = decision.get("stock_code") or ""
    name = decision.get("stock_name")
    out: list[dict] = []
    for a in now:
        out.append({
            "stock_code": code,
            "stock_name": name,
            "label": a.get("label") or "",
            "condition": a.get("condition") or "",
            "price": _f(a.get("price")),
            "basis": list(a.get("basis") or []),
        })
    return out


def build_items(decision: dict, position) -> list[dict]:
    """明日操作预案项(纯函数)

    `position` 须为含 `.shares` **属性**的对象(或 None)——与
    `services/position_status.resolve_position_status` 同契约(属性形状,不是 dict)。
    """
    code = decision.get("stock_code") or ""
    name = decision.get("stock_name")
    _, armed, blocked = _split_actions(decision)
    items: list[dict] = []

    # 1) armed → 明日预案主力
    for a in armed:
        kind = str(a.get("kind") or "watch")
        direction = KIND_DIRECTION.get(kind, "none")
        price = _f(a.get("price"))
        basis = list(a.get("basis") or [])
        items.append(_item(
            code, name, kind, direction,
            a.get("label") or "", price,
            a.get("condition") or "", basis,
            _invalid_if(kind, direction, price, a.get("label") or ""),
            "armed",
        ))

    # 2) blocked → 解锁条件(方向继承原动作)
    for a in blocked:
        kind = str(a.get("kind") or "watch")
        direction = KIND_DIRECTION.get(kind, "none")
        price = _f(a.get("price"))
        basis = list(a.get("basis") or [])
        # 缺的依据 = 除首条(价位)外的其余依据;没有则用标签兜底
        missing = basis[1:] if len(basis) > 1 else basis
        unlock_txt = "、".join(missing) if missing else f"{a.get('label') or ''}的前置条件"
        items.append(_item(
            code, name, "unlock", direction,
            f"解锁后:{a.get('label') or ''}",
            price,
            a.get("condition") or "", basis,
            f"{unlock_txt}未满足则不解锁",
            "blocked",
        ))

    # 3) 止损(仅持仓票)
    stop = decision.get("stop_loss")
    if isinstance(stop, dict) and _has_position(position):
        price = _f(stop.get("price"))
        items.append(_item(
            code, name, "stop", "sell", "止损",
            price,
            f"跌破 {price:.2f} 元无条件减仓" if price is not None else "跌破止损位无条件减仓",
            [stop.get("basis") or ""],
            (f"收盘站回 {price:.2f} 元上方则明日不看止损" if price is not None
             else "止损位未知,明日不执行"),
            "armed",
        ))

    # 4) 做T(仅持仓票;拆上沿/下沿两条)
    t_plan = decision.get("t_plan")
    if isinstance(t_plan, dict) and t_plan.get("suitable") and _has_position(position):
        base = t_plan.get("base_position_pct") or ""
        th = _f(t_plan.get("t_high"))
        tl = _f(t_plan.get("t_low"))
        amp = t_plan.get("amplitude_pct")
        basis = [f"T 区间宽度 {amp}%"] if amp is not None else []
        if base:
            basis.append(f"底仓要求 {base}")
        if th is not None:
            items.append(_item(
                code, name, "t_sell", "sell", "做T减仓",
                th, t_plan.get("sell_trigger") or "", basis,
                (f"上沿 {th:.2f} 未触及则不做减仓;下沿 {tl:.2f} 未触及则不做回补"
                 if tl is not None else "上沿未触及则不做减仓"),
                "armed",
            ))
        if tl is not None:
            items.append(_item(
                code, name, "t_buyback", "buy", "做T回补",
                tl, t_plan.get("buyback_trigger") or "", basis,
                (f"下沿 {tl:.2f} 未触及则不做回补;上沿 {th:.2f} 未触及则今日只减不接"
                 if th is not None else "下沿未触及则不做回补"),
                "armed",
            ))

    # 5) 别动清单
    for txt in decision.get("do_not") or []:
        if not txt:
            continue
        items.append(_item(
            code, name, "do_not", "none", "别动", None,
            str(txt), [str(txt)],
            "该别动项恒成立,明日仍然有效",
            "armed",
        ))

    return items


__all__ = ["build_items", "build_todos"]
