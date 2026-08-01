"""技术指标服务(v0.4-roadmap 功能3)

全部确定性计算,无网络 / 无 LLM。输入升序日K:
    [{date, open, high, low, close, volume}, ...]
输出:
    ma / volume / channel / support_pressure / stabilize
任何指标数据不足时返回 None 或空,不抛异常(除空输入)。
"""
from statistics import mean, stdev
from typing import Any

__all__ = ["compute_indicators", "TaError"]


class TaError(ValueError):
    """输入为空或非法"""


def _f(v: Any) -> float:
    return float(v)


def _sma(values: list[float], n: int) -> list[float | None]:
    """简单移动平均序列;窗口不足处为 None"""
    out: list[float | None] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out.append(round(s / n, 2))
        else:
            out.append(None)
    return out


def _volume_ratio(volumes: list[int]) -> float | None:
    """量比 = 近5日均量 ÷ 再前20日均量(roadmap 定义)"""
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
    """通道判定:回归斜率(相对均价) → up/down/sideways + 上下轨"""
    seg = prices[-window:]
    if len(seg) < 10:
        return {"state": "sideways", "slope": None, "upper": None, "lower": None}
    slope = _linear_slope(seg)
    avg = mean(seg)
    slope_norm = slope / avg if avg else 0.0
    up_th, down_th = 0.0015, -0.0015
    if slope_norm > up_th:
        state = "up"
    elif slope_norm < down_th:
        state = "down"
    else:
        state = "sideways"
    std = stdev(seg) if len(seg) > 1 else 0.0
    y0 = _linear_slope(seg) * (len(seg) - 1) + (mean(seg) - _linear_slope(seg) * mean(range(len(seg))))
    return {
        "state": state,
        "slope": round(slope, 4),
        "upper": round(y0 + std, 2),
        "lower": round(y0 - std, 2),
    }


def _support_pressure(
    closes: list[float], highs: list[float], lows: list[float],
    ma20: float | None, ma60: float | None,
) -> dict[str, Any]:
    """支撑/压力:近 20/60 日高低点 + MA20/MA60(最近值)"""
    if not closes:
        return {"support": [], "pressure": []}
    close = closes[-1]
    win20 = max(20, len(closes) - 5)
    lo20 = min(lows[-win20:])
    hi20 = max(highs[-win20:])
    lo60 = min(lows)
    hi60 = max(highs)

    supports: list[float] = []
    for v in (ma20, ma60, lo20, lo60):
        if v is not None and v <= close and v > 0:
            supports.append(round(v, 2))
    pressures: list[float] = []
    for v in (ma20, ma60, hi20, hi60):
        if v is not None and v >= close and v > 0:
            pressures.append(round(v, 2))

    support = sorted({round(s, 2) for s in supports}, reverse=True)[:3]
    pressure = sorted({round(p, 2) for p in pressures})[:3]
    return {"support": support, "pressure": pressure}


def _stabilize(
    closes: list[float], lows: list[float], volumes: list[int],
    ma20: float | None,
) -> dict[str, Any]:
    """企稳检测(三段式):站上 MA20 + 回踩不破前低 + 放量突破

    企稳价位 = max(MA20, 前20日低点),即"站住该位不破视为企稳"。
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
    if len(volumes) >= 6:
        avg5 = mean(volumes[-6:-1])
        breakout_volume = volumes[-1] > avg5
    reasons.append({
        "name": "放量突破",
        "ok": breakout_volume,
        "note": f"末日量 {volumes[-1] if volumes else 0} vs 前5日均量 {round(avg5) if len(volumes) >= 6 else '-'}",
    })

    price = round(max(ma20, prior_low) if prior_low is not None else ma20, 2)
    return {
        "state": above_ma20 and pullback_holds and breakout_volume,
        "price": price,
        "reasons": reasons,
    }


def compute_indicators(klines: list[dict[str, Any]]) -> dict[str, Any]:
    """主入口:输入升序日K列表,输出全部指标"""
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

    vol_ratio = _volume_ratio(volumes)
    if vol_ratio is None:
        vol_state = None
    elif vol_ratio >= 1.5:
        vol_state = "expand"
    elif vol_ratio <= 0.7:
        vol_state = "shrink"
    else:
        vol_state = "normal"

    return {
        "latest_close": round(closes[-1], 2),
        "ma": {
            "ma5": last(ma5),
            "ma10": last(ma10),
            "ma20": last(ma20),
            "ma60": last(ma60),
        },
        "ma_series": {
            "ma5": [v for v in ma5 if v is not None][-60:],
            "ma10": [v for v in ma10 if v is not None][-60:],
            "ma20": [v for v in ma20 if v is not None][-60:],
            "ma60": [v for v in ma60 if v is not None][-60:],
        },
        "volume": {
            "ratio": vol_ratio,
            "state": vol_state,
        },
        "channel": _channel(closes, window=60),
        "support_pressure": _support_pressure(closes, highs, lows, last(ma20), last(ma60)),
        "stabilize": _stabilize(closes, lows, volumes, last(ma20)),
    }
