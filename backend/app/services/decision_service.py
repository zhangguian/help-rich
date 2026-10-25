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

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from app.core.cost_engine import TradeFees, buy_fee, sell_fee

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

# ---- v0.10 补维度阈值(设计文档 §6.8) ----
HOLD_DAYS_LIMIT = 20             # 持有超期阈值(自然日,约合 14 个交易日)
CONCENTRATION_WARN_PCT = 30      # 持仓成本占比 ≥ 此值 → 集中度偏高
CONCENTRATION_STRONG_PCT = 50    # 持仓成本占比 ≥ 此值 → 集中度过高
T_SPREAD_MIN_MULTIPLE = 2        # 做 T 预期差价需 ≥ 2× 往返费用率才算划算

# ---- v0.10 网格建议阈值(设计文档 §6.9) ----
GRID_WINDOW = 20                 # 网格观察窗口(根)
GRID_MIN_AMPLITUDE_PCT = 3.0     # 近 20 日平均振幅下限
GRID_MIN_SPAN_PCT = 8.0          # 网格区间宽度下限(相对现价 %)
GRID_TARGET_STEP_PCT = 2.0       # 目标步长 %
GRID_MAX_GRIDS = 10              # 最多档数
GRID_MIN_PROFIT_MULTIPLE = 2     # 单格净收益需 ≥ 2× 往返费用率
GRID_LOT_SIZE = 100              # 1 手 = 100 股(A股/场内 ETF/LOF 均是)


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
    # --- 品种属性(默认按股票,既有构造点零改动) ---
    instrument_kind: str = "stock"   # 'stock' | 'etf'
    t0: bool = False                 # 是否当日可回转(T+0:跨境/黄金/商品 ETF)
    # --- v0.10 补维度输入(设计文档 §6.8;缺数据 → None + degraded,绝不编数字) ---
    fees: TradeFees | None = None            # 已按品种选档(ETF 免印花税/过户费)
    cash_available: float | None = None      # 账户可用资金(元);None = 未填写
    holding_days: int | None = None          # 持有自然日(IO 层算好注入)
    position_share_pct: float | None = None  # 该票持仓成本占比 %


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

    # G5 T 区间必须有正宽度(设计文档 §6.2 修订)
    if t_high <= t_low:
        return _unsuitable(
            "T 区间无宽度(P20~P80 分位带与近 5 日波动区间无重叠),做 T 无差价",
            needs_position,
        )

    amplitude_pct = (t_high - t_low) / ep * 100 if ep > 0 else None

    base_pct = "≥70%" if bull_ma else "≥50%"
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
        "unsuitable_signals": "",
        "needs_position": needs_position,
    }


# ============================ 买入(空仓) ============================

def _recent_pressure(ind: dict[str, Any], price: float) -> float | None:
    """最近压力位:低于现价的压力位里最高的一个"""
    pressures = [_f(p) for p in ((ind.get("support_pressure") or {}).get("pressure") or [])]
    below = [p for p in pressures if p is not None and p < price]
    return max(below) if below else None


