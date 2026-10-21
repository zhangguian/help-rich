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

from decimal import Decimal
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
    shares = getattr(position, "shares", 0)
    # ⚠️ 数值类型契约必须与 `position_status.resolve_position_status` **对齐**:
    # 那里声明「int / float / bool / Decimal 实测均可」(比较运算成立即通过)。
    # 这里若只收 (int, float),同一个 Decimal 持仓在两个模块里结论不同 —— 契约分裂。
    # bool 是 int 的子类,天然通过(与 position_status 相同)。
    # ⚠️ 但**不是完全一致**:NaN 的处理两边不同(2026-10-22 收口复审发现)。
    # 本模块显式抛错(见下);而 position_status 的 `position.shares <= 0` 对 NaN 恒为 False
    # → 会把 NaN 持仓当成「有持仓」放行。本模块更严是对的:
    # NaN 的持仓既不能算有、也不能算无,必须响亮失败,不能静默。
    if not isinstance(shares, (int, float, Decimal)):
        # 形状对了但**值畸形**(如 'abc' / None):同样必须响亮失败。
        # 静默当成「无持仓」会让止损与做T子项整条消失 —— 与 position_status 的契约一致
        # (那里 `position.shares <= 0` 特意放在 try 之外,字符串会抛 TypeError)。
        raise TypeError(
            f"position.shares 须为数值(int / float / Decimal,与 position_status 同类型集),"
            f"收到 {type(shares).__name__}: {shares!r}"
        )
    if shares != shares:  # NaN:与任何数比较都是 False → 会被静默当成「无持仓」
        raise TypeError(f"position.shares 不得为 NaN: {shares!r}")
    return float(shares) > 0


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
    source: str = "decision.actions",
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
        "source": source,          # 溯源用(spec §4.4.4)
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
        raw_label = a.get("label") or ""
        items.append(_item(
            code, name, kind, direction,
            f"明日{raw_label}", price,
            a.get("condition") or "", basis,
            _invalid_if(kind, direction, price, raw_label),
            "armed",
            "decision.actions",
        ))

    # 2) blocked → 解锁条件(方向继承原动作)
    for a in blocked:
        kind = str(a.get("kind") or "watch")
        direction = KIND_DIRECTION.get(kind, "none")
        price = _f(a.get("price"))
        basis = list(a.get("basis") or [])
        raw_label = a.get("label") or ""
        # 缺的依据:优先用决策层显式给出的 `missing`(那是**真正没满足的条件**);
        # 没有才退回「除首条(价位)外的其余依据」。
        # 为什么必须有 missing:真实 blocked 动作(如 L4 补仓摊薄)的 basis 是两条**事实**
        # (「持仓 600 股 @ 成本 15.58 元」「补 100 股后均价 9.87 元」),
        # 把 basis[1:] 当缺失条件会写出「补 100 股后均价 9.87 元未满足则不解锁」——
        # 那不是条件,是事实,用户读到的是假前提。
        explicit = [str(x) for x in (a.get("missing") or []) if str(x)]
        if explicit:
            missing = explicit
        else:
            missing = basis[1:] if len(basis) > 1 else basis
        unlock_txt = "、".join(missing) if missing else f"{raw_label}的前置条件"
        # 文案去重复:缺失依据里已经写了「未达/未满足/未站回/尚未」就别再叠一句
        if any(k in unlock_txt for k in ("未达", "未满足", "未站回", "尚未")):
            invalid_txt = f"{unlock_txt}则不解锁"
        else:
            invalid_txt = f"{unlock_txt}未满足则不解锁"
        items.append(_item(
            code, name, "unlock", direction,
            f"明日解锁后:{raw_label}",
            price,
            a.get("condition") or "", basis,
            invalid_txt,
            "blocked",
            "decision.actions",
        ))

    # 3) 止损(仅持仓票)
    stop = decision.get("stop_loss")
    if isinstance(stop, dict) and _has_position(position):
        price = _f(stop.get("price"))
        # 止损位**已被击穿**时(决策层同时给了 status=="now" 的止损动作),
        # 明日预案不能再写「跌破 X 元无条件减仓」—— 那个条件今天就已经成立,
        # 写进明日预案就是一条过期建议。改成「仍在 X 下方则继续减仓」。
        already = any(
            str(a.get("kind") or "") == "stop"
            and a.get("status") == "now"
            and price is not None
            and _f(a.get("price")) == price
            for a in (decision.get("actions") or [])
            if isinstance(a, dict)
        )
        if price is not None:
            cond = (
                f"已跌破 {price:.2f} 元,明日仍在该位置下方则继续无条件减仓"
                if already else f"跌破 {price:.2f} 元无条件减仓"
            )
        else:
            cond = "跌破止损位无条件减仓"
        items.append(_item(
            code, name, "stop", "sell", "明日止损",
            price,
            cond,
            [stop.get("basis") or ""],
            (f"收盘站回 {price:.2f} 元上方则明日不看止损" if price is not None
             else "止损位未知,明日不执行"),
            "armed",
            "decision.stop_loss",
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
                code, name, "t_sell", "sell", "明日做T减仓",
                th, t_plan.get("sell_trigger") or "", list(basis),
                (f"上沿 {th:.2f} 未触及则不做减仓;下沿 {tl:.2f} 未触及则不做回补"
                 if tl is not None else "上沿未触及则不做减仓"),
                "armed",
                "decision.t_plan",
            ))
        if tl is not None:
            items.append(_item(
                code, name, "t_buyback", "buy", "明日做T回补",
                tl, t_plan.get("buyback_trigger") or "", list(basis),
                (f"下沿 {tl:.2f} 未触及则不做回补;上沿 {th:.2f} 未触及则今日只减不接"
                 if th is not None else "下沿未触及则不做回补"),
                "armed",
                "decision.t_plan",
            ))

    # 5) 别动清单
    for txt in decision.get("do_not") or []:
        if not txt:
            continue
        items.append(_item(
            code, name, "do_not", "none", "明日别动", None,
            str(txt), [str(txt)],
            "该别动项恒成立,明日仍然有效",
            "armed",
            "decision.do_not",
        ))

    return items


__all__ = ["build_items", "build_todos"]
