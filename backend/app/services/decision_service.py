"""确定性盯盘决策引擎(v0.9 Trading Desk)

回答七问:该买?该卖?何时做T?亏损怎么办?盈利怎么办?市场情况?现在走势?
—— 以**可执行的条件清单**给出,而不是散文。

设计文档:docs/superpowers/specs/2026-10-21-stock-decision-engine-design.md

三条铁律:
1. 纯函数、零 IO、零 LLM —— 可单测、可回测
2. 所有价格必须来自 indicators / 实时报价 / 持仓,或其显式四则运算(禁止编造)
3. 任一输入缺失 → 对应字段为 None,并写进 degraded(绝不编数字)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---- 阈值(全部来自设计文档 §6;改动必须同步改文档) ----
T_MIN_AMPLITUDE_PCT = 3.0        # G1:做 T 所需最小近 5 日平均振幅
T_WINDOW = 5                     # 做 T 观察窗口(根)
ENTRY_MIN_VOLUME_RATIO = 1.5     # C3:突破确认所需量比
POSITION_TIERS = ((45, 10), (65, 20), (10**9, 30))  # (signal.score 上界, 首仓 %)
POSITION_ADD_CAP = 60            # 加仓上限 %
MARKET_COLD_RATIO = 1.5          # 大盘普跌:跌家数 > 涨家数 × 该系数
NEAR_LIMIT_UP_PCT = 9.5          # 近涨停判定(当日涨幅 %)
ONE_WORD_LIMIT_PCT = 0.1         # 一字板:当日振幅 < 该值 %
ADD_SHARE_RATIO = 0.3            # L4:补仓股数 = 现有股数 × 该比例
MIN_KLINES_FOR_SIGNAL = 23       # 少于该根数 → 信号不可信


@dataclass(frozen=True)
class MarketContext:
    """市场环境(由 market_context_service 构造;decision_service 只读)"""
    market: dict[str, Any] = field(default_factory=dict)
    sector: dict[str, Any] = field(default_factory=dict)
    stock_flow: dict[str, Any] = field(default_factory=dict)
    relative: dict[str, Any] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionContext:
    """决策引擎的全部输入(纯数据,不含任何 IO 对象)"""
    stock_code: str
    stock_name: str | None
    indicators: dict[str, Any]
    klines: list[dict[str, Any]]
    current_price: float | None
    prev_close: float | None
    cost_basis: float | None
    shares: int
    position_status: str          # 'empty' | 'profit' | 'loss'
    env: MarketContext = field(default_factory=MarketContext)


def _f(v: Any) -> float | None:
    """安全转 float;None / 非法值 / NaN → None"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def effective_price(ctx: DecisionContext) -> float | None:
    """统一计算价:实时价优先,缺失时用最新收盘价。

    所有判定器一律用它,不得自行判断 current_price 是否为 None。
    """
    p = _f(ctx.current_price)
    if p is not None and p > 0:
        return p
    lc = _f(ctx.indicators.get("latest_close"))
    return lc if lc is not None and lc > 0 else None


def _clamped(value: float | None) -> float | None:
    return value if value is not None else None


def judge_trend(ctx: DecisionContext) -> dict[str, Any]:
    """现在的走势如何 → {"phase": 阶段, "note": 依据}"""
    ind = ctx.indicators
    channel = (ind.get("channel") or {}).get("state") or "sideways"
    ma = ind.get("ma") or {}
    ma5, ma10, ma20, ma60 = (_f(ma.get(k)) for k in ("ma5", "ma10", "ma20", "ma60"))
    all_ma = all(v is not None for v in (ma5, ma10, ma20, ma60))
    bull_ma = all_ma and ma5 > ma10 > ma20 > ma60
    bear_ma = all_ma and ma5 < ma10 < ma20 < ma60
    vp = (ind.get("volume_price") or {}).get("direction")
    boll = ind.get("boll") or {}
    boll_pos = boll.get("position")
    squeeze = bool(boll.get("squeeze"))
    kdj_zone = (ind.get("kdj") or {}).get("zone")
    vol_ratio = _f((ind.get("volume") or {}).get("ratio"))

    if channel == "up":
        if vp == "healthy_up" or boll_pos in ("touching_upper", "above_upper"):
            phase = "上涨通道·加速"
        elif vp == "liar_up_suspect" or (
            kdj_zone == "overbought" and vol_ratio is not None and vol_ratio < 0.8
        ):
            phase = "上涨通道·滞涨"
        else:
            phase = "上涨通道·延续"
    elif channel == "down":
        if vp == "panic_sell" or boll_pos in ("touching_lower", "below_lower"):
            phase = "下跌通道·破位"
        elif kdj_zone == "oversold" and bool((ind.get("stabilize") or {}).get("state")):
            phase = "下跌通道·筑底"
        else:
            phase = "下跌通道·延续"
    else:
        phase = "震荡收敛" if squeeze else "震荡"

    if bull_ma:
        ma_txt = "多头排列 MA5>MA10>MA20>MA60"
    elif bear_ma:
        ma_txt = "空头排列 MA5<MA10<MA20<MA60"
    else:
        ma_txt = "均线缠绕"
    boll_txt = {
        "touching_upper": "布林触上轨",
        "above_upper": "布林破上轨",
        "touching_lower": "布林触下轨",
        "below_lower": "布林破下轨",
        "middle": "布林中轨附近",
    }.get(boll_pos, "布林位置未知")
    vol_txt = f"量比 {vol_ratio:.2f}" if vol_ratio is not None else "量比未知"
    return {"phase": phase, "note": f"{ma_txt},{boll_txt},{vol_txt}"}


