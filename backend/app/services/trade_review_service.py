"""拟交易复核(纯函数层 · 零 IO · 零 LLM)

把「用户拟做的一笔买卖」与决策引擎的结论做**比对**,输出三档判定:
- ✅ ok              符合条件
- ⚠️ conditional     有条件可做
- ⛔ not_recommended 不建议
- ❓ unknown         数据不足(不猜)

三条铁律(与 `decision_service` 一致):
1. 纯函数、零 IO、零 LLM —— 可单测、可回测
2. 所有价格必须来自 indicators / 实时报价 / 持仓,或其显式四则运算(禁止编造)
3. 任一输入缺失 → 对应字段为 None,并写进 degraded(绝不编数字)

**为什么不重写决策算法**:做 T 时机、止盈/止损价、买入条件全部已经由
`decision_service.build_decision()` 算好了。本模块只做「拟操作 × 决策结论」
的比对,**不自己算 T 区间、不自己算止损价、不做均线/量能再判定** ——
否则会出现两个判定口径互相打架(决策卡说"现在可买",计算器说"不建议买")。

设计文档:docs/superpowers/specs/2026-10-23-calculator-trade-review-design.md
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from app.core.cost_engine import calculate_after_transaction
from app.core.instrument import degraded_note
from app.services.decision_service import (
    MIN_KLINES_FOR_SIGNAL,
    DecisionContext,
    effective_price,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注,避免运行时耦合 modules 层
    from app.modules.portfolio.service import Position


# ---- 阈值(改动必须同步改设计文档 §4.1) ----
PRICE_TOLERANCE = 0.02        # 拟成交价与建议价偏离 ≤2% = 价位合适
SELL_TRIM_RATIO = 1 / 3       # 减仓建议:每次减 1/3
T_BASE_POSITION = {"≥70%": 0.70, "≥50%": 0.50}  # 底仓比例(来自 t_plan.base_position_pct)
ADD_AMOUNT_RATIO = 0.5        # 单笔加仓金额 ≤ 持仓市值 × 该比例
AVG_COST_JUMP_PCT = 10.0      # 买入后均价升幅超过该值 → 风险标记

# do_not 清单的方向适用性:
# 决策引擎的「别动清单」目前全是**买入侧**规则(不要加仓/不要追高/不要抄底),
# 对一笔**卖出**提议不构成反对理由 —— 下跌通道里卖出是合理的。
# 只有「数据本身不可靠」类的通用规则对买卖两个方向都成立。
UNIVERSAL_DO_NOT_MARKERS = ("K 线不足", "无成交", "指标不可靠", "无法判断")


def _do_not_applies(text: str, action: str) -> bool:
    """这条「别动清单」对当前方向的拟操作是否构成反对理由"""
    if action == "buy":
        return True
    return any(marker in text for marker in UNIVERSAL_DO_NOT_MARKERS)


@dataclass(frozen=True)
class ProposedTrade:
    """用户拟做的一笔交易"""

    action: Literal["buy", "sell"]
    shares: int
    price: float


def _f(v: Any) -> float | None:
    """安全转 float;None / 非法值 / NaN → None"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _pick_suggested(actions: list[dict], kinds: tuple[str, ...]) -> dict | None:
    """在相关动作里挑一个带建议价的当"参考价位"

    kind 优先级由调用方给的顺序决定(sell: stop → exit;buy: add → entry);
    同一 kind 内优先 status=="now"。
    """
    for kind in kinds:
        cands = [
            a
            for a in actions
            if a.get("kind") == kind and _f(a.get("price")) is not None
        ]
        if not cands:
            continue
        cands.sort(key=lambda a: 0 if a.get("status") == "now" else 1)
        return cands[0]
    return None


def _unknown(
    reasons: list[str], degraded: list[str], decision: dict, t0: bool = False
) -> dict:
    """数据不足 → 不猜(verdict=unknown)"""
    return {
        "verdict": "unknown",
        "headline": "数据不足,无法判断这笔操作是否合适",
        "reasons": [],
        "blockers": list(reasons),
        "price_check": {
            "suggested": None,
            "your_price": None,
            "verdict": "unknown",
            "note": "",
        },
        "size_check": {
            "suggested_shares": None,
            "your_shares": None,
            "note": "",
        },
        "t_assessment": {
            "suitable": False,
            "t_high": None,
            "t_low": None,
            "sell_trigger": "",
            "buyback_trigger": "",
            "your_price_in_range": None,
            "max_t_shares": None,
            "note": "数据不足,无法判断是否适合做 T",
        },
        "position_after": {
            "shares": 0,
            "avg_cost": None,
            "total_cost": "0.00",
            "realized_pnl": "0.00",
        },
        "risk_flags": [],
        "degraded": _collect_degraded(decision, degraded),
        "t_directions": _empty_t_directions("数据不足,无法判断做 T 方向", t0=t0),
    }