def judge_entry(ctx: DecisionContext) -> list[dict[str, Any]]:
    """什么时候该买(空仓)→ 三个候选,各自标 now / armed / blocked"""
    ind = ctx.indicators
    ep = effective_price(ctx)
    if ep is None:
        return []
    actions: list[dict[str, Any]] = []

    # 下跌通道守卫(设计文档 §6.3 补充条款)
    # ------------------------------------------------------------------
    # 为什么要有:§6.6 把「下跌通道中不要抄底」列为**全局**别动规则,
    # 但 C1/C2/C3 原来完全不看通道 —— 结果卡片会同时出现
    #   「可以建仓 · 现在可做」  +  「🚫 别动: 下跌通道中不要抄底」
    # 两条互相打架的指令,股民该听哪条?全局规则必须赢。
    # 触发时机:channel=='down'(与 §6.6 判据完全一致,不多不少)。
    # 实测影响(30 只 × 120 交易日 = 3600 个信号日):
    #   现状 entry 触发日 339 → 本守卫后 158(仍 > 闸门要求的 100 条有效信号)。
    down_channel = (ind.get("channel") or {}).get("state") == "down"

    def _guard(action: dict[str, Any]) -> dict[str, Any]:
        """下跌通道里,把已满足技术条件的建仓候选降级为「待触发」"""
        if down_channel and action["status"] == "now":
            action["status"] = "armed"
            action["basis"] = list(action["basis"]) + [
                "下跌通道中(趋势未修复),按全局「别动」规则不抄底"
            ]
        return action

    # C1 支撑企稳
    st = ind.get("stabilize") or {}
    st_price = _f(st.get("price"))
    if bool(st.get("state")) and st_price is not None:
        actions.append(_guard({
            "kind": "entry",
            "label": "支撑企稳建仓",
            "condition": f"回踩 {st_price:.2f} 元不破且 MACD 绿柱缩短时,首仓建仓",
            "price": round(st_price, 3),
            "basis": [
                f"企稳价 {st_price:.2f} 元(现价 {(ep / st_price - 1) * 100:+.1f}%)",
                "stabilize.state=true",
            ],
            "status": "now" if ep >= st_price else "armed",
        }))

    # C2 超跌反弹
    # ------------------------------------------------------------------
    # status 必须与 condition 自述的触发条件**同时成立**(设计文档 §5:
    # 「now = 此刻条件已满足」)。condition 是合取式:
    #   「站回 P20 低位带」**且**「KDJ 出金叉」
    # 原来只判了「KDJ 出金叉」一个合取项 → 现价还在 P20 之下也标「现在可做」,
    # 而 basis 里明明白白写着「站回 15.19 元」—— 卡片自相矛盾。
    pos = ind.get("position") or {}
    p20 = _f(pos.get("p20"))
    kdj = ind.get("kdj") or {}
    if pos.get("risk_band") == "low" and kdj.get("zone") == "oversold" and p20 is not None:
        golden = kdj.get("cross") == "golden"
        reclaimed = ep >= p20
        missing: list[str] = []
        if not reclaimed:
            missing.append(f"现价 {ep:.2f} 元未站回 P20 低位带 {p20:.2f} 元")
        if not golden:
            missing.append("KDJ 尚未出金叉")
        actions.append(_guard({
            "kind": "entry",
            "label": "超跌反弹建仓",
            "condition": f"站回 {p20:.2f} 元(P20 低位带)且 KDJ 出金叉时小仓位试仓",
            "price": round(p20, 3),
            "basis": [
                f"P20 低位带 {p20:.2f} 元",
                f"KDJ {kdj.get('zone')}(K={kdj.get('k')},D={kdj.get('d')})",
            ] + missing,
            "status": "now" if (golden and reclaimed) else "armed",
        }))

    # C3 突破确认
    vol_ratio = _f((ind.get("volume") or {}).get("ratio"))
    pressure = _recent_pressure(ind, ep)
    if pressure is not None:
        broke = ep > pressure
        enough = vol_ratio is not None and vol_ratio >= ENTRY_MIN_VOLUME_RATIO
        if not broke:
            status, basis_extra = "armed", [f"尚未突破压力位 {pressure:.2f} 元"]
        elif enough:
            status, basis_extra = "now", [f"量比 {vol_ratio:.2f} ≥ {ENTRY_MIN_VOLUME_RATIO}"]
        else:
            status = "blocked"
            basis_extra = [f"量能仅 {vol_ratio:.2f} 倍,未达 {ENTRY_MIN_VOLUME_RATIO} 倍确认标准"]
        actions.append(_guard({
            "kind": "entry",
            "label": "放量突破追进",
            "condition": f"放量站上 {pressure:.2f} 元压力位时追进",
            "price": round(pressure, 3),
            "basis": [f"压力位 {pressure:.2f} 元"] + basis_extra,
            "missing": basis_extra,          # ← 新增:真正没满足的条件
            "status": status,
        }))
    return actions


# ============================ 卖出(浮盈) ============================

def judge_exit(ctx: DecisionContext) -> list[dict[str, Any]]:
    """什么时候该卖(浮盈)"""
    ind = ctx.indicators
    ep = effective_price(ctx)
    if ep is None:
        return []
    pos = ind.get("position") or {}
    ma = ind.get("ma") or {}
    boll = ind.get("boll") or {}
    kdj = ind.get("kdj") or {}
    vp = (ind.get("volume_price") or {}).get("direction")
    channel = (ind.get("channel") or {}).get("state")
    ma5, ma10, ma20, ma60 = (_f(ma.get(k)) for k in ("ma5", "ma10", "ma20", "ma60"))
    bull_ma = all(v is not None for v in (ma5, ma10, ma20, ma60)) and ma5 > ma10 > ma20 > ma60

    actions: list[dict[str, Any]] = []
    p80 = _f(pos.get("p80"))
    if p80 is not None:
        actions.append({
            "kind": "exit",
            "label": "分批止盈",
            "condition": f"涨到 {p80:.2f} 元(P80 分位)先减仓 1/3",
            "price": round(p80, 3),
            "basis": [f"P80 分位 {p80:.2f} 元"],
            "status": "now" if ep >= p80 else "armed",
        })

    if boll.get("position") in ("touching_upper", "above_upper") and kdj.get("zone") == "overbought":
        actions.append({
            "kind": "exit",
            "label": "高位滞涨再减",
            "condition": "布林触上轨且 KDJ 超买,再减仓 1/3",
            "price": round(ep, 3),
            "basis": [f"布林位置 {boll.get('position')}", f"KDJ {kdj.get('zone')}"],
            "status": "now",
        })

    if ma5 is not None:
        actions.append({
            "kind": "exit",
            "label": "移动止盈",
            "condition": f"跌破 MA5 {ma5:.2f} 元清掉剩余仓位",
            "price": round(ma5, 3),
            "basis": [f"MA5 {ma5:.2f} 元"],
            "status": "armed",
        })

    if channel == "up" and vp == "healthy_up" and bull_ma:
        actions.append({
            "kind": "watch",
            "label": "让利润跑",
            "condition": "放量价升且均线多头,持股不动等突破,不急卖",
            "price": None,
            "basis": [f"通道 {channel}", f"量价 {vp}", "均线多头排列"],
            "status": "now",
        })

    stop = _f(pos.get("stop_loss_price"))
    if stop is not None and ep < stop:
        actions.append({
            "kind": "stop",
            "label": "止损",
            "condition": f"跌破 {stop:.2f} 元无条件减仓",
            "price": round(stop, 3),
            "basis": [f"建议止损 {stop:.2f} 元"],
            "status": "now",
        })
    return actions


