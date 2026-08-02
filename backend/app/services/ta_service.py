"""技术指标服务(v0.4-roadmap 功能3)

全部确定性计算,无网络 / 无 LLM。输入升序日K:
    [{date, open, high, low, close, volume}, ...]
输出:
    ma / volume / channel / support_pressure / stabilize / data_quality
任何指标数据不足时返回 None 或空,并在 data_quality.degraded 中记录原因。
"""
from statistics import mean, stdev
from typing import Any

__all__ = ["compute_indicators", "TaError"]


class TaError(ValueError):
    """输入为空或非法"""


def _f(v: Any) -> float:
    return float(v)


def _sma(values: list[float], n: int) -> list[float | None]:
    """简单移动平均序列;窗口不足处为 None

    实现说明(见 backend/docs/ta-algorithm.md §1):
    - S_{n-1} = Σ_{j=0}^{n-1} v_j(直接求和初始化)
    - i ≥ n 才走递推 S_i = S_{i-1} + v_i - v_{i-n}
    - i < n 不使用负索引(避免 Python 负索引取到序列尾部)
    - **返回全精度**,不在内部 round(下游模块需引用未舍入的 MA 值)
    """
    out: list[float | None] = []
    if len(values) < n:
        return [None] * len(values)
    s = sum(values[:n])
    out.append(s / n)
    for i in range(n, len(values)):
        s += values[i] - values[i - n]
        out.append(s / n)
    for _ in range(n - 1):
        out.insert(0, None)
    return out


def _volume_ratio(volumes: list[int]) -> float | None:
    """量比 = 近5日均量 ÷ 再前20日均量(roadmap 定义,语义为 5/25 量能趋势比)

    需 len ≥ 26;前 20 日均量 ≤ 0 返回 None。
    """
    if len(volumes) < 26:
        return None
    avg5 = mean(volumes[-5:])
    avg_prior = mean(volumes[-25:-5])
    if avg_prior <= 0:
        return None
    return round(avg5 / avg_prior, 2)


def _linear_slope(prices: list[float]) -> float:
    """近 window 根 close 的线性回归斜率(每根价格变化)"""
    n = len(prices)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = mean(xs)
    y_mean = mean(prices)
    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, prices))
    var = sum((x - x_mean) ** 2 for x in xs)
    if var == 0:
        return 0.0
    return cov / var


def _channel(prices: list[float], window: int) -> dict[str, Any]:
    """通道判定:回归斜率(相对均价) → up/down/sideways + 残差 σ 上下轨

    带宽 = 回归末点 y0 ± 1×残差标准差 σ_res = sqrt(Σ(yᵢ-ŷᵢ)²/(n-2))
    σ_res = 0 时 upper = lower = y0(带宽为零;无除法,无需特殊分支)。
    """
    seg = prices[-window:]
    if len(seg) < 10:
        return {
            "state": "sideways",
            "slope": None,
            "upper": None,
            "lower": None,
            "resid_std": None,
        }
    slope = _linear_slope(seg)
    avg = mean(seg)
    n = len(seg)
    slope_norm = slope / avg if avg else 0.0
    up_th, down_th = 0.0015, -0.0015
    if slope_norm > up_th:
        state = "up"
    elif slope_norm < down_th:
        state = "down"
    else:
        state = "sideways"

    # 回归拟合值 ŷᵢ = slope * xᵢ + intercept,intercept = avg - slope * x_mean
    x_mean = mean(range(n))
    intercept = avg - slope * x_mean
    resid_sq_sum = sum((y - (slope * x + intercept)) ** 2 for x, y in enumerate(seg))
    resid_std = (resid_sq_sum / (n - 2)) ** 0.5 if n > 2 else 0.0

    y0 = slope * (n - 1) + intercept
    return {
        "state": state,
        "slope": round(slope, 4),
        "upper": round(y0 + resid_std, 2),
        "lower": round(y0 - resid_std, 2),
        "resid_std": round(resid_std, 4) if resid_std else 0.0,
    }


def _support_pressure(
    closes: list[float], highs: list[float], lows: list[float],
    ma20: float | None, ma60: float | None,
) -> dict[str, Any]:
    """支撑/压力:近 20 根高低点(含当日) + 全期高低点 + MA20/MA60

    容差去重 ±0.5%(贪心链式不传递为已知局限,见 docs)。
    现价恰等于候选价时归入支撑(偏保守)。
    """
    if not closes:
        return {"support": [], "pressure": []}
    close = closes[-1]
    lo20 = min(lows[-20:])
    hi20 = max(highs[-20:])
    lo_all = min(lows)
    hi_all = max(highs)

    raw_supports = [v for v in (ma20, ma60, lo20, lo_all) if v is not None and v <= close and v > 0]
    raw_pressures = [v for v in (ma20, ma60, hi20, hi_all) if v is not None and v >= close and v > 0]

    def _dedup(values: list[float], take: int, reverse: bool) -> list[float]:
        sorted_vals = sorted({round(v, 2) for v in values}, reverse=reverse)
        kept: list[float] = []
        for v in sorted_vals:
            if not kept:
                kept.append(v)
            else:
                base = kept[0]
                if base > 0 and abs(v - base) / base < 0.005:
                    continue
                kept.append(v)
            if len(kept) >= take:
                break
        return kept

    return {
        "support": _dedup(raw_supports, 3, reverse=True),
        "pressure": _dedup(raw_pressures, 3, reverse=False),
    }