def _collect_degraded(decision: dict, extra: list[str]) -> list[str]:
    """汇总降级来源(去重、保序)"""
    out: list[str] = []
    for src in (
        (decision.get("data_quality") or {}).get("degraded") or [],
        (decision.get("market_env") or {}).get("degraded") or [],
        extra or [],
    ):
        for s in src:
            if s and s not in out:
                out.append(s)
    return out


# ============================================================
# 做 T 方向判定(正T / 反T)
# ============================================================

# A 股最小交易单位:买入腿至少 1 手(100 股),零股无法下单
T_MIN_LOT = 100

# 现价在 T 区间 [t_low, t_high] 的相对位置 ≥ 该阈值 → 推荐反T(先卖后买)
T_RATIO_FOR_REVERSE = 0.5

T_PLUS_1_NOTE = (
    "A 股 T+1:当天买入的股票当天不能卖出。"
    "正T 的卖出腿只能用预留的老底仓承接;"
    "反T 持股数不变,买回的部分当天也不能再卖。"
)

# T+0 品种(跨境/黄金/商品 ETF):当日买入的份额当天即可卖出
T0_NOTE = (
    "该品种为 T+0(当日可回转):当天买入的份额当天就能卖出,"
    "正T 的卖出腿无需预留老底仓;"
    "反T 持股数不变,买回的部分当天也可以再卖。"
    "(具体以交易软件显示的品种属性为准)"
)


