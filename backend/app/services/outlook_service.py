"""明日市场预期(纯函数、零 IO、零 LLM)

设计文档 §4.3。

**定位**:纪律锚点,不是预测器。
四维度规则打分 → 偏多/震荡/偏空 + 关键位。所有数字取自真实数据源
(上证指数日K / 涨跌家数 / 板块资金流),或对其显式四则运算。

**铁律**:
- 文案只写「倾向」,禁写「必涨/必跌/一定」;disclaimer 必含「非预测」。
- 缺数据的维度记 0 且**不计入**有效维度数;绝不编造。
- 有效维度 < 2 时不得判「偏多」(单条证据不足以定向);
  但「偏空」允许单维度成立(风险侧保守优于激进)—— 这是**刻意的不对称**。
"""
from __future__ import annotations

from typing import Any

# ---- 规则参数(先定死;后续回测校准只能改参数,不得事后调门槛美化结论) ----
VOLUME_BULL_RATIO = 1.10     # 今日量 >= 5日均量 × 1.10 → 偏多
VOLUME_BEAR_RATIO = 0.90     # 今日量 <= 5日均量 × 0.90 → 偏空
SENTIMENT_BULL_PCT = 0.60    # 上涨占比 >= 60% → 偏多
SENTIMENT_BEAR_PCT = 0.40    # 上涨占比 <= 40% → 偏空
VOLUME_AVG_WINDOW = 5        # 量能对比窗口(前 N 日均量,不含今日)
MIN_KLINES_VOLUME = 6        # 今日 + 前 5 日
MIN_KLINES_MA10 = 11         # 算 MA10 至少 11 根
MIN_KLINES_MA20 = 21         # 算 MA20 至少 21 根
BULLISH_MIN_EFFECTIVE_DIMS = 2  # 判「偏多」所需的最少有效维度数
FLOW_TOTAL_EPS = 1e-9           # 板块资金净额归零阈值(浮点零和保护)


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _ma(closes: list[float], n: int) -> float | None:
    """简单均线;数据不足返回 None"""
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _dim(key: str, label: str, score: int, state: str, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "score": score, "state": state, "detail": detail}


# ============================ 各维度 ============================

def _volume_dim(klines: list[dict]) -> dict[str, Any]:
    """量能:今日量 vs 前 5 日均量"""
    if len(klines) < MIN_KLINES_VOLUME:
        return _dim("volume", "量能", 0, "missing", "K 线不足,无法比较量能")
    vols: list[float] = []
    for k in klines:
        v = _f(k.get("volume"))
        vols.append(v if v is not None else 0.0)
    today = vols[-1]
    avg5 = sum(vols[-1 - VOLUME_AVG_WINDOW:-1]) / VOLUME_AVG_WINDOW
    if avg5 <= 0:
        return _dim("volume", "量能", 0, "missing", "历史成交量为 0,无法比较量能")
    ratio = today / avg5
    if ratio >= VOLUME_BULL_RATIO:
        score = 1
    elif ratio <= VOLUME_BEAR_RATIO:
        score = -1
    else:
        score = 0
    detail = f"今日量为近 5 日均量的 {ratio:.2f} 倍"
    if score == 1:
        detail += ",放量"
    elif score == -1:
        detail += ",缩量"
    else:
        detail += ",量能平稳"
    return _dim("volume", "量能", score, "bull" if score > 0 else ("bear" if score < 0 else "flat"), detail)


def _sentiment_dim(sentiment: dict | None) -> dict[str, Any]:
    """涨跌家数"""
    if not isinstance(sentiment, dict):
        return _dim("sentiment", "涨跌家数", 0, "missing", "涨跌家数数据不可用")
    up = _f(sentiment.get("up_total"))
    down = _f(sentiment.get("down_total"))
    if up is None or down is None or (up + down) <= 0:
        return _dim("sentiment", "涨跌家数", 0, "missing", "涨跌家数数据不可用")
    ratio = up / (up + down)
    if ratio >= SENTIMENT_BULL_PCT:
        score = 1
    elif ratio <= SENTIMENT_BEAR_PCT:
        score = -1
    else:
        score = 0
    detail = f"上涨 {int(up)} 家 / 下跌 {int(down)} 家(上涨占比 {ratio * 100:.0f}%)"
    return _dim("sentiment", "涨跌家数", score, "bull" if score > 0 else ("bear" if score < 0 else "flat"), detail)


def _ma_dim(closes: list[float]) -> dict[str, Any]:
    """指数均线位置"""
    if len(closes) < MIN_KLINES_MA10:
        return _dim("ma", "指数均线", 0, "missing", "K 线不足,无法计算 MA10")
    close = closes[-1]
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    if ma5 is None or ma10 is None:
        return _dim("ma", "指数均线", 0, "missing", "均线数据不完整")
    if close > ma5 > ma10:
        score = 1
    elif close < ma5 < ma10:
        score = -1
    else:
        score = 0
    detail = f"收盘 {close:.2f},MA5 {ma5:.2f},MA10 {ma10:.2f}"
    return _dim("ma", "指数均线", score, "bull" if score > 0 else ("bear" if score < 0 else "flat"), detail)


