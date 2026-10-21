"""昨日预案 × 今日行情/流水 → 兑现状态(纯函数、零 IO、零 LLM)

设计文档 §4.5。

**记法**:R = 被检查的日报日(R 日报的 items 是为 R+1 定下的);
R+1 = 兑现判定日。

**诚实性**:"未触发"不评价对错。计划说"跌破 9.62 止损",当天最低 9.70
没跌破 —— 这不是"止损错了",而是"不该触发"。算成错误会污染决策档案。

**归属规则(spec §4.5.2.1,2026-10-22 澄清后为「全局三段配对」)**:
一条流水最多被一条预案消费。配对是**全局**的,不是「逐条预案各走一遍」:
  1. **第一段 · T 子项硬匹配**(按价格区间):t_sell 卖出价 ≥ 上沿×0.98、t_buyback 买价 ≤ 下沿×1.02
     —— T 子项优先于**所有**普通预案;
  2. **第二段 · 普通预案全局择优**:枚举全部同票、方向兼容、流水带价的 (预案, 流水) 候选对,
     按「成交价与触发价的绝对价差」**全局升序**贪心配对,一条流水被配走即消费;
  3. **第三段 · 无价流水兜底**:前两段配完仍有流水无归属,才轮到「成交价缺失」的流水按方向兜底
     并在 note 里披露;
  4. 纪律类(do_not/unlock)**不参与流水归属** —— 它的「executed」表示「当日有操作(违规)」,
     同一笔操作也可能同时构成别的预案的执行,两个结论都成立,不该互相吞掉。

为什么不能逐条「先到先得」:同票多条同向预案时,先遍历到的那条会抢走流水,哪怕另一条的触发价
明显更接近成交价 —— 结果是「用户实际照做的那条」被记成执行缺口,抢到的那条被记成
「已执行但价位不符」。这不是显示瑕疵,是**往复盘档案写错事实**。

为什么 T 子项要先做:只看方向时,同票多笔同向预案会把「T 回补的那笔买入」也算成「建仓预案已执行」——
那种假阳性会直接污染复盘档案,而本模块存在的意义就是不污染。

**输入范围约束**:传入的 target_klines 与 transactions **必须只含目标日(R+1)的数据**。
本模块是纯函数、零 IO,不做日期过滤(那是编排层的职责);若上游喂进多日 K 线,
多日极值会被当成单日极值 —— 这正是「假触及」的来源。

**第三态 `no_data`(2026-10-21 T6 fix round 1 / round 3 收紧)**:目标日**没有该票的行情数据**时,
既不能说「触及」也不能说「未触及」—— 那不是判定结果,是「没判定」。判 missed
等于用无知冒充事实,会把结论永久写进复盘档案。纪律类与「有流水」两条分支在更前面,
不受本态影响(有流水时仍按 executed 判)。

⚠️ **判缺按「判定所需的那一半」**:buy 看 low、sell 看 high。
半残 K 线(有 high 无 low)对 buy 项同样是无从判定,不能因为「另一半在」就放行
(round 3 实测:high=10.5/low=None 曾把 buy 项判成 missed)。
"""
from __future__ import annotations

import math
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
    """转 float;**非有限值(NaN / ±inf)一律当无效**。

    ⚠️ 与 `services/outlook_service._f` 口径统一(用 `math.isfinite`)。
    只滤 NaN 不滤 ±inf 会出**假触及**:K 线 low = -inf 时 `low <= 触发价` 恒成立 →
    buy 项被判「已触及」;触发价 = ±inf 时同理。
    """
    try:
        if v is None:
            return None
        f = float(v)
        return f if math.isfinite(f) else None
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


def _take_free(pool: list[dict[str, Any]], pred) -> dict[str, Any] | None:
    """取第一条满足 pred 且未被消费的流水,并立刻标记为已消费"""
    for t in pool:
        if t["used"] or not pred(t):
            continue
        t["used"] = True
        return t
    return None