def _floor_lot(shares: int) -> int:
    """向下取整到整手(100 股的倍数)—— A 股买入腿至少 1 手"""
    if shares <= 0:
        return 0
    return (shares // T_MIN_LOT) * T_MIN_LOT


def _empty_t_directions(reason: str, t0: bool = False) -> dict:
    """两个方向都不可用时的骨架(照常显示,灰显 + 说明原因)"""
    return {
        "reverse": {
            "key": "reverse",
            "label": "反T · 先卖后买",
            "applicable": False,
            "reason_code": "unknown",
            "prerequisite": reason,
            "max_shares": None,
            "max_amount": None,
            "steps": [],
            "status_text": reason,
        },
        "forward": {
            "key": "forward",
            "label": "正T · 先买后卖",
            "applicable": False,
            "reason_code": "unknown",
            "prerequisite": reason,
            "max_shares": None,
            "max_amount": None,
            "steps": [],
            "status_text": reason,
        },
        "recommended": None,
        "recommend_reason": reason,
        "your_leg": None,
        "t_plus_one_note": T0_NOTE if t0 else T_PLUS_1_NOTE,
    }


def _build_t_directions(
    *,
    t_plan: dict,
    shares_before: int,
    ep: float | None,
    p80: float | None,
    cash_available: Decimal | None,
    proposed: ProposedTrade,
    t0: bool = False,
) -> dict:
    """正T / 反T 两个方向的适用性、股数上限与推荐

    **术语写死(不许含糊)**:
    - 反T(reverse)= 先卖后买(高抛低吸):卖老仓 → 回落买回。持股数不变。
    - 正T(forward)= 先买后卖(低吸高抛):低位买入 → 冲高卖出。

    **两者的差别只有两点**:
    1. 资金:反T 卖出所得即可覆盖买回(区间上沿 > 下沿),不额外占用资金;
       正T 的买入腿要先掏钱 → 受「账户可用资金 ÷ 买价」限制。
    2. 顺序:反T 先卖(不用等),正T 先买。

    **持仓约束按品种分流(t0)**:
    - T+1(股票、境内股票ETF):卖出腿只能用老底仓(当天买的当天不能卖),
      所以两个方向的股数上限都取「可动 T 仓」= floor(持股 × (1 - 底仓比例))。
    - T+0(跨境/黄金/商品 ETF):当天买入的份额当天就能卖 →
      **正T 的卖出腿无需预留老底仓**,上限只受「可用资金 ÷ 买价」约束;
      反T 仍受可动 T 仓约束(不能把仓位卖光)。

    **缺数据不猜**:账户可用资金没填 → 正T 的股数上限给 None(而不是 0),
    并在 prerequisite 里写明「未填写可用资金」。
    """
    suitable = bool(t_plan.get("suitable"))
    t_high = _f(t_plan.get("t_high"))
    t_low = _f(t_plan.get("t_low"))
    base_pct = str(t_plan.get("base_position_pct") or "")
    base_ratio = T_BASE_POSITION.get(base_pct)

    # ---- 共同的持仓约束:可动 T 仓(底仓需保留 base_ratio) ----
    # 用 Decimal 算,避免 floats 在 0.5 / 0.7 上出边界误差
    # (如 999 * 0.3 = 299.69999999999999 → 截断成 299 → 少算 100 股)
    max_t_shares: int | None = None
    if base_ratio is not None and shares_before > 0:
        movable = Decimal(shares_before) * (Decimal(1) - Decimal(str(base_ratio)))
        max_t_shares = _floor_lot(int(movable))

    # ---- 正T 的买入参考价:用户拟买价优先,否则用区间下沿(计划低吸位) ----
    if proposed.action == "buy":
        buy_ref: float | None = float(proposed.price)
    else:
        buy_ref = t_low

    # ---- 资金能买多少股(正T 专用) ----
    cash_shares: int | None = None
    if cash_available is not None and buy_ref is not None and buy_ref > 0:
        cash_shares = _floor_lot(
            int(Decimal(cash_available) / Decimal(str(buy_ref)))
        )

    # ==================== 反T(先卖后买) ====================
    reverse: dict = {
        "key": "reverse",
        "label": "反T · 先卖后买",
        "applicable": False,
        "reason_code": "unknown",
        "prerequisite": "",
        "max_shares": None,
        "max_amount": None,
        "steps": [],
        "status_text": "",
    }
    reverse_block: str | None = None
    reverse_code = "unknown"
    # 前置条件拆成两条链:
    #   common   —— 与品种无关(不适合做 T / 缺 T 区间 / 无持仓),两个方向都受限
    #   position —— 与底仓相关(缺底仓比例 / 可动 T 仓不足 1 手)
    #               T+1 时正T 也受限(卖腿要预留老底仓);T+0 时正T 不受此限
    common_block: str | None = None
    common_code = "unknown"
    position_block: str | None = None
    position_code = "unknown"
    if not suitable:
        common_block = str(t_plan.get("unsuitable_signals") or "当前不适合做 T")
        common_code = "not_suitable"
    elif t_high is None or t_low is None or t_high <= t_low:
        common_block = "缺 T 区间,无法测算做 T 的股数"
        common_code = "no_t_range"
    elif shares_before <= 0:
        common_block = "当前无底仓,做 T 前需先建仓"
        common_code = "no_position"
    elif max_t_shares is None:
        position_block = "缺底仓比例,无法测算可动 T 仓"
        position_code = "no_base_ratio"
    elif max_t_shares < T_MIN_LOT:
        position_block = f"底仓需保留 {base_pct},可动 T 仓不足 1 手"
        position_code = "base_too_large"
    reverse_block = common_block or position_block
    reverse_code = common_code if common_block else position_code
    if reverse_block:
        reverse["reason_code"] = reverse_code
        reverse["prerequisite"] = reverse_block
        reverse["status_text"] = reverse_block
    else:
        n = max_t_shares or 0
        reverse["applicable"] = True
        reverse["reason_code"] = "ok"
        reverse["max_shares"] = n
        reverse["max_amount"] = (
            str((Decimal(str(n)) * Decimal(str(t_high))).quantize(Decimal("0.01")))
            if t_high is not None
            else None
        )
        reverse["prerequisite"] = (
            f"需有老底仓可卖:可动 {n} 股(底仓保留 {base_pct}),卖出所得即可覆盖买回"
        )
        reverse["steps"] = [
            {
                "role": "sell",
                "text": f"冲高至 {t_high:.2f} 元附近卖出 {n} 股(老仓)",
            },
            {
                "role": "buyback",
                "text": f"回落至 {t_low:.2f} 元附近买回 {n} 股",
            },
        ]
        reverse["status_text"] = (
            f"可做 {n} 股:冲高 {t_high:.2f} 元卖 {n} 股,回落 {t_low:.2f} 元买回 {n} 股"
            "(持股数不变)"
        )

    # ==================== 正T(先买后卖) ====================
    forward: dict = {
        "key": "forward",
        "label": "正T · 先买后卖",
        "applicable": False,
        "reason_code": "unknown",
        "prerequisite": "",
        "max_shares": None,
        "max_amount": None,
        "steps": [],
        "status_text": "",
    }
    forward_block: str | None = None
    forward_code = "unknown"
    if common_block:
        # 与品种无关的前提不成立 → 两个方向一起不成立
        forward_block = common_block
        forward_code = common_code
    elif not t0 and position_block:
        # T+1:卖腿只能用预留老底仓 → 底仓约束同样卡正T
        # (T+0 时正T 的卖腿可用当日买入的份额,不受此限)
        forward_block = position_block
        forward_code = position_code
    elif cash_available is None:
        forward_block = "未填写账户可用资金,无法测算正T 股数"
        forward_code = "no_cash"
    elif cash_shares is None or cash_shares < T_MIN_LOT:
        forward_block = (
            f"可用资金 {Decimal(cash_available):.2f} 元不足以买入 1 手"
            f"(参考价 {buy_ref:.2f} 元)"
            if buy_ref is not None
            else "可用资金不足以买入 1 手"
        )
        forward_code = "cash_too_little"
    else:
        # T+0:卖腿可用当日买入的份额 → 不受可动 T 仓约束,只受资金约束
        # T+1:卖腿要用预留老底仓 → 取两者较小
        n = cash_shares if t0 else min(max_t_shares or 0, cash_shares)
        n = _floor_lot(n)
        if n < T_MIN_LOT:
            forward_block = "可动 T 仓与可用资金都不足 1 手"
            forward_code = "cash_too_little"
        else:
            amount = (Decimal(str(n)) * Decimal(str(buy_ref))).quantize(Decimal("0.01"))
            forward["applicable"] = True
            forward["reason_code"] = "ok"
            forward["max_shares"] = n
            forward["max_amount"] = str(amount)
            if t0:
                forward["prerequisite"] = (
                    f"买入腿需占用资金 {amount:.2f} 元"
                    "(T+0 品种,卖出腿可用当日买入的份额,无需预留老底仓)"
                )
                sell_leg_text = f"冲高至 {t_high:.2f} 元附近卖出当日买入的 {n} 股"
                forward["status_text"] = (
                    f"可做 {n} 股:回落 {buy_ref:.2f} 元买 {n} 股(占资金 {amount:.2f} 元),"
                    f"冲高 {t_high:.2f} 元卖出当日买入的 {n} 股"
                )
            else:
                forward["prerequisite"] = (
                    f"需有老底仓承接卖腿(可动 {max_t_shares} 股,底仓保留 {base_pct}),"
                    f"且买入腿需占用资金 {amount:.2f} 元"
                )
                sell_leg_text = f"冲高至 {t_high:.2f} 元附近卖出老底仓 {n} 股"
                forward["status_text"] = (
                    f"可做 {n} 股:回落 {buy_ref:.2f} 元买 {n} 股(占资金 {amount:.2f} 元),"
                    f"冲高 {t_high:.2f} 元卖老底仓 {n} 股"
                )
            forward["steps"] = [
                {
                    "role": "buy",
                    "text": f"回落至 {buy_ref:.2f} 元附近买入 {n} 股(占资金 {amount:.2f} 元)",
                },
                {
                    "role": "sell",
                    "text": sell_leg_text,
                },
            ]

    if forward_block:
        forward["reason_code"] = forward_code
        forward["prerequisite"] = forward_block
        forward["status_text"] = forward_block

    # ==================== 推荐哪个方向 ====================
    reverse_ok = bool(reverse["applicable"])
    forward_ok = bool(forward["applicable"])
    recommended: str | None = None
    reason = ""

    if reverse_ok and forward_ok:
        if ep is None:
            reason = "缺少现价,无法判断更适合哪个方向"
        elif p80 is not None and ep > p80:
            recommended = "reverse"
            reason = f"现价 {ep:.2f} 元高于 P80 分位 {p80:.2f} 元,冲高卖出更稳妥"
        elif t_high is not None and ep >= t_high:
            recommended = "reverse"
            reason = f"现价 {ep:.2f} 元已达 T 区间上沿 {t_high:.2f} 元,先卖后买更稳妥"
        elif t_low is not None and ep <= t_low:
            recommended = "forward"
            reason = f"现价 {ep:.2f} 元已到 T 区间下沿 {t_low:.2f} 元,先买后卖更占优"
        elif t_high is not None and t_low is not None and t_high > t_low:
            ratio = (ep - t_low) / (t_high - t_low)
            recommended = "reverse" if ratio >= T_RATIO_FOR_REVERSE else "forward"
            reason = (
                f"现价 {ep:.2f} 元位于 T 区间 {t_low:.2f}~{t_high:.2f} 元的"
                f"{ratio * 100:.0f}% 位置,"
                + (
                    "偏上沿,先卖后买更稳妥"
                    if recommended == "reverse"
                    else "偏下沿,先买后卖更占优"
                )
            )
        else:
            reason = "T 区间无效,无法判断更适合哪个方向"
    elif reverse_ok:
        recommended = "reverse"
        reason = f"正T 当前不可用({forward_block}),只能做反T"
    elif forward_ok:
        recommended = "forward"
        reason = f"反T 当前不可用({reverse_block}),只能做正T"
    else:
        reason = reverse_block or forward_block or "当前不适合做 T"

    # ==================== 你拟的这笔落在哪条腿 ====================
    your_leg: str | None = None
    if recommended == "reverse":
        your_leg = "reverse.sell" if proposed.action == "sell" else "reverse.buyback"
    elif recommended == "forward":
        your_leg = "forward.buy" if proposed.action == "buy" else "forward.sell"

    return {
        "reverse": reverse,
        "forward": forward,
        "recommended": recommended,
        "recommend_reason": reason,
        "your_leg": your_leg,
        "t_plus_one_note": T0_NOTE if t0 else T_PLUS_1_NOTE,
    }


def review_trade(
    ctx: DecisionContext,
    decision: dict,
    proposed: ProposedTrade,
    position: Position | None = None,
    cash_available: Decimal | None = None,
) -> dict:
    """拟操作 × 决策结论 → 三档判定 + 做 T 评估 + 风险

    Args:
        ctx: 决策引擎上下文(纯数据)
        decision: `build_decision(ctx)` 的输出
        proposed: 用户拟做的交易
        position: 当前持仓(可为 None = 空仓)
        cash_available: 账户可用资金(元)。None = 未填写 →
            正T 的股数上限给 None(不猜),并在 prerequisite 里说明。

    Returns:
        见设计文档 §4.2 的结构。verdict ∈ ok / conditional / not_recommended / unknown。
    """
    degraded: list[str] = []
    reasons: list[str] = []
    blockers: list[str] = []
    risk_flags: list[str] = []

    # 品种相关:表外 ETF 走保守口径 → 必须明说,不能假装已知
    unknown_etf_note = degraded_note(ctx.stock_code)
    if unknown_etf_note:
        degraded.append(unknown_etf_note)

    ind = ctx.indicators or {}
    pos_ind = ind.get("position") or {}
    p20 = _f(pos_ind.get("p20"))
    p80 = _f(pos_ind.get("p80"))
    kline_count = len(ctx.klines or [])

    # ---- 1. 数据充分性(缺数据 → 不猜) ----
    if p20 is None or p80 is None:
        degraded.append("分位带 P20/P80 缺失,无法给出判定")
    if kline_count < MIN_KLINES_FOR_SIGNAL:
        degraded.append(f"K 线不足 {MIN_KLINES_FOR_SIGNAL} 根,信号不可靠")
    if proposed.shares <= 0 or proposed.price <= 0:
        degraded.append("拟交易的股数或价格无效")
    if p20 is None or p80 is None or kline_count < MIN_KLINES_FOR_SIGNAL:
        blockers.append("数据不足,不给结论")
        return _unknown(blockers, degraded, decision, t0=ctx.t0)

    actions = list(decision.get("actions") or [])
    ep = effective_price(ctx)
    your_price = float(proposed.price)

    # ---- 持仓(现取,不入缓存) ----
    shares_before = int(getattr(position, "shares", 0) or 0)
    total_cost_dec = Decimal(str(getattr(position, "total_cost", 0) or 0))
    total_cost_before = float(total_cost_dec)
    # 均价用未量化的 total_cost / shares(与事件溯源链的 ChainState.avg_cost 同口径,
    # 避免 3 位量化在千股级持仓上放大成几毛钱的误差)
    avg_cost_before = (
        total_cost_dec / shares_before if shares_before > 0 else None
    )
    avg_cost_before_f = float(avg_cost_before) if avg_cost_before is not None else None

    if proposed.action == "buy":
        relevant_kinds = ("entry", "add")
        opposite_kinds = ("exit", "stop")
    else:
        relevant_kinds = ("exit", "stop")
        opposite_kinds = ("entry", "add")

    relevant = [a for a in actions if a.get("kind") in relevant_kinds]
    opposite = [a for a in actions if a.get("kind") in opposite_kinds]

    # ---- 2. 方向结论 ----
    verdict = "conditional"
    if any(a.get("status") == "now" for a in relevant):
        verdict = "ok"
    elif any(a.get("status") == "armed" for a in relevant):
        verdict = "conditional"
    elif any(a.get("status") == "blocked" for a in relevant):
        verdict = "not_recommended"
    else:
        # 无相关动作:看反向信号
        opp_now = [a for a in opposite if a.get("status") == "now"]
        if proposed.action == "buy" and opp_now:
            verdict = "not_recommended"
            for a in opp_now:
                blockers.append(f"当前信号指向卖出({a.get('label')}):{a.get('condition')}")
        elif proposed.action == "sell" and opp_now:
            verdict = "conditional"
            for a in opp_now:
                reasons.append(f"当前信号偏向加仓({a.get('label')}),此时卖出属逆势")
        else:
            verdict = "conditional"
            blockers.append(
                "当前没有建仓触发条件(未出现企稳 / 超跌反弹 / 放量突破信号)"
                if proposed.action == "buy"
                else "当前没有卖出触发条件(既未到止盈位,也未跌破止损位)"
            )

    # 相关动作里 now/armed 的依据
    for a in relevant:
        status = a.get("status")
        if status == "now":
            reasons.append(f"当前有 {a.get('label')} 条件:{a.get('condition')}")
        elif status == "armed":
            reasons.append(f"待触发({a.get('label')}):{a.get('condition')}")
        elif status == "blocked":
            missing = a.get("missing") or a.get("basis") or []
            blockers.append(
                f"{a.get('label')} 条件不成立:"
                + (";".join(str(m) for m in missing) if missing else str(a.get("condition") or ""))
            )

    # ---- 3. 价位检查 ----
    suggested_action = _pick_suggested(relevant, relevant_kinds)
    suggested_price = _f(suggested_action.get("price")) if suggested_action else None
    price_check = {
        "suggested": round(suggested_price, 3) if suggested_price is not None else None,
        "your_price": round(your_price, 3),
        "verdict": "unknown",
        "note": "",
    }
    if suggested_action is not None and suggested_action.get("kind") == "stop":
        # 止损是「纪律触发」(现价已跌破止损位才触发),卖出价由纪律决定,
        # 不做价位容差比较 —— 否则止损卖出会被误判成「卖早了」。
        price_check["verdict"] = "ok"
        price_check["note"] = (
            f"已跌破止损位 {suggested_price:.2f} 元,卖出价按止损纪律执行,不看价位容差"
        )
    elif suggested_price is None or suggested_price <= 0:
        degraded.append("没有可参考的建议价位,跳过价位检查")
    else:
        diff_pct = (your_price / suggested_price - 1) * 100
        if proposed.action == "buy":
            within = your_price <= suggested_price * (1 + PRICE_TOLERANCE)
            if within:
                price_check["verdict"] = "ok"
                price_check["note"] = (
                    f"建议 {suggested_price:.2f} 元附近,你的 {your_price:.2f} 元"
                    + (
                        f"低 {abs(diff_pct):.2f}%,价位更划算"
                        if diff_pct < 0
                        else "在容差内"
                    )
                )
            else:
                price_check["verdict"] = "conditional"
                price_check["note"] = (
                    f"比建议价 {suggested_price:.2f} 元高 {diff_pct:.2f}%,追高风险"
                )
        else:
            within = your_price >= suggested_price * (1 - PRICE_TOLERANCE)
            if within:
                price_check["verdict"] = "ok"
                price_check["note"] = (
                    f"建议 {suggested_price:.2f} 元附近,你的 {your_price:.2f} 元"
                    + (
                        f"高 {diff_pct:.2f}%,卖价不错"
                        if diff_pct > 0
                        else "在容差内"
                    )
                )
            else:
                price_check["verdict"] = "conditional"
                price_check["note"] = (
                    f"比建议价 {suggested_price:.2f} 元低 {abs(diff_pct):.2f}%,价差没拿到"
                )
        if price_check["verdict"] == "conditional":
            blockers.append(price_check["note"])

    # ---- 4. 数量检查 ----
    size_check = {
        "suggested_shares": None,
        "your_shares": proposed.shares,
        "note": "",
    }
    size_issue = False
    stop_action = next(
        (a for a in relevant if a.get("kind") == "stop" and a.get("status") == "now"),
        None,
    )
    if proposed.action == "sell":
        trim = int(shares_before * SELL_TRIM_RATIO)
        size_check["suggested_shares"] = trim
        if stop_action is not None:
            size_check["note"] = "已触发止损,数量由止损纪律决定"
        elif shares_before > 0:
            notes: list[str] = []
            if proposed.shares == shares_before:
                notes.append("清仓是重大决策,当前无止损触发")
            if proposed.shares > trim:
                notes.append(f"建议分批减仓,每次 1/3({trim} 股)")
            if notes:
                size_check["note"] = ";".join(notes)
                blockers.append(size_check["note"])
                size_issue = True
    else:
        market_value = (
            (ep * shares_before)
            if ep is not None and shares_before > 0
            else total_cost_before
        )
        amount = your_price * proposed.shares
        if market_value > 0 and amount > market_value * ADD_AMOUNT_RATIO:
            size_check["note"] = (
                f"单笔加仓 {amount:.2f} 元超过持仓市值 {market_value:.2f} 元的一半"
            )
            blockers.append(size_check["note"])
            risk_flags.append("单笔加仓过大")
            size_issue = True

    # ---- 5. 冲突项(do_not) ----
    down_channel_conflict = False
    do_not_hit = False
    for item in decision.get("do_not") or []:
        text = str(item)
        if not _do_not_applies(text, proposed.action):
            # 买入侧的「别动」规则对卖出提议不成立(下跌通道里卖出是合理的)
            continue
        blockers.append(text)
        do_not_hit = True
        if "下跌通道" in text and proposed.action == "buy":
            down_channel_conflict = True

    # ---- 6. 止损检查 ----
    stop = decision.get("stop_loss") or {}
    stop_price = _f(stop.get("price"))
    if stop_price is not None and ep is not None and ep < stop_price:
        if proposed.action == "buy":
            verdict = "not_recommended"
            blockers.append(f"现价 {ep:.2f} 元已跌破止损位 {stop_price:.2f} 元,不应加仓")
        else:
            reasons.append(f"现价 {ep:.2f} 元已跌破止损位 {stop_price:.2f} 元,本次卖出符合止损纪律")

    # ---- 7. 做 T 评估(完全复用 t_plan) ----
    t_plan = decision.get("t_plan") or {}
    t_high = _f(t_plan.get("t_high"))
    t_low = _f(t_plan.get("t_low"))
    t_assessment = {
        "suitable": bool(t_plan.get("suitable")),
        "t_high": round(t_high, 3) if t_high is not None else None,
        "t_low": round(t_low, 3) if t_low is not None else None,
        "sell_trigger": str(t_plan.get("sell_trigger") or ""),
        "buyback_trigger": str(t_plan.get("buyback_trigger") or ""),
        "your_price_in_range": None,
        "max_t_shares": None,
        "note": "",
    }
    # ---- 7b. 正T / 反T 方向判定(新增) ----
    t_directions = _build_t_directions(
        t_plan=t_plan,
        shares_before=shares_before,
        ep=ep,
        p80=p80,
        cash_available=cash_available,
        proposed=proposed,
        t0=ctx.t0,
    )
    if cash_available is None and t_plan.get("suitable"):
        degraded.append("未填写账户可用资金,正T 股数无法测算")
    if not t_assessment["suitable"]:
        t_assessment["note"] = str(t_plan.get("unsuitable_signals") or "当前不适合做 T")
        if t_plan.get("needs_position"):
            t_assessment["note"] += "(当前无底仓,做 T 前需先建仓)"
    else:
        if t_high is not None and t_low is not None:
            t_assessment["your_price_in_range"] = t_low <= your_price <= t_high
        base_ratio = T_BASE_POSITION.get(str(t_plan.get("base_position_pct") or ""))
        if base_ratio is not None and shares_before > 0:
            max_t = int(shares_before * (1 - base_ratio))
            t_assessment["max_t_shares"] = max_t
            if proposed.action == "sell" and proposed.shares > max_t:
                t_assessment["note"] = (
                    f"可动 T 仓上限 {max_t} 股(底仓需保留 {t_plan.get('base_position_pct')}),"
                    f"你拟卖 {proposed.shares} 股,超出部分属于减仓/清仓,不是做 T"
                )
                blockers.append(t_assessment["note"])
        if proposed.action == "sell" and t_high is not None and your_price >= t_high * 0.98:
            t_assessment["note"] = (
                t_assessment["note"] + " | " if t_assessment["note"] else ""
            ) + f"你的 {your_price:.2f} 元接近 T 高点 {t_high:.2f} 元,价位适合 T 的卖出腿"
        if proposed.action == "buy" and t_low is not None and your_price <= t_low * 1.02:
            t_assessment["note"] = (
                t_assessment["note"] + " | " if t_assessment["note"] else ""
            ) + f"你的 {your_price:.2f} 元接近 T 低点 {t_low:.2f} 元,价位适合 T 的买回腿"

    # ---- 8. 交易后持仓 ----
    position_after = {
        "shares": 0,
        "avg_cost": None,
        "total_cost": "0.00",
        "realized_pnl": "0.00",
    }
    try:
        result = calculate_after_transaction(
            shares_before=shares_before,
            cost_before=Decimal(str(avg_cost_before if avg_cost_before is not None else 0)),
            action=proposed.action,
            tx_shares=proposed.shares,
            tx_price=Decimal(str(proposed.price)),
            fees=None,  # D3:不启用费用模型
        )
        position_after["shares"] = result["shares_after"]
        position_after["total_cost"] = str(result["total_cost_after"])
        position_after["realized_pnl"] = str(result["realized_pnl_net"])
        cost_after = result["cost_after"]
        position_after["avg_cost"] = (
            str(cost_after.quantize(Decimal("0.001"))) if cost_after is not None else None
        )
        if proposed.action == "buy" and cost_after is not None and avg_cost_before_f:
            jump = (float(cost_after) / avg_cost_before_f - 1) * 100
            if jump > AVG_COST_JUMP_PCT:
                risk_flags.append(f"买入后均价上升 {jump:.1f}%")
        if proposed.action == "sell" and result["shares_after"] == 0:
            risk_flags.append("清仓")
    except ValueError as e:
        degraded.append(f"交易后试算失败:{e}")

    # ---- 9. verdict 取最严 ----
    # ok < conditional < not_recommended < unknown
    order = {"ok": 0, "conditional": 1, "not_recommended": 2, "unknown": 3}

    def _worse(current: str, candidate: str) -> str:
        return candidate if order[candidate] > order[current] else current

    if down_channel_conflict:
        verdict = "not_recommended"
    if price_check["verdict"] == "conditional":
        verdict = _worse(verdict, "conditional")
    if size_issue:
        verdict = _worse(verdict, "conditional")
    if do_not_hit:
        verdict = _worse(verdict, "conditional")
    if any(a.get("status") == "blocked" for a in relevant):
        # 有候选被明确否决 → 至少降一档
        verdict = _worse(verdict, "conditional")

    # ---- 10. headline ----
    verdict_label = {
        "ok": "符合条件",
        "conditional": "有条件可做",
        "not_recommended": "不建议",
        "unknown": "数据不足",
    }[verdict]
    decision_headline = str(decision.get("headline") or "")
    headline = f"{verdict_label} · {decision_headline}" if decision_headline else verdict_label

    return {
        "verdict": verdict,
        "headline": headline,
        "reasons": reasons,
        "blockers": blockers,
        "price_check": price_check,
        "size_check": size_check,
        "t_assessment": t_assessment,
        "position_after": position_after,
        "risk_flags": risk_flags,
        "degraded": _collect_degraded(decision, degraded),
        "t_directions": t_directions,
    }


__all__ = [
    "ProposedTrade",
    "review_trade",
    "PRICE_TOLERANCE",
    "SELL_TRIM_RATIO",
    "T_BASE_POSITION",
    "ADD_AMOUNT_RATIO",
    "AVG_COST_JUMP_PCT",
    "T_MIN_LOT",
    "T_RATIO_FOR_REVERSE",
    "T_PLUS_1_NOTE",
]