# ============================ 亏损处理 ============================

def judge_loss_plan(ctx: DecisionContext) -> list[dict[str, Any]]:
    """亏损了怎么办"""
    ind = ctx.indicators
    ep = effective_price(ctx)
    if ep is None:
        return []
    pos = ind.get("position") or {}
    channel = (ind.get("channel") or {}).get("state")
    st = ind.get("stabilize") or {}
    actions: list[dict[str, Any]] = []

    stop = _f(pos.get("stop_loss_price"))
    if stop is not None and ep < stop:
        actions.append({
            "kind": "stop",
            "label": "无条件止损",
            "condition": f"已跌破 {stop:.2f} 元,无条件止损,不要等回本",
            "price": round(stop, 3),
            "basis": [f"建议止损 {stop:.2f} 元(参考支撑 × 0.97)"],
            "status": "now",
        })

    support = _f(pos.get("support_price"))
    vp = (ind.get("volume_price") or {}).get("direction")
    if support is not None and ep < support and vp == "panic_sell":
        actions.append({
            "kind": "exit",
            "label": "破位减仓",
            "condition": f"跌破 {support:.2f} 元且量增价跌(主力出货),减仓而不是补仓",
            "price": round(support, 3),
            "basis": [f"参考支撑 {support:.2f} 元", f"量价 {vp}"],
            "status": "now",
        })

    # L3 解套路径(watch:亏损时最该先回答「还能不能回本?要涨多少?」)
    # 任一输入缺失就不生成这条,更不编数字(设计文档 §6.5)
    p80 = _f(pos.get("p80"))
    cost_basis = _f(ctx.cost_basis)
    if cost_basis is not None and cost_basis > 0 and p80 is not None and p80 > 0:
        need_pct = (cost_basis - ep) / ep * 100
        if p80 > cost_basis:
            condition = f"涨到 {p80:.2f} 元可解套(需涨 {need_pct:.1f}%)"
            basis = [
                f"持仓成本 {cost_basis:.2f} 元",
                f"现价 {ep:.2f} 元",
                f"需涨 {need_pct:.1f}%",
            ]
        else:
            condition = f"按 P80 {p80:.2f} 元也回不了本,建议降低预期或换股"
            basis = [f"持仓成本 {cost_basis:.2f} 元", f"P80 仅 {p80:.2f} 元"]
            if need_pct > 30:
                condition += ",不建议死扛"
                basis.append(f"需涨 {need_pct:.1f}%,超 30%")
        actions.append({
            "kind": "watch",
            "label": "解套路径",
            "condition": condition,
            "price": round(p80, 3),
            "basis": basis,
            "status": "armed",
        })

    # L4 补仓摊薄
    market_state = (ctx.env.market or {}).get("state")
    reasons: list[str] = []
    if channel == "down":
        reasons.append("下跌通道(趋势未破条件不成立)")
    if not bool(st.get("state")):
        reasons.append("尚无企稳信号")
    if market_state == "cold":
        reasons.append("大盘偏冷")
    shares = ctx.shares
    cost = _f(ctx.cost_basis)
    if shares > 0 and cost is not None and cost > 0:
        add_shares = round(shares * ADD_SHARE_RATIO)
        if add_shares > 0:
            new_cost = (shares * cost + add_shares * ep) / (shares + add_shares)
            actions.append({
                "kind": "add",
                "label": "补仓摊薄",
                "condition": (
                    f"趋势未破且企稳,可补 {add_shares} 股摊薄成本到 {new_cost:.2f} 元"
                    if not reasons
                    else f"暂不补仓({';'.join(reasons)})"
                ),
                "price": round(ep, 3),
                "basis": [
                    f"持仓 {shares} 股 @ 成本 {cost:.2f} 元",
                    f"补 {add_shares} 股后均价 {new_cost:.2f} 元",
                ],
                "missing": reasons,               # ← 新增:真正没满足的条件(下跌通道/无企稳/大盘偏冷)
                "status": "now" if not reasons else "blocked",
            })
    return actions


# ============================ 别动清单 ============================