def _assign(
    items: list[dict],
    transactions: list[dict],
) -> dict[int, tuple[dict[str, Any] | None, str]]:
    """把当日流水归属到预案项 → {item 序号: (归属到的流水, 归属说明)}

    规则见模块 docstring。**一条流水最多被一条预案消费。**
    纪律类不参与归属(它的 executed 表示违规,不是「执行了这条预案」)。

    ⚠️ **配对是全局三段(spec §4.5.2.1「配对顺序」),不是「逐条预案各走一遍」**:
      1. 第一段 · T 子项硬匹配(价格区间)—— 优先于所有普通预案;
      2. 第二段 · 普通预案**全局择优** —— 枚举全部候选对,按绝对价差全局升序贪心配对;
      3. 第三段 · 无价流水兜底 —— 前两段配完仍有流水无归属才轮到它(并披露「成交价缺失」)。
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

    # 预案分两组:T 子项(硬匹配)与普通预案(全局择优)
    t_items: list[tuple[int, str, str, float]] = []   # (idx, code, kind, 触发价)
    plain: list[tuple[int, str, str, float]] = []      # (idx, code, direction, 触发价)
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
        code = str(it.get("stock_code") or "")
        if kind in ("t_sell", "t_buyback"):
            t_items.append((idx, code, kind, price))
        else:
            plain.append((idx, code, direction, price))

    out: dict[int, tuple[dict[str, Any] | None, str]] = {}

    # ---- 第一段 · T 子项硬匹配(按价格区间,优先于所有普通预案) ----
    for idx, code, kind, price in t_items:
        if kind == "t_sell":
            thr = price * T_SELL_TOLERANCE
            hit = _take_free(pool, lambda x, code=code, thr=thr: x["code"] == code
                             and x["action"] == "sell" and x["price"] is not None
                             and x["price"] >= thr - _EPS)
            hint = "减仓成交价在计划区间内"
        else:  # t_buyback
            thr = price * T_BUYBACK_TOLERANCE
            hit = _take_free(pool, lambda x, code=code, thr=thr: x["code"] == code
                             and x["action"] == "buy" and x["price"] is not None
                             and x["price"] <= thr + _EPS)
            hint = "回补成交价在计划区间内"
        if hit is not None:
            out[idx] = (hit, hint)

    # ---- 第二段 · 普通预案全局择优 ----
    # 候选集是「(预案, 流水) 对」的**全局**集合:先枚举全部同票、方向兼容、流水带价的对,
    # 再按绝对价差**全局升序**排序后依次配对 —— 一条流水被配走即消费。
    # ⚠️ 绝不能「逐条预案各挑一条」:那会让先遍历到的预案抢走流水,
    # 把「用户实际照做的那条」记成执行缺口(往复盘档案写错事实)。
    pairs: list[tuple[float, int, int]] = []
    for idx, code, direction, price in plain:
        for j, x in enumerate(pool):
            if x["used"] or x["code"] != code or x["action"] != direction:
                continue
            if x["price"] is None:
                continue
            pairs.append((abs(x["price"] - price), idx, j))
    pairs.sort(key=lambda p: (p[0], p[1], p[2]))
    for _diff, idx, j in pairs:
        if idx in out or pool[j]["used"]:
            continue
        pool[j]["used"] = True
        out[idx] = (pool[j], "")

    # ---- 第三段 · 无价流水兜底 ----
    # 成交价缺失的流水**不能证明是哪条预案** → 只在前两段配完还有流水无归属时兜底,
    # 并在 note 里披露「成交价缺失」。
    for idx, code, direction, _price in plain:
        if idx in out:
            continue
        hit = _take_free(pool, lambda x, code=code, direction=direction: x["code"] == code
                         and x["action"] == direction and x["price"] is None)
        if hit is not None:
            out[idx] = (hit, "成交价缺失,仅按方向匹配")
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
            if tp is not None and abs(tp - price) > price * DEVIATION_TOLERANCE + _EPS:
                note += f"(成交价 {tp:.2f} 与触发价 {price:.2f} 不符)"
        else:
            # 第二步:价格是否触及
            # ⚠️ 按**判定所需的那一半**判缺:
            #   buy  看 low  → 缺 low  = 无从判定
            #   sell 看 high → 缺 high = 无从判定
            # 缺了关键的那一半就说「未触及」= 拿无知冒充事实(与 F1 同一类错误)。
            # 另一半缺不缺无所谓 —— 判定只用得到的那一半。
            needed = high if direction == "sell" else low
            if needed is None:
                fulfillment = "no_data"
                note = "目标日无行情数据,未判定"
            else:
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
    """复盘段统计口径(spec §4.5.4)

    `no_data` = 目标日无行情数据,**不计入统计**(与 n_a 同性质),
    且 verdict 不允许因为它而说成「按计划执行」——「没判定」不是「做对了」。
    """
    total = len(items or [])
    executed = touched = missed = na = no_data = 0
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
        elif f == "no_data":
            no_data += 1
    if discipline > 0:
        verdict_label, verdict_level = "存在纪律问题", "danger"
    elif touched > 0:
        verdict_label, verdict_level = "有执行缺口", "warn"
    elif no_data > 0:
        verdict_label, verdict_level = "数据不足", "warn"
    elif executed > 0:
        verdict_label, verdict_level = "按计划执行", "ok"
    else:
        verdict_label, verdict_level = "无操作记录", "flat"
    return {
        "total": total, "executed": executed, "touched": touched,
        "missed": missed, "na": na, "no_data": no_data, "discipline": discipline,
        "verdict_label": verdict_label, "verdict_level": verdict_level,
    }


__all__ = ["check_fulfillment", "summarize_fulfillment"]