def _stabilize(
    closes: list[float], lows: list[float], volumes: list[int],
    ma20: float | None,
) -> dict[str, Any]:
    """企稳检测(三段式 AND):站上 MA20 + 回踩不破前低 + 放量突破(>1.3 倍)

    企稳价位 = max(MA20, 前低)。
    """
    if not closes or ma20 is None:
        return {"state": False, "price": None, "reasons": []}
    close = closes[-1]
    reasons = []
    above_ma20 = close > ma20
    reasons.append({
        "name": "站上MA20",
        "ok": above_ma20,
        "note": f"现价 {round(close, 2)} vs MA20 {round(ma20, 2)}",
    })

    prior_low = min(lows[-25:-5]) if len(lows) >= 26 else min(lows[:-1]) if len(lows) > 1 else None
    pullback_holds = True
    if prior_low is not None:
        pullback_holds = min(lows[-5:]) > prior_low
    reasons.append({
        "name": "回踩不破前低",
        "ok": bool(pullback_holds),
        "note": f"近5日低点 {round(min(lows[-5:]), 2)} vs 前低 {round(prior_low, 2) if prior_low is not None else '-'}",
    })

    breakout_volume = False
    breakout_note_parts = []
    if len(volumes) >= 6:
        avg5 = mean(volumes[-6:-1])
        breakout_volume = volumes[-1] > 1.3 * avg5
        breakout_note_parts = [f"末日量 {volumes[-1]}", f"前5日均量 {round(avg5)}", f"阈值 1.3× = {round(1.3 * avg5)}"]
    else:
        breakout_note_parts = ["末日量 -", "前5日均量 -"]
    reasons.append({
        "name": "放量突破",
        "ok": bool(breakout_volume),
        "note": " vs ".join(breakout_note_parts),
    })

    price = round(max(ma20, prior_low) if prior_low is not None else ma20, 2)
    return {
        "state": above_ma20 and pullback_holds and breakout_volume,
        "price": price,
        "reasons": reasons,
    }


def compute_indicators(klines: list[dict[str, Any]]) -> dict[str, Any]:
    """主入口:输入升序日K列表,输出全部指标 + data_quality"""
    if not klines:
        raise TaError("K 线数据为空")

    closes = [_f(r["close"]) for r in klines]
    highs = [_f(r["high"]) for r in klines]
    lows = [_f(r["low"]) for r in klines]
    volumes = [int(r["volume"]) for r in klines]

    ma5 = _sma(closes, 5)
    ma10 = _sma(closes, 10)
    ma20 = _sma(closes, 20)
    ma60 = _sma(closes, 60)

    def last(seq: list[float | None]) -> float | None:
        return seq[-1] if seq else None

    degraded: list[str] = []

    def ma_last_with_check(seq: list[float | None], n: int, key: str) -> float | None:
        v = last(seq)
        if v is None:
            degraded.append(f"{key}: len<{n}")
        return v

    ma5_v = ma_last_with_check(ma5, 5, "ma5")
    ma10_v = ma_last_with_check(ma10, 10, "ma10")
    ma20_v = ma_last_with_check(ma20, 20, "ma20")
    ma60_v = ma_last_with_check(ma60, 60, "ma60")

    vol_ratio = _volume_ratio(volumes)
    if vol_ratio is None:
        vol_state = None
    elif vol_ratio >= 1.5:
        vol_state = "expand"
    elif vol_ratio <= 0.7:
        vol_state = "shrink"
    else:
        vol_state = "normal"

    channel = _channel(closes, window=60)
    if len(closes) < 10:
        degraded.append("channel: len<10")

    sp = _support_pressure(closes, highs, lows, ma20_v, ma60_v)

    if ma20_v is None:
        degraded.append("stabilize: ma20=None")
    elif len(closes) < 26:
        degraded.append("stabilize: len<26")
    stabilize = _stabilize(closes, lows, volumes, ma20_v)

    return {
        "latest_close": round(closes[-1], 2),
        "ma": {
            "ma5": round(ma5_v, 2) if ma5_v is not None else None,
            "ma10": round(ma10_v, 2) if ma10_v is not None else None,
            "ma20": round(ma20_v, 2) if ma20_v is not None else None,
            "ma60": round(ma60_v, 2) if ma60_v is not None else None,
        },
        "ma_series": {
            "ma5": [round(v, 2) for v in ma5 if v is not None][-60:],
            "ma10": [round(v, 2) for v in ma10 if v is not None][-60:],
            "ma20": [round(v, 2) for v in ma20 if v is not None][-60:],
            "ma60": [round(v, 2) for v in ma60 if v is not None][-60:],
        },
        "volume": {
            "ratio": vol_ratio,
            "state": vol_state,
        },
        "channel": channel,
        "support_pressure": sp,
        "stabilize": stabilize,
        "data_quality": {
            "kline_count": len(klines),
            "degraded": degraded,
        },
    }