def judge_do_not(ctx: DecisionContext) -> list[str]:
    """什么情况别动"""
    ind = ctx.indicators
    out: list[str] = []
    ep = effective_price(ctx)

    if (ind.get("liar") or {}).get("bull_liars"):
        out.append("出现诱多信号时不要加仓")

    prev = _f(ctx.prev_close)
    if ep is not None and prev is not None and prev > 0:
        chg = (ep - prev) / prev * 100
        if chg >= NEAR_LIMIT_UP_PCT:
            if ctx.instrument_kind == "etf":
                # ETF 无涨跌幅限制 → 涨到 9.5% 不是涨停,只是涨得多
                out.append(
                    f"当日涨幅已达 {chg:.1f}%,不追高(ETF 无涨跌停限制,涨幅可以更大)"
                )
            else:
                out.append("涨停或接近涨停时不要追高")

    m = ctx.env.market or {}
    up_total = m.get("up_total")
    down_total = m.get("down_total")
    if (
        isinstance(up_total, int)
        and isinstance(down_total, int)
        and up_total > 0
        and down_total > up_total * MARKET_COLD_RATIO
    ):
        out.append(f"大盘普跌(跌 {down_total} 家多于涨 {up_total} 家 1.5 倍)时不要加仓")

    kline_count = (ind.get("data_quality") or {}).get("kline_count") or 0
    if kline_count < MIN_KLINES_FOR_SIGNAL:
        out.append(f"K 线不足 {MIN_KLINES_FOR_SIGNAL} 根,指标不可靠,先别动手")

    if (ind.get("channel") or {}).get("state") == "down":
        out.append("下跌通道中不要抄底")

    last_vol = ctx.klines[-1].get("volume") if ctx.klines else None
    if not last_vol or int(last_vol) <= 0:
        out.append("今日无成交,无法判断")

    return out


# ============================ v0.10 补维度(设计文档 §6.8) ============================
#
# 纪律:这五个维度**只增信息**,不参与 derive_verdict,不改任何既有阈值。
# 任一输入缺失 → 对应字段为 None,并由调用方写进 degraded。


def judge_cost_anchor(ctx: DecisionContext) -> dict[str, Any] | None:
    """成本锚点:浮盈亏 / 回本还差多少 / 距止损 / 到第一目标 / 风险收益比"""
    ep = effective_price(ctx)
    cb = _f(ctx.cost_basis)
    if ep is None or cb is None or cb <= 0:
        return None

    pos = ctx.indicators.get("position") or {}
    p80 = _f(pos.get("p80"))
    stop = _f(pos.get("stop_loss_price"))

    pnl_pct = (ep - cb) / cb * 100
    # 回本还需涨幅:只在浮亏时给(浮盈时不需要"回本")
    break_even_gap = (cb - ep) / ep * 100 if pnl_pct < 0 else None
    distance_to_stop = (stop - ep) / ep * 100 if stop is not None else None
    # 到第一目标(P80)的空间:浮盈时才有意义
    distance_to_target = (p80 - ep) / ep * 100 if (p80 is not None and pnl_pct > 0) else None

    # 风险收益比 = 上行空间 / 下行空间;下行空间为 0(已在止损下方)或缺失 → None
    risk_reward: float | None = None
    if distance_to_target is not None and distance_to_stop is not None and distance_to_stop < 0:
        risk_reward = distance_to_target / abs(distance_to_stop)

    return {
        "cost_basis": round(cb, 3),
        "current_price": round(ep, 3),
        "pnl_pct": round(pnl_pct, 2),
        "break_even_gap_pct": round(break_even_gap, 2) if break_even_gap is not None else None,
        "distance_to_stop_pct": round(distance_to_stop, 2) if distance_to_stop is not None else None,
        "distance_to_target_pct": round(distance_to_target, 2) if distance_to_target is not None else None,
        "risk_reward": round(risk_reward, 2) if risk_reward is not None else None,
    }


def judge_time_window(ctx: DecisionContext) -> dict[str, Any] | None:
    """时间窗口:持有天数与是否超期(口径:自纳入本系统起算)"""
    days = ctx.holding_days
    if days is None:
        return None
    return {
        "holding_days": int(days),
        "overdue": bool(days > HOLD_DAYS_LIMIT),
        "note": f"自纳入本系统起 {int(days)} 天(自然日)",
    }


def _effective_fees(fees: TradeFees | None) -> tuple[TradeFees | None, str | None]:
    """返回 (用于计算的费率档, fee_basis)。

    费用设置未启用(enabled=false)时,**按当前费率档估算**并在 degraded 标注
    「费用设置未启用,费用按默认档估算」——默认档是系统常量,来源可追溯,
    且最低佣金与 ETF 免印花税只有费率明确时才算得出来。
    """
    if fees is None:
        return None, None
    if fees.enabled:
        return fees, "configured"
    return replace(fees, enabled=True), "default_estimate"


def _roundtrip_fee_pct(fees: TradeFees | None) -> float | None:
    """往返费用率 %(费率口径,不含最低佣金)"""
    if fees is None:
        return None
    rate = (
        2 * float(fees.commission_rate)
        + float(fees.stamp_tax_rate)
        + 2 * float(fees.transfer_fee_rate)
    )
    return rate * 100


