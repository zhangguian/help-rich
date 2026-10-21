"""昨日预案 × 今日行情/流水 → 兑现状态(纯函数、零 IO、零 LLM)

设计文档 §4.5。

**记法**:R = 被检查的日报日(R 日报的 items 是为 R+1 定下的);
R+1 = 兑现判定日。

**诚实性**:"未触发"不评价对错。计划说"跌破 9.62 止损",当天最低 9.70
没跌破 —— 这不是"止损错了",而是"不该触发"。算成错误会污染决策档案。
"""
from __future__ import annotations

from typing import Any

# 纪律问题相关:计划说别动/未解锁,却仍然操作
DISCIPLINE_KINDS = {"do_not", "unlock"}

# T 操作的「减」与「接」方向相反,**不能只看 action**,必须按价格区间匹配(spec §4.5):
#   卖出价 ≥ 上沿 × 0.98 → 算「减仓」子项已执行
#   买价   ≤ 下沿 × 1.02 → 算「回补」子项已执行
T_SELL_TOLERANCE = 0.98
T_BUYBACK_TOLERANCE = 1.02


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _day_extremes(klines: list[dict] | None) -> tuple[float | None, float | None]:
    """目标日的 (high, low);缺数据返回 (None, None)"""
    if not klines:
        return None, None
    highs: list[float] = []
    lows: list[float] = []
    for k in klines:
        if not isinstance(k, dict):
            continue
        h = _f(k.get("high"))
        lo = _f(k.get("low"))
        if h is not None:
            highs.append(h)
        if lo is not None:
            lows.append(lo)
    return (max(highs) if highs else None, min(lows) if lows else None)


def _has_txn(transactions: list[dict] | None, code: str, action: str) -> bool:
    if not transactions:
        return False
    for t in transactions:
        if not isinstance(t, dict):
            continue
        if t.get("stock_code") != code:
            continue
        if str(t.get("action") or "").lower() == action:
            return True
    return False


def _executed_at_price(
    transactions: list[dict] | None,
    code: str,
    action: str,
    threshold: float,
    at_least: bool,
) -> bool:
    """T 子项按**价格区间**匹配(spec §4.5)。

    at_least=True → 成交价 ≥ threshold 算已执行(如减仓卖出价 ≥ 上沿 × 0.98);
    at_least=False → 成交价 ≤ threshold 算已执行(如回补买价 ≤ 下沿 × 1.02)。
    成交价缺失(price=None)不算匹配 —— 无价流水无法证明是按哪条预案执行的。
    """
    for t in transactions or []:
        if not isinstance(t, dict):
            continue
        if t.get("stock_code") != code:
            continue
        if str(t.get("action") or "").lower() != action:
            continue
        p = _f(t.get("price"))
        if p is None:
            continue
        if at_least and p >= threshold:
            return True
        if (not at_least) and p <= threshold:
            return True
    return False


def check_fulfillment(
    items: list[dict],
    target_klines: dict[str, list[dict]],
    transactions: list[dict],
) -> list[dict]:
    """给每个预案项补 fulfillment / fulfillment_note(不修改入参)"""
    out: list[dict] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        code = str(item.get("stock_code") or "")
        kind = str(item.get("item_kind") or "")
        direction = str(item.get("direction") or "none")
        price = _f(item.get("trigger_price"))
        high, low = _day_extremes((target_klines or {}).get(code))

        fulfillment = "pending"
        note = ""

        # 第一步:是否真的执行了(最高优先级)
        if kind in DISCIPLINE_KINDS:
            # 别动 / 未解锁类:买卖任一方向都算"动了手"(spec §4.5 第四步)
            executed = _has_txn(transactions, code, "buy") or _has_txn(transactions, code, "sell")
        elif kind == "t_sell":
            executed = _executed_at_price(
                transactions, code, "sell", price * T_SELL_TOLERANCE, at_least=True
            )
        elif kind == "t_buyback":
            executed = _executed_at_price(
                transactions, code, "buy", price * T_BUYBACK_TOLERANCE, at_least=False
            )
        elif direction == "buy":
            executed = _has_txn(transactions, code, "buy")
        elif direction == "sell":
            executed = _has_txn(transactions, code, "sell")
        else:
            # direction=none 且非纪律类(如 watch):无明确动作可判定
            executed = False

        if kind in DISCIPLINE_KINDS and executed:
            # 纪律问题优先于「不计入统计」—— 这是最该被看见的一条
            fulfillment = "executed"
            note = "⚠️ 纪律问题:昨日标记别动/未解锁,今日仍有操作"
        elif kind in DISCIPLINE_KINDS:
            # 别动 / 未解锁类:本来就不该执行 → 不计入统计(spec §4.5.4)
            fulfillment = "n_a"
            note = "别动/未解锁类,不计入兑现统计"
        elif direction == "none" or price is None:
            # 无触发价(如 watch):不参与统计
            fulfillment = "n_a"
            note = "无触发价,不计入兑现统计"
        elif executed:
            fulfillment = "executed"
            note = "已按计划执行"
        else:
            # 第二步:价格是否触及
            touched = False
            if direction == "sell" and high is not None and high >= price:
                touched = True
            if direction == "buy" and low is not None and low <= price:
                touched = True
            if touched:
                fulfillment = "touched"
                note = "价格已触及触发位,但当日无对应操作"
            else:
                fulfillment = "missed"
                note = "当日未触及触发位(不评价对错)"

        item["fulfillment"] = fulfillment
        item["fulfillment_note"] = note
        out.append(item)
    return out


def summarize_fulfillment(items: list[dict]) -> dict[str, Any]:
    """复盘段统计口径(spec §4.5.4)"""
    total = len(items or [])
    executed = touched = missed = na = 0
    discipline = 0
    for i in items or []:
        if not isinstance(i, dict):
            continue
        f = i.get("fulfillment")
        if f == "executed":
            executed += 1
            if "纪律问题" in str(i.get("fulfillment_note") or ""):
                discipline += 1
        elif f == "touched":
            touched += 1
        elif f == "missed":
            missed += 1
        elif f == "n_a":
            na += 1
    if discipline > 0:
        verdict_label, verdict_level = "存在纪律问题", "danger"
    elif touched > 0:
        verdict_label, verdict_level = "有执行缺口", "warn"
    elif executed > 0:
        verdict_label, verdict_level = "按计划执行", "ok"
    else:
        verdict_label, verdict_level = "无操作记录", "flat"
    return {
        "total": total, "executed": executed, "touched": touched,
        "missed": missed, "na": na, "discipline": discipline,
        "verdict_label": verdict_label, "verdict_level": verdict_level,
    }


__all__ = ["check_fulfillment", "summarize_fulfillment"]