def _daily_amplitude_pct(klines: list[dict[str, Any]]) -> list[float]:
    """逐日振幅 % = (high - low) / 昨收 * 100"""
    out: list[float] = []
    for i in range(1, len(klines)):
        h = _f(klines[i].get("high"))
        low = _f(klines[i].get("low"))
        pc = _f(klines[i - 1].get("close"))
        if h is not None and low is not None and pc is not None and pc > 0:
            out.append((h - low) / pc * 100)
    return out


def _cum_change_pct(klines: list[dict[str, Any]], days: int) -> float | None:
    """近 days 个交易日累计涨跌幅 %"""
    if len(klines) < days + 1:
        return None
    a = _f(klines[-(days + 1)].get("close"))
    b = _f(klines[-1].get("close"))
    if a is None or b is None or a <= 0:
        return None
    return (b - a) / a * 100


def _unsuitable(reason: str, needs_position: bool) -> dict[str, Any]:
    return {
        "suitable": False,
        "t_high": None,
        "t_low": None,
        "amplitude_pct": None,
        "sell_trigger": "",
        "buyback_trigger": "",
        "base_position_pct": "",
        "unsuitable_signals": reason,
        "needs_position": needs_position,
    }


def judge_t_plan(ctx: DecisionContext) -> dict[str, Any]:
    """什么时候适合做 T → TPlan"""
    ind = ctx.indicators
    pos = ind.get("position") or {}
    p20 = _f(pos.get("p20"))
    p80 = _f(pos.get("p80"))
    ep = effective_price(ctx)
    needs_position = ctx.shares <= 0

    if ep is None or p20 is None or p80 is None:
        return _unsuitable("K 线不足,无法计算 T 区间", needs_position)

    # G1 近 5 日平均振幅 ≥ 3%
    amps = _daily_amplitude_pct(ctx.klines)[-T_WINDOW:]
    if not amps:
        return _unsuitable("K 线不足,无法计算振幅", needs_position)
    avg_amp = sum(amps) / len(amps)
    if avg_amp < T_MIN_AMPLITUDE_PCT:
        return _unsuitable(
            f"近 5 日平均振幅 {avg_amp:.2f}% 不足 {T_MIN_AMPLITUDE_PCT}%,做 T 赚不到差价",
            needs_position,
        )

    # G2 当日有成交
    last_vol = ctx.klines[-1].get("volume")
    if not last_vol or int(last_vol) <= 0:
        return _unsuitable("今日无成交(停牌或一字板),无法判断", needs_position)

    # G3 非一字板:近 5 日不存在振幅 < 0.1% 的交易日
    window = ctx.klines[-T_WINDOW:]
    one_word = False
    for k in window:
        h, low = _f(k.get("high")), _f(k.get("low"))
        c = _f(k.get("close"))
        if h is None or low is None or c is None or c <= 0:
            continue
        if (h - low) / c * 100 < ONE_WORD_LIMIT_PCT:
            one_word = True
            break
    if one_word:
        return _unsuitable("近 5 日出现一字板,无法做 T", needs_position)

    # G4 现价不能远低于 P20 低位带
    if ep < p20 * 0.97:
        return _unsuitable(
            f"现价已跌破 P20 低位带 {p20:.2f},下行空间不明,不建议做 T", needs_position
        )

    # 单边排除
    ma = ind.get("ma") or {}
    ma5, ma10, ma20, ma60 = (_f(ma.get(k)) for k in ("ma5", "ma10", "ma20", "ma60"))
    all_ma = all(v is not None for v in (ma5, ma10, ma20, ma60))
    bull_ma = all_ma and ma5 > ma10 > ma20 > ma60
    bear_ma = all_ma and ma5 < ma10 < ma20 < ma60
    channel = (ind.get("channel") or {}).get("state")
    up3 = _cum_change_pct(ctx.klines, 3)
    if channel == "up" and bull_ma and up3 is not None and up3 > 5:
        return _unsuitable("单边上涨,做 T 容易做飞,建议持股不动", needs_position)
    if channel == "down" and bear_ma and up3 is not None and up3 < -5:
        return _unsuitable("单边下跌,做 T 越做越低,建议只减不加", needs_position)

    # T 区间(取保守边)
    highs = [_f(k.get("high")) for k in window]
    lows = [_f(k.get("low")) for k in window]
    hi5 = max((v for v in highs if v is not None), default=None)
    lo5 = min((v for v in lows if v is not None), default=None)
    if hi5 is None or lo5 is None:
        return _unsuitable("K 线缺少最高/最低价,无法计算 T 区间", needs_position)
    t_high = min(hi5, p80)
    t_low = max(lo5, p20)
    amplitude_pct = (t_high - t_low) / ep * 100 if ep > 0 else None

    base_pct = "≥70%" if bull_ma else "≥50%"
    stop_price = _f(pos.get("stop_loss_price"))
    stop_txt = (
        f"底仓跌破 {stop_price:.2f} 元即止损,防止做 T 做飞" if stop_price is not None else ""
    )
    over_p80 = ep > p80
    sell_txt = f"冲高至 {t_high:.2f} 元附近且量能未超 5 日均量 1.5 倍时卖出 T 仓"
    if over_p80:
        sell_txt += "(现价已高于 P80,只做卖出方向)"
    buyback_txt = f"回落至 {t_low:.2f} 元附近且缩量企稳(MACD 绿柱不放大)时买回"

    return {
        "suitable": True,
        "t_high": round(t_high, 3),
        "t_low": round(t_low, 3),
        "amplitude_pct": round(amplitude_pct, 2) if amplitude_pct is not None else None,
        "sell_trigger": sell_txt,
        "buyback_trigger": buyback_txt,
        "base_position_pct": base_pct,
        "unsuitable_signals": stop_txt,
        "needs_position": needs_position,
    }
