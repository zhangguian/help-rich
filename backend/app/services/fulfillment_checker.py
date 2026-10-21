"""昨日预案 × 今日行情/流水 → 兑现状态(纯函数、零 IO、零 LLM)

设计文档 §4.5。

**记法**:R = 被检查的日报日(R 日报的 items 是为 R+1 定下的);
R+1 = 兑现判定日。

**诚实性**:"未触发"不评价对错。计划说"跌破 9.62 止损",当天最低 9.70
没跌破 —— 这不是"止损错了",而是"不该触发"。算成错误会污染决策档案。

**归属规则(spec §4.5.3 第一步细化,2026-10-21 T4 评审后补)**:
一条流水最多被一条预案消费。
  1. **T 子项硬匹配**(按价格区间):t_sell 卖出价 ≥ 上沿×0.98、t_buyback 买价 ≤ 下沿×1.02;
  2. **其余预案按方向**匹配**尚未被消费**的流水,多条候选时取「成交价与触发价最接近」的一条;
  3. 成交价缺失的流水**不能证明是哪条预案** → 只在没有带价候选时兜底,并在 note 里披露;
  4. 纪律类(do_not/unlock)**不参与流水归属** —— 它的「executed」表示「当日有操作(违规)」,
     同一笔操作也可能同时构成别的预案的执行,两个结论都成立,不该互相吞掉。

为什么:只看方向时,同票多笔同向预案会把「T 回补的那笔买入」也算成「建仓预案已执行」——
那种假阳性会直接污染复盘档案,而本模块存在的意义就是不污染。

**输入范围约束**:传入的 target_klines 与 transactions **必须只含目标日(R+1)的数据**。
本模块是纯函数、零 IO,不做日期过滤(那是编排层的职责);若上游喂进多日 K 线,
多日极值会被当成单日极值 —— 这正是「假触及」的来源。
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

# 成交价与触发价偏离超过这个比例 → 在 note 里披露
# (「已执行」不等于「按计划价位执行」——追高买、提前卖都要看得见)
DEVIATION_TOLERANCE = 0.03

# 阈值比较的浮点容差:9.2 × 1.02 = 9.383999999999999 < 9.384,
# 不加容差会漏判「恰好按计划价位成交」的边界
_EPS = 1e-9


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


def _assign(
    items: list[dict],
    transactions: list[dict],
) -> dict[int, tuple[dict[str, Any] | None, str]]:
    """把当日流水归属到预案项 → {item 序号: (归属到的流水, 归属说明)}

    规则见模块 docstring。**一条流水最多被一条预案消费。**
    纪律类不参与归属(它的 executed 表示违规,不是「执行了这条预案」)。
    """
    pool: list[dict[str, Any]] = []
    for t in transactions or []:
        if not isinstance(t, dict):
            continue
        code = str(t.get("stock_code") or "")
        action = str(t.get("action") or "").lower()
        if not code or not action:
            continue
        pool.append({
            "code": code, "action": action,
            "price": _f(t.get("price")), "used": False,
        })

    def _take(pred) -> dict[str, Any] | None:
        for t in pool:
            if t["used"] or not pred(t):
                continue
            t["used"] = True
            return t
        return None

    plan: list[tuple[int, int, str, str, str, float | None]] = []
    for idx, it in enumerate(items or []):
        if not isinstance(it, dict):
            continue
        kind = str(it.get("item_kind") or "")
        if kind in DISCIPLINE_KINDS:
            continue  # 纪律类不参与归属
        direction = str(it.get("direction") or "none")
        price = _f(it.get("trigger_price"))
        if price is None or direction not in ("buy", "sell"):
            continue  # 无触发价/无方向 → n_a,不占流水
        prio = 1 if kind in ("t_sell", "t_buyback") else 2
        plan.append((prio, idx, str(it.get("stock_code") or ""), kind, direction, price))
    plan.sort(key=lambda x: (x[0], x[1]))

    out: dict[int, tuple[dict[str, Any] | None, str]] = {}
    for _prio, idx, code, kind, direction, price in plan:
        if kind == "t_sell":
            thr = price * T_SELL_TOLERANCE
            t = _take(lambda x, code=code, thr=thr: x["code"] == code and x["action"] == "sell"
                      and x["price"] is not None and x["price"] >= thr - _EPS)
            if t is not None:
                out[idx] = (t, "减仓成交价在计划区间内")
            continue
        if kind == "t_buyback":
            thr = price * T_BUYBACK_TOLERANCE
            t = _take(lambda x, code=code, thr=thr: x["code"] == code and x["action"] == "buy"
                      and x["price"] is not None and x["price"] <= thr + _EPS)
            if t is not None:
                out[idx] = (t, "回补成交价在计划区间内")
            continue
        # 其余预案:按方向匹配尚未被消费的流水,多条候选时取价差最小的
        best: dict[str, Any] | None = None
        best_diff: float | None = None
        for x in pool:
            if x["used"] or x["code"] != code or x["action"] != direction:
                continue
            if x["price"] is None:
                continue
            diff = abs(x["price"] - price)
            if best_diff is None or diff < best_diff:
                best, best_diff = x, diff
        if best is not None:
            best["used"] = True
            out[idx] = (best, "")
            continue
        # 兜底:没有带价候选 → 方向匹配一条(成交价缺失,不能证明归属 → note 里披露)
        t = _take(lambda x, code=code, direction=direction: x["code"] == code and x["action"] == direction)
        if t is not None:
            out[idx] = (t, "成交价缺失,仅按方向匹配")
    return out


def check_fulfillment(
    items: list[dict],
    target_klines: dict[str, list[dict]],
    transactions: list[dict],
) -> list[dict]:
    """给每个预案项补 fulfillment / fulfillment_note(不修改入参)"""
    assign = _assign(items, transactions)
    out: list[dict] = []
    for idx, raw in enumerate(items or []):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        code = str(item.get("stock_code") or "")
        kind = str(item.get("item_kind") or "")
        direction = str(item.get("direction") or "none")
        price = _f(item.get("trigger_price"))
        high, low = _day_extremes((target_klines or {}).get(code))
        txn, hint = assign.get(idx, (None, ""))

        if kind in DISCIPLINE_KINDS:
            # 纪律问题优先于「不计入统计」—— 这是最该被看见的一条
            if _has_txn(transactions, code, "buy") or _has_txn(transactions, code, "sell"):
                fulfillment = "executed"
                note = "⚠️ 纪律问题:昨日标记别动/未解锁,今日仍有操作"
            else:
                fulfillment = "n_a"
                note = "别动/未解锁类,不计入兑现统计"
        elif direction == "none" or price is None:
            # 无触发价(如 watch):不参与统计
            fulfillment = "n_a"
            note = "无触发价,不计入兑现统计"
        elif txn is not None:
            fulfillment = "executed"
            note = f"已按计划执行({hint})" if hint else "已按计划执行"
            tp = txn.get("price")
            if tp is not None and abs(tp - price) > price * DEVIATION_TOLERANCE:
                note += f"(成交价 {tp:.2f} 与触发价 {price:.2f} 不符)"
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