def _flow_dim(sector_flows: list[dict] | None) -> dict[str, Any]:
    """板块资金(真实板块资金流,非估算)

    判定按**净流入总额符号**,不是「有无正流入」——
    「有正有负」蕴含「存在正流入」,按有无判定会让偏多与中性两档互相排斥。
    总额: >0 偏多 / <0 偏空 / ==0 中性。

    ⚠️ 两个诚实性要点(2026-10-21 复审发现,必须保留):
    1. **浮点零和**: [38.6, -12.4, -26.2] 的和是 3.55e-15 而非精确 0,
       直接用 `total > 0` 判会误判成偏多,并渲染出「净流入合计 0.00 亿」这种
       自相矛盾的文案。故用 FLOW_TOTAL_EPS 把 |total| < 1e-9 归一为 0。
    2. **全部板块净额都是 None** 时 = 根本没有板块资金数据,必须判 **missing**
       而不是 flat。否则会在完全没有该维度数据时对外宣称「4/4 维度规则推断」。
    """
    if not sector_flows:
        return _dim("flow", "板块资金", 0, "missing", "板块资金流数据不可用")
    total = 0.0
    valid = 0
    top: tuple[float, str] | None = None
    for f in sector_flows:
        if not isinstance(f, dict):
            continue
        net = _f(f.get("netamount_yi"))
        if net is None:
            continue
        valid += 1
        total += net
        if net > 0 and (top is None or net > top[0]):
            top = (net, str(f.get("name") or ""))
    if valid == 0:
        return _dim("flow", "板块资金", 0, "missing", "板块资金流无有效净额数据")
    if abs(total) < FLOW_TOTAL_EPS:
        total = 0.0
    if total > 0:
        # total > 0 必然蕴含至少一个 net > 0,故此处 top 一定非 None(无需 None 兜底分支)
        score = 1
        detail = f"板块资金净流入合计 {total:.2f} 亿,主攻 {top[1]} {top[0]:.2f} 亿"
    elif total < 0:
        score = -1
        detail = f"板块资金净流出合计 {abs(total):.2f} 亿,无主攻方向"
    else:
        score = 0
        detail = "板块资金多空抵消,无明确主攻方向"
    state = "bull" if score > 0 else ("bear" if score < 0 else "flat")
    return _dim("flow", "板块资金", score, state, detail)


# ============================ 关键位 ============================

def _key_levels(klines: list[dict], closes: list[float]) -> dict[str, Any]:
    """支撑 / 压力:全部取自真实日K,不做虚构点位"""
    close = closes[-1] if closes else None
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20) if len(closes) >= MIN_KLINES_MA20 else None
    last = klines[-1] if klines else {}
    high = _f(last.get("high"))
    low = _f(last.get("low"))

    support: list[float] = []
    if ma5 is not None and close is not None and ma5 < close:
        support.append(round(ma5, 2))
    if low is not None:
        support.append(round(low, 2))

    resistance: list[float] = []
    if high is not None:
        resistance.append(round(high, 2))
    if ma20 is not None and close is not None and ma20 > close:
        resistance.append(round(ma20, 2))

    return {
        "close": round(close, 2) if close is not None else None,
        "ma5": round(ma5, 2) if ma5 is not None else None,
        "ma10": round(ma10, 2) if ma10 is not None else None,
        "ma20": round(ma20, 2) if ma20 is not None else None,
        "support": sorted(set(support)),
        "resistance": sorted(set(resistance)),
    }


# ============================ 主入口 ============================

def build_outlook(
    index_klines: list[dict],
    sentiment: dict | None,
    sector_flows: list[dict] | None,
) -> dict[str, Any]:
    """明日市场预期(纯函数)

    Args:
        index_klines: 上证指数升序日K,{date,open,high,low,close,volume}
        sentiment: {up_total, down_total, ...} 或 None
        sector_flows: [{name, netamount_yi}, ...] 或 None
    """
    klines = index_klines if isinstance(index_klines, list) else []
    closes: list[float] = []
    for k in klines:
        c = _f(k.get("close")) if isinstance(k, dict) else None
        if c is not None:
            closes.append(c)

    dims = [
        _volume_dim(klines),
        _sentiment_dim(sentiment),
        _ma_dim(closes),
        _flow_dim(sector_flows),
    ]
    score = sum(d["score"] for d in dims)
    effective = sum(1 for d in dims if d["state"] != "missing")

    if effective == 0:
        stance = "unknown"
    elif score >= 1 and effective >= BULLISH_MIN_EFFECTIVE_DIMS:
        stance = "bullish"
    elif score <= -1:
        stance = "bearish"
    else:
        stance = "neutral"

    stance_label = {
        "bullish": "偏多", "bearish": "偏空", "neutral": "震荡", "unknown": "数据不足",
    }[stance]
    degraded = effective < len(dims)
    degraded_reason = [
        f"{d['label']}数据缺失" for d in dims if d["state"] == "missing"
    ]

    return {
        "stance": stance,
        "stance_label": stance_label,
        "score": score,
        "dims_total": len(dims),
        "dims_effective": effective,
        "dims": dims,
        "key_levels": _key_levels(klines, closes),
        "disclaimer": (
            f"基于 {effective}/{len(dims)} 维度规则推断，非预测；仅作明日操作参考。"
        ),
        "degraded": degraded,
        "degraded_reason": degraded_reason,
    }


__all__ = ["build_outlook"]