def judge_cost_effect(ctx: DecisionContext, t_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """费用影响:做 T 预期差价 vs 往返费用率(设计文档 §6.8.3)"""
    fees_eff, fee_basis = _effective_fees(ctx.fees)
    if fees_eff is None:
        return None

    fee_pct = _roundtrip_fee_pct(fees_eff)
    spread = _f((t_plan or {}).get("amplitude_pct"))
    worth_it: bool | None = None
    if spread is not None and fee_pct is not None:
        worth_it = spread >= T_SPREAD_MIN_MULTIPLE * fee_pct

    notes: list[str] = []
    if ctx.instrument_kind == "etf":
        notes.append("ETF 免印花税、免过户费,只收佣金")
    else:
        notes.append("股票卖出收印花税 0.05%,过户费双向 0.001%")
    if fee_basis == "default_estimate":
        notes.append("费用设置未启用,按费率档估算")

    return {
        "roundtrip_fee_pct": round(fee_pct, 4) if fee_pct is not None else None,
        "fee_basis": fee_basis,
        "spread_pct": round(spread, 2) if spread is not None else None,
        "worth_it": worth_it,
        "note": ";".join(notes),
    }


def judge_instrument_rule(ctx: DecisionContext) -> dict[str, Any]:
    """品种规则:涨跌停 / 印花税过户费 / T+0"""
    notes: list[str] = []
    if ctx.instrument_kind == "etf":
        notes.append("ETF 无涨跌幅限制")
        notes.append("免印花税、免过户费(只收佣金)")
        notes.append("当日可回转(T+0)" if ctx.t0 else "T+1,当日买入当日不可卖出")
    else:
        notes.append("股票有涨跌幅限制(±10%)")
        notes.append("T+1,当日买入当日不可卖出")
    return {"kind": ctx.instrument_kind, "t0": ctx.t0, "notes": notes}


def judge_concentration(ctx: DecisionContext) -> dict[str, Any] | None:
    """集中度:该票持仓成本占比(口径见设计文档 §6.8.5)"""
    pct = ctx.position_share_pct
    if pct is None:
        return None
    if pct >= CONCENTRATION_STRONG_PCT:
        level = "strong"
        note = f"该标的占持仓成本 {pct:.1f}%,集中度过高,加仓会放大单一暴露"
    elif pct >= CONCENTRATION_WARN_PCT:
        level = "warn"
        note = f"该标的占持仓成本 {pct:.1f}%,集中度偏高"
    else:
        level = "low"
        note = f"该标的占持仓成本 {pct:.1f}%,集中度可接受"
    return {"cost_share_pct": round(pct, 2), "level": level, "note": note}


# ============================ v0.10 网格建议(设计文档 §6.9) ============================


def _grid_unsuitable(reason: str) -> dict[str, Any]:
    """不适用时的网格块:配置类字段一律 None(不给"半截配置")"""
    return {
        "suitable": False,
        "mode": None,
        "reason": "",
        "range_low": None,
        "range_high": None,
        "span_pct": None,
        "grids": None,
        "step_pct": None,
        "step_price": None,
        "shares_per_grid": None,
        "capital_per_grid": None,
        "cash_needed": None,
        "cash_available": None,
        "net_step_pct": None,
        "roundtrip_fee_pct": None,
        "fee_basis": None,
        "net_profit_per_grid": None,
        "replace_t_plan": False,
        "risk": "",
        "unsuitable_signals": reason,
    }


def judge_grid_plan(
    ctx: DecisionContext,
    t_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """是否采取网格交易配置 → GridPlan(设计文档 §6.9)

    网格是长期挂单式策略,与手动做 T **互为替代**。判定比 judge_t_plan 更保守:
    t_plan 只看均线排列 + 3 日涨跌,而网格在单边市里会越买越多直到资金耗尽。
    """
    ind = ctx.indicators
    pos = ind.get("position") or {}
    p20 = _f(pos.get("p20"))
    p80 = _f(pos.get("p80"))
    ep = effective_price(ctx)

    # G0 前置数据
    if ep is None or p20 is None or p80 is None or len(ctx.klines) < GRID_WINDOW:
        return _grid_unsuitable("K 线不足,无法计算网格区间")

    # G1 方向:单边市里布网格 = 越套越深 / 卖飞底仓
    channel = (ind.get("channel") or {}).get("state")
    if channel == "down":
        return _grid_unsuitable("下跌通道中不要布网格:越买越套")
    if channel == "up":
        return _grid_unsuitable("上涨通道中布网格会卖飞底仓")

    # G2 振幅:抓不到差价就没有网格的意义
    amps = _daily_amplitude_pct(ctx.klines)[-GRID_WINDOW:]
    if not amps:
        return _grid_unsuitable("K 线不足,无法计算振幅")
    avg_amp = sum(amps) / len(amps)
    if avg_amp < GRID_MIN_AMPLITUDE_PCT:
        return _grid_unsuitable(
            f"近 {GRID_WINDOW} 日平均振幅 {avg_amp:.2f}% 不足 "
            f"{GRID_MIN_AMPLITUDE_PCT:.1f}%,网格抓不到差价"
        )

    # G4 区间(保守边:与 t_plan 同思路,取 P20~P80 与近 20 日波动区间的交集)
    window = ctx.klines[-GRID_WINDOW:]
    highs = [_f(k.get("high")) for k in window]
    lows = [_f(k.get("low")) for k in window]
    hi20 = max((v for v in highs if v is not None), default=None)
    lo20 = min((v for v in lows if v is not None), default=None)
    if hi20 is None or lo20 is None:
        return _grid_unsuitable("K 线缺少最高/最低价,无法计算网格区间")
    range_low = max(lo20, p20)
    range_high = min(hi20, p80)
    if range_high <= range_low:
        return _grid_unsuitable(
            "网格区间无宽度(P20~P80 分位带与近 20 日波动区间无重叠)"
        )
    span_pct = (range_high - range_low) / ep * 100

    # G3 区间宽度
    if span_pct < GRID_MIN_SPAN_PCT:
        return _grid_unsuitable(
            f"区间宽度 {span_pct:.1f}% 不足 {GRID_MIN_SPAN_PCT:.1f}%,放不下有意义的网格"
        )

    # G5 底仓:网格靠底仓高抛低吸,没有底仓就没有网格
    if ctx.shares < GRID_LOT_SIZE:
        return _grid_unsuitable("当前无底仓,网格需先建底仓")

    # 步长:不得低于 2× 往返费用率(费率口径)
    fees_eff, fee_basis = _effective_fees(ctx.fees)
    fee_pct = _roundtrip_fee_pct(fees_eff)
    step_pct = GRID_TARGET_STEP_PCT
    if fee_pct is not None:
        step_pct = max(step_pct, round(GRID_MIN_PROFIT_MULTIPLE * fee_pct, 2))
    step_price = ep * step_pct / 100
    if step_price <= 0:
        return _grid_unsuitable("步长计算异常,无法给出网格配置")

    # G4 现价须在区间内(容差 1 格)
    if ep < range_low - step_price:
        return _grid_unsuitable(
            f"现价已跌破网格下沿 {range_low:.2f},布网格等于接飞刀"
        )
    if ep > range_high + step_price:
        return _grid_unsuitable(
            f"现价已突破网格上沿 {range_high:.2f},网格不再适用"
        )

    grids = min(GRID_MAX_GRIDS, int(span_pct // step_pct))
    if grids < 1:
        return _grid_unsuitable(
            f"区间宽度 {span_pct:.1f}% 放不下一个 {step_pct:.1f}% 的步长"
        )

    # G6 费用(金额口径:扣掉最低佣金后每格仍要赚钱)
    shares_per_grid = GRID_LOT_SIZE
    # 每格涉及的资金 = 一手金额(不是每格利润)
    capital_per_grid = shares_per_grid * ep
    # 每格毛收益 = 卖一档买回一档的价差 × 股数
    gross_profit = shares_per_grid * step_price
    fee_amount: float | None = None
    net_profit: float | None = None
    if fees_eff is not None:
        d_price = Decimal(str(round(step_price, 3)))
        fee_amount = float(
            buy_fee(shares_per_grid, d_price, fees_eff)
            + sell_fee(shares_per_grid, d_price, fees_eff)
        )
        net_profit = gross_profit - fee_amount
        if net_profit <= 0:
            return _grid_unsuitable(
                f"每格毛收益 {gross_profit:.2f} 元,扣手续费 {fee_amount:.2f} 元后为负,网格不划算"
            )

    # G7 资金:够 → 加仓网格;不够 → 降级为底仓高抛低吸(零额外现金)
    cash_needed = -(-grids // 2) * capital_per_grid  # ceil(grids/2)
    cash_available = ctx.cash_available
    mode = "base"
    if cash_available is None:
        money_note = "账户可用资金未填写,按底仓模式(零额外现金)估算"
    elif cash_available >= cash_needed:
        mode = "add"
        money_note = f"加仓网格需现金 {cash_needed:.0f} 元,账户可用 {cash_available:.0f} 元"
    else:
        money_note = (
            f"现金不足(需 {cash_needed:.0f} 元,可用 {cash_available:.0f} 元),"
            f"只能做底仓高抛低吸"
        )

    # G8 集中度:高集中度时禁止加仓网格
    if (
        ctx.position_share_pct is not None
        and ctx.position_share_pct >= CONCENTRATION_STRONG_PCT
        and mode == "add"
    ):
        mode = "base"
        money_note += (
            f";该标的已占持仓成本 {ctx.position_share_pct:.1f}%,加仓会放大单一暴露,不给加仓模式"
        )

    t_suitable = bool((t_plan or {}).get("suitable"))
    replace_t_plan = t_suitable
    if replace_t_plan:
        reason = "震荡市建议以网格为主(不用盯盘),手动做 T 与网格互斥,择一执行"
    else:
        reason = "震荡市建议以网格为主(不用盯盘);当前手动做 T 条件不满足"
    reason = f"{reason};{money_note}"

    risk = (
        f"跌破 {range_low:.2f} 元(区间下沿)网格失效,按止损离场,不要继续接;"
        f"突破 {range_high:.2f} 元只是少赚,不损;"
        f"单边下行时网格会越买越多直到资金耗尽 —— 这是网格最大的风险。"
    )

    return {
        "suitable": True,
        "mode": mode,
        "reason": reason,
        "range_low": round(range_low, 3),
        "range_high": round(range_high, 3),
        "span_pct": round(span_pct, 2),
        "grids": grids,
        "step_pct": round(step_pct, 2),
        "step_price": round(step_price, 3),
        "shares_per_grid": shares_per_grid,
        "capital_per_grid": round(capital_per_grid, 2),
        "cash_needed": round(cash_needed, 2),
        "cash_available": round(cash_available, 2) if cash_available is not None else None,
        "net_step_pct": round(step_pct - fee_pct, 3) if fee_pct is not None else None,
        "roundtrip_fee_pct": round(fee_pct, 4) if fee_pct is not None else None,
        "fee_basis": fee_basis,
        "net_profit_per_grid": round(net_profit, 2) if net_profit is not None else None,
        "replace_t_plan": replace_t_plan,
        "risk": risk,
        "unsuitable_signals": "",
    }


# ============================ v0.10 操作建议六格(设计文档 §6.10) ============================


def build_suggestions(
    ctx: DecisionContext,
    actions: list[dict[str, Any]],
    stop_loss: dict[str, Any] | None,
    position_pct: str,
    do_not: list[str],
    cost_anchor: dict[str, Any] | None,
    time_window: dict[str, Any] | None,
) -> dict[str, Any]:
    """操作建议六格。值为 None = 该维度数据不足(前端不渲染该格,不显示空框)。"""
    active = [a for a in actions if a.get("status") in ("now", "armed")]
    armed = [a for a in actions if a.get("status") == "armed"]

    # 价位:第一条可执行动作的条件 + 价位
    price_cell: dict[str, Any] | None = None
    if active:
        first = active[0]
        cond = first.get("condition") or ""
        p = _f(first.get("price"))
        if p is not None:
            # 条件里已经带价位时不重复前缀(否则读起来是「28.77 元(涨到 28.77 元…)」)
            if f"{p:.2f}" in cond:
                price_cell = {"label": "价位", "value": cond}
            else:
                price_cell = {"label": "价位", "value": f"{p:.2f} 元({cond})"}
        elif cond:
            price_cell = {"label": "价位", "value": cond}

    # 止损:既有止损价 + 距现价百分比
    stop_cell: dict[str, Any] | None = None
    if stop_loss is not None:
        sp = _f(stop_loss.get("price"))
        if sp is not None:
            dist = (cost_anchor or {}).get("distance_to_stop_pct")
            if dist is not None:
                stop_cell = {"label": "止损", "value": f"{sp:.2f} 元(距现价 {dist:+.1f}%)"}
            else:
                stop_cell = {"label": "止损", "value": f"{sp:.2f} 元"}

    # 仓位:既有 position_pct
    position_cell = {"label": "仓位", "value": position_pct} if position_pct else None

    # 触发:第一条待触发动作的条件
    trigger_cell: dict[str, Any] | None = None
    if armed:
        cond = armed[0].get("condition") or ""
        if cond:
            trigger_cell = {"label": "触发", "value": cond}

    # 时间:持有天数 + 回本还差多少
    timing_cell: dict[str, Any] | None = None
    if time_window is not None:
        days = time_window.get("holding_days")
        gap = (cost_anchor or {}).get("break_even_gap_pct")
        bits: list[str] = []
        if days is not None:
            bits.append(f"已持有 {int(days)} 天")
        if gap is not None:
            bits.append(f"回本还需 +{gap:.1f}%")
        if bits:
            timing_cell = {"label": "时间", "value": ",".join(bits)}

    # 不动:全局别动清单
    avoid_cell = {"label": "不动", "value": " · ".join(do_not)} if do_not else None

    return {
        "price": price_cell,
        "stop_loss": stop_cell,
        "position": position_cell,
        "trigger": trigger_cell,
        "timing": timing_cell,
        "avoid": avoid_cell,
    }


# ============================ 结论组装 ============================

_VERDICT_BY_KIND = {"stop": "sell", "exit": "reduce", "entry": "buy", "add": "add"}


def derive_verdict(actions: list[dict[str, Any]], position_status: str) -> str:
    """actions → 单一结论"""
    now_kinds = {a["kind"] for a in actions if a.get("status") == "now"}
    for kind in ("stop", "exit", "entry", "add"):
        if kind in now_kinds:
            return _VERDICT_BY_KIND[kind]
    if position_status in ("profit", "loss"):
        return "hold"
    return "wait"


def _headline(
    ctx: DecisionContext,
    verdict: str,
    actions: list[dict[str, Any]],
    position_status: str,
) -> str:
    """一句话结论(白话,带具体数字)"""
    ep = effective_price(ctx)
    price_txt = f"现价 {ep:.2f} 元" if ep is not None else "现价未知"
    now = [a for a in actions if a.get("status") == "now"]
    armed = [a for a in actions if a.get("status") == "armed"]

    if verdict == "sell" and now:
        return f"{price_txt},{now[0]['label']}:{now[0]['condition']}"
    if verdict == "reduce" and now:
        return f"{price_txt},{now[0]['label']}:{now[0]['condition']}"
    if verdict == "buy" and now:
        return f"{price_txt},{now[0]['label']}:{now[0]['condition']}"
    if verdict == "add" and now:
        return f"{price_txt},{now[0]['label']}:{now[0]['condition']}"
    if armed:
        return f"{price_txt},等触发:{armed[0]['condition']}"
    if position_status == "profit":
        return f"{price_txt},暂无止盈触发条件,持股观察"
    if position_status == "loss":
        return f"{price_txt},等解套信号,未到止损位"
    return f"{price_txt},暂不满足建仓条件,继续观察"


def build_decision(ctx: DecisionContext) -> dict[str, Any]:
    """组装完整决策(纯函数)"""
    ind = ctx.indicators
    ep = effective_price(ctx)
    degraded: list[str] = list(ctx.env.degraded or [])
    if ctx.current_price is None and ep is not None:
        degraded.append(f"实时价不可用,按最新收盘价 {ep} 计算")

    trend = judge_trend(ctx)
    t_plan = judge_t_plan(ctx)

    if ctx.position_status == "empty":
        actions = judge_entry(ctx)
    elif ctx.position_status == "profit":
        actions = judge_exit(ctx)
    else:
        actions = judge_loss_plan(ctx)

    verdict = derive_verdict(actions, ctx.position_status)
    role = {"empty": "建仓参考", "profit": "止盈参考", "loss": "解套参考"}[ctx.position_status]

    # 仓位建议
    pos = ind.get("position") or {}
    signal = ind.get("signal") or {}
    score = _f(signal.get("score"))
    base = 20
    if score is not None:
        for upper, pct in POSITION_TIERS:
            if score < upper:
                base = pct
                break
    if pos.get("risk_band") == "low":
        base = min(base + 10, 30)
    ma20 = _f((ind.get("ma") or {}).get("ma20"))
    add_to = min(base * 2, POSITION_ADD_CAP)
    if ctx.position_status == "empty":
        position_pct = f"首仓 {base}%"
        if ma20 is not None:
            position_pct += f",站稳 MA20 {ma20:.2f} 元后加至 {add_to}%"
    elif ctx.position_status == "profit":
        position_pct = "分批止盈,每次减 1/3,保留底仓 ≥50%"
    else:
        position_pct = f"解套优先,减仓不追补;确需补仓时单次不超过 {add_to}%"

    # 止损(文案归位到顶层:设计文档 §6.2)
    stop_loss = None
    stop_price = _f(pos.get("stop_loss_price"))
    support = _f(pos.get("support_price"))
    if stop_price is not None:
        stop_loss = {
            "price": round(stop_price, 3),
            "basis": (
                f"参考支撑 {support:.2f} 元 × 0.97,跌破 {stop_price:.2f} 元即止损"
                if support is not None
                else f"跌破 {stop_price:.2f} 元即止损"
            ),
        }

    # 置信度
    conf = signal.get("confidence") or "medium"
    if degraded and conf == "high":
        conf = "medium"

    market_env = {
        "market": ctx.env.market or {},
        "sector": ctx.env.sector or {},
        "stock_flow": ctx.env.stock_flow or {},
        "relative": ctx.env.relative or {},
        "degraded": list(ctx.env.degraded or []),
    }

    headline = _headline(ctx, verdict, actions, ctx.position_status)
    if ctx.position_status == "empty":
        # 设计文档 §6.2 空仓特例:做 T 前需先建仓
        headline += ";当前无底仓,做 T 前需先建仓"

    # ---- v0.10 补维度(设计文档 §6.8):只增信息,不改既有 verdict 逻辑与阈值 ----
    cost_anchor = judge_cost_anchor(ctx)
    if cost_anchor is None and ctx.position_status != "empty":
        degraded.append("成本锚点不可用(缺持仓成本或现价)")
    time_window = judge_time_window(ctx)
    if time_window is None and ctx.position_status != "empty":
        degraded.append("持有天数不可用(缺持仓起始日)")
    cost_effect = judge_cost_effect(ctx, t_plan)
    if cost_effect is None:
        degraded.append("费用影响不可用(费用档读取失败)")
    elif cost_effect.get("fee_basis") == "default_estimate":
        degraded.append("费用设置未启用,费用按默认档估算")
    instrument_rule = judge_instrument_rule(ctx)
    concentration = judge_concentration(ctx)
    if concentration is None and ctx.position_status != "empty":
        degraded.append("集中度不可用(全量持仓读取失败)")

    # ---- v0.10 网格建议(设计文档 §6.9) ----
    grid_plan = judge_grid_plan(ctx, t_plan)

    # ---- v0.10 操作建议六格(设计文档 §6.10) ----
    do_not = judge_do_not(ctx)
    suggestions = build_suggestions(
        ctx, actions, stop_loss, position_pct, do_not,
        cost_anchor, time_window,
    )

    return {
        "stock_code": ctx.stock_code,
        "stock_name": ctx.stock_name,
        "verdict": verdict,
        "headline": headline,
        "confidence": conf,
        "role": role,
        "position_status": ctx.position_status,
        "actions": actions,
        "stop_loss": stop_loss,
        "position_pct": position_pct,
        "do_not": do_not,
        "t_plan": t_plan,
        "grid_plan": grid_plan,
        "suggestions": suggestions,
        "cost_anchor": cost_anchor,
        "time_window": time_window,
        "cost_effect": cost_effect,
        "instrument_rule": instrument_rule,
        "concentration": concentration,
        "trend_state": trend,
        "market_env": market_env,
        "data_quality": {"degraded": degraded},
    }
