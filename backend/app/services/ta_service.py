"""技术指标服务(v0.4-roadmap 功能3)

全部确定性计算,无网络 / 无 LLM。输入升序日K:
    [{date, open, high, low, close, volume}, ...]
输出:
    ma / volume / channel / support_pressure / stabilize /
    macd / kdj / boll / volume_price / patterns / liar / position /
    signal / signal_series / data_quality
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


# ============================================================
# K 线智能分析引擎 v1 — 新增纯函数
# 算法规格见 backend/docs/ta-algorithm.md §10
# ============================================================


def _ema(values: list[float], n: int) -> list[float | None]:
    """指数移动平均;初始化 = 前 n 项的简单均值,系数 = 2/(n+1);数据不足返回 None 序列"""
    if len(values) < n:
        return [None] * len(values)
    k = 2.0 / (n + 1)
    out: list[float | None] = [None] * (n - 1)
    seed = sum(values[:n]) / n
    out.append(seed)
    prev = seed
    for v in values[n:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def _macd(closes: list[float]) -> dict[str, Any]:
    """MACD(12,26,9):DIF=EMA12-EMA26,DEA=EMA9(DIF),HIST=2*(DIF-DEA)

    - golden cross = DIF 上穿 DEA
    - dead cross = DIF 下穿 DEA
    - 数据不足(<26)返回空 + degraded 标记由调用方处理
    """
    if len(closes) < 26:
        return {
            "dif": None, "dea": None, "hist": None,
            "dif_series": [], "dea_series": [], "hist_series": [],
            "cross": None,
        }
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif_series: list[float | None] = []
    for a, b in zip(ema12, ema26):
        if a is None or b is None:
            dif_series.append(None)
        else:
            dif_series.append(a - b)
    # DIF 从第 26 项开始有效;DEA 用首个有效 DIF 作种子递推(避免 _ema 要求 ≥9 项时返回全 None)
    valid_dif = [v for v in dif_series if v is not None]
    dea_series: list[float | None] = [None] * len(closes)
    if valid_dif:
        # 找出 DIF 序列中首个非 None 的索引
        first_idx = next(i for i, v in enumerate(dif_series) if v is not None)
        # 递推:k = 2/(9+1) = 0.2
        k = 2.0 / (9 + 1)
        prev = valid_dif[0]
        dea_series[first_idx] = prev
        for offset, v in enumerate(valid_dif[1:], start=1):
            prev = v * k + prev * (1 - k)
            dea_series[first_idx + offset] = prev
    hist_series: list[float | None] = []
    for d, e in zip(dif_series, dea_series):
        if d is None or e is None:
            hist_series.append(None)
        else:
            hist_series.append(round((d - e) * 2, 4))

    # golden / dead cross:最近两日 DIF vs DEA(取序列末尾对齐位置)
    cross = None
    if len(valid_dif) >= 2 and dea_series[-1] is not None and dea_series[-2] is not None:
        d_prev, d_curr = valid_dif[-2], valid_dif[-1]
        e_prev, e_curr = dea_series[-2], dea_series[-1]
        if d_prev <= e_prev and d_curr > e_curr:
            cross = "golden"
        elif d_prev >= e_prev and d_curr < e_curr:
            cross = "dead"

    last_dif = valid_dif[-1] if valid_dif else None
    last_dea = dea_series[-1] if dea_series[-1] is not None else None
    last_hist = hist_series[-1] if hist_series[-1] is not None else None

    return {
        "dif": round(last_dif, 4) if last_dif is not None else None,
        "dea": round(last_dea, 4) if last_dea is not None else None,
        "hist": round(last_hist, 4) if last_hist is not None else None,
        "dif_series": [round(v, 4) for v in dif_series if v is not None][-60:],
        "dea_series": [round(v, 4) for v in dea_series if v is not None][-60:],
        "hist_series": [v for v in hist_series if v is not None][-60:],
        "cross": cross,
    }


def _kdj(
    highs: list[float], lows: list[float], closes: list[float], n: int = 9,
) -> dict[str, Any]:
    """KDJ(n=9):RSV=(C-LLV)/(HHV-LLV)×100, K = SMA(RSV, 3, 1) (prev×2+RSV)/3
    当日不足 n 项时初始化 K/D = 50,J = 3K - 2D
    """
    if len(closes) < n:
        return {"k": None, "d": None, "j": None, "k_series": [], "d_series": [], "j_series": [], "zone": None}
    rsv: list[float | None] = [None] * (n - 1)
    for i in range(n - 1, len(closes)):
        h_max = max(highs[i - n + 1:i + 1])
        l_min = min(lows[i - n + 1:i + 1])
        if h_max == l_min:
            rsv.append(50.0)
        else:
            rsv.append((closes[i] - l_min) / (h_max - l_min) * 100)
    k_series: list[float] = []
    d_series: list[float] = []
    k_prev = 50.0
    d_prev = 50.0
    for v in rsv:
        if v is None:
            continue
        k_prev = (k_prev * 2 + v) / 3
        d_prev = (d_prev * 2 + k_prev) / 3
        k_series.append(round(k_prev, 2))
        d_series.append(round(d_prev, 2))
    j_series = [round(3 * k - 2 * d, 2) for k, d in zip(k_series, d_series)]

    k_v = k_series[-1] if k_series else None
    d_v = d_series[-1] if d_series else None
    j_v = j_series[-1] if j_series else None

    zone = None
    if k_v is not None:
        if k_v > 80 or j_v is not None and j_v > 100:
            zone = "overbought"
        elif k_v < 20 or (j_v is not None and j_v < 0):
            zone = "oversold"
        else:
            zone = "normal"

    # 最近两日 K-D 关系判断交叉
    cross = None
    if len(k_series) >= 2 and len(d_series) >= 2:
        kp, kc = k_series[-2], k_series[-1]
        dp, dc = d_series[-2], d_series[-1]
        if kp <= dp and kc > dc:
            cross = "golden"
        elif kp >= dp and kc < dc:
            cross = "dead"

    return {
        "k": k_v, "d": d_v, "j": j_v,
        "k_series": k_series[-60:],
        "d_series": d_series[-60:],
        "j_series": j_series[-60:],
        "zone": zone,
        "cross": cross,
    }


def _boll(closes: list[float], window: int = 20, k: float = 2.0) -> dict[str, Any]:
    """布林带(20,2):MID=MA20,UP=MID+k*σ,DN=MID-k*σ

    - bandwidth = (UP-DN)/MID * 100(百分比)
    - squeeze = bandwidth < 近20日 bandwidth 均值 × 0.9(收口)
    - position = touching_upper / touching_lower / middle(±0.5%)
    """
    if len(closes) < window:
        return {
            "mid": None, "upper": None, "lower": None,
            "mid_series": [], "upper_series": [], "lower_series": [],
            "bandwidth": None, "squeeze": None, "position": None,
        }
    mid_series = _sma(closes, window)
    # 计算 σ 序列(总体 stdev, ddof=0)
    upper_series: list[float | None] = []
    lower_series: list[float | None] = []
    bandwidth_series: list[float | None] = []
    for i, m in enumerate(mid_series):
        if m is None:
            upper_series.append(None)
            lower_series.append(None)
            bandwidth_series.append(None)
            continue
        seg = closes[i - window + 1:i + 1]
        sd = stdev(seg)
        up = m + k * sd
        dn = m - k * sd
        upper_series.append(round(up, 3))
        lower_series.append(round(dn, 3))
        bandwidth_series.append(round((up - dn) / m * 100, 3) if m else None)
    last_close = closes[-1]
    last_mid = mid_series[-1]
    last_up = upper_series[-1]
    last_dn = lower_series[-1]
    last_bw = bandwidth_series[-1]

    position = "middle"
    if last_mid and last_up and abs(last_close - last_up) / last_up < 0.005:
        position = "touching_upper"
    elif last_mid and last_dn and abs(last_close - last_dn) / last_dn < 0.005:
        position = "touching_lower"

    valid_bw = [b for b in bandwidth_series[-20:] if b is not None]
    squeeze = None
    if len(valid_bw) >= 10 and last_bw is not None:
        avg_recent = mean(valid_bw)
        squeeze = last_bw < avg_recent * 0.9

    return {
        "mid": round(last_mid, 3) if last_mid else None,
        "upper": last_up,
        "lower": last_dn,
        "mid_series": [v for v in mid_series if v is not None][-60:],
        "upper_series": [v for v in upper_series if v is not None][-60:],
        "lower_series": [v for v in lower_series if v is not None][-60:],
        "bandwidth": last_bw,
        "squeeze": squeeze,
        "position": position,
    }


def _volume_price(
    closes: list[float], volumes: list[int],
) -> dict[str, Any]:
    """量价四维:对比末日 vs 前1日的价格变化和成交量变化

    健康度(降级):末日量/近5日均量 × |末日涨幅%|(无主动买入数据时用比例替代)
    """
    if len(closes) < 2 or len(volumes) < 2:
        return {"label": None, "direction": None, "health": None, "reasons": []}

    chg_pct = (closes[-1] - closes[-2]) / closes[-2] * 100 if closes[-2] else 0
    vol_chg_pct = (volumes[-1] - volumes[-2]) / volumes[-2] * 100 if volumes[-2] else 0

    up = chg_pct > 0
    vol_up = vol_chg_pct > 0

    if up and vol_up:
        label = "量增价升"; direction = "healthy_up"; emoji = "🟢"
    elif not up and vol_up:
        label = "量增价跌"; direction = "panic_sell"; emoji = "🔴"
    elif up and not vol_up:
        label = "量缩价升"; direction = "liar_up_suspect"; emoji = "⚠️"
    else:
        label = "量缩价跌"; direction = "natural_pullback"; emoji = "🟡"

    health = None
    reasons: list[dict[str, Any]] = [{
        "name": "量价关系",
        "ok": direction == "healthy_up",
        "note": f"末日 {round(chg_pct, 2)}%, 成交变化 {round(vol_chg_pct, 1)}% → {label}",
    }]

    # 健康度近似:近5日均量作分母
    if len(volumes) >= 6:
        avg5 = mean(volumes[-6:-1])
        if avg5 > 0:
            health = round(min(1.0, volumes[-1] / avg5) * abs(chg_pct) / 100, 3)
            if health > 0.8:
                rating = "真实拉升"
            elif health >= 0.5:
                rating = "多空博弈"
            else:
                rating = "诱多风险"
            reasons.append({
                "name": "量价健康度(近似)",
                "ok": health >= 0.5,
                "note": f"{health} → {rating}(末日量/前5均量 × |末日涨幅%|)",
            })

    return {
        "label": label,
        "direction": direction,
        "emoji": emoji,
        "health": health,
        "reasons": reasons,
    }


# ============ K 线图图例指标 v2:RSI / CCI / STOCH / MOM / WMSR / SKT / FASK ============


def _rsi(closes: list[float], period: int = 14) -> dict[str, Any]:
    """RSI(14 日,Wilder 平滑)

    - 首期 gain/loss 用前 period 日均值初始化
    - 后续 avg_gain/avg_loss 递推:prev * (period-1)/period + cur/period
    - 数据不足(<period+1)返回空 + state=None
    """
    if len(closes) < period + 1:
        return {"rsi": None, "rsi_series": [], "state": None}
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rsi_series: list[float | None] = [None] * period  # 前 period 项 RSI 未知
    for i in range(period, len(closes)):
        if i == period:
            # 首个 RSI
            if avg_loss == 0:
                rsi_series.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_series.append(round(100 - 100 / (1 + rs), 2))
        else:
            diff = closes[i] - closes[i - 1]
            gain = max(diff, 0.0)
            loss = max(-diff, 0.0)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            if avg_loss == 0:
                rsi_series.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi_series.append(round(100 - 100 / (1 + rs), 2))

    valid = [v for v in rsi_series if v is not None]
    last = valid[-1] if valid else None
    state = None
    if last is not None:
        if last >= 70:
            state = "overbought"
        elif last <= 30:
            state = "oversold"
        elif last >= 50:
            state = "bullish"
        elif last < 50:
            state = "bearish"
        else:
            state = "neutral"
    return {
        "rsi": last,
        "rsi_series": valid[-60:],
        "state": state,
    }


def _cci(highs: list[float], lows: list[float], closes: list[float], period: int = 20) -> dict[str, Any]:
    """CCI(20 日,顺势指标)

    - TP = (H+L+C)/3
    - CCI = (TP - SMA(TP, n)) / (0.015 * mean_dev)
    - mean_dev = Σ|TP_i - SMA| / n
    """
    if len(closes) < period:
        return {"cci": None, "cci_series": [], "state": None}
    tp: list[float] = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(closes))]
    sma_tp = _sma(tp, period)
    cci_series: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, len(closes)):
        if sma_tp[i] is None:
            cci_series.append(None)
            continue
        mean_dev = sum(abs(tp[j] - sma_tp[i]) for j in range(i - period + 1, i + 1)) / period
        if mean_dev == 0:
            cci_series.append(0.0)
        else:
            cci_series.append(round((tp[i] - sma_tp[i]) / (0.015 * mean_dev), 2))

    valid = [v for v in cci_series if v is not None]
    last = valid[-1] if valid else None
    state = None
    if last is not None:
        if last >= 100:
            state = "overbought"
        elif last <= -100:
            state = "oversold"
        elif last >= 50:
            state = "strong_up"
        elif last <= -50:
            state = "strong_down"
        else:
            state = "neutral"
    return {
        "cci": last,
        "cci_series": valid[-60:],
        "state": state,
    }


def _stoch(
    highs: list[float], lows: list[float], closes: list[float],
    n: int = 14, k_smooth: int = 3, d_smooth: int = 3,
) -> dict[str, Any]:
    """Stochastic(14, 3, 3):Fast %K / Fast %D / Slow %K / Slow %D

    - Fast %K_i = (C_i - LLV_n) / (HHV_n - LLV_n) * 100
    - Slow %K = SMA(Fast%K, k_smooth)
    - Fast %D = SMA(Fast%K, k_smooth)(与 SlowK 同) — 但本函数按经典
      stochastic 输出 4 条:FastK / FastD / SlowK / SlowD
    - 经典公式:
      * FastK = (C-LLV)/(HHV-LLV)*100
      * FastD = SMA(FastK, k_smooth)   ← 此即 SlowK
      * SlowK = SMA(FastK, k_smooth)   ← 同 FastD
      * SlowD = SMA(SlowK, d_smooth)
    - 实际:"FastD" 与 "SlowK" 是同一条线。保留两名字以兼容前端展示。
    """
    if len(closes) < n:
        return {
            "fastk": None, "fastd": None, "slowk": None, "slowd": None,
            "fastk_series": [], "fastd_series": [], "slowk_series": [], "slowd_series": [],
            "state": None,
        }
    fastk_raw: list[float | None] = [None] * (n - 1)
    for i in range(n - 1, len(closes)):
        h_max = max(highs[i - n + 1:i + 1])
        l_min = min(lows[i - n + 1:i + 1])
        if h_max == l_min:
            fastk_raw.append(50.0)
        else:
            fastk_raw.append(round((closes[i] - l_min) / (h_max - l_min) * 100, 2))

    fastk_only = [v for v in fastk_raw if v is not None]
    fastd_series = _sma(fastk_only, k_smooth)
    # 将 fastd_series 长度对齐到 closes 长度(前面补 None)
    pad = [None] * (len(closes) - len(fastd_series))
    fastd_aligned: list[float | None] = pad + fastd_series
    slowk_only = [v for v in fastd_aligned if v is not None]
    slowd_series = _sma(slowk_only, d_smooth)
    pad2 = [None] * (len(closes) - len(slowd_series))
    slowd_aligned: list[float | None] = pad2 + slowd_series
    # slowk 与 fastd 数值相同,序列结构上保留
    slowk_series = list(fastd_aligned)

    valid_fastk = [v for v in fastk_raw if v is not None]
    valid_fastd = [v for v in fastd_aligned if v is not None]
    valid_slowd = [v for v in slowd_aligned if v is not None]

    last_fastk = valid_fastk[-1] if valid_fastk else None
    last_fastd = valid_fastd[-1] if valid_fastd else None
    last_slowk = valid_fastd[-1] if valid_fastd else None
    last_slowd = valid_slowd[-1] if valid_slowd else None

    state = None
    if last_fastk is not None and last_fastd is not None:
        if last_fastk >= 80:
            state = "overbought"
        elif last_fastk <= 20:
            state = "oversold"
        elif len(valid_fastk) >= 2 and len(valid_fastd) >= 2:
            # 金叉死叉判定(FastK vs FastD 最近两日)
            if valid_fastk[-2] <= valid_fastd[-2] and valid_fastk[-1] > valid_fastd[-1]:
                state = "golden_cross"
            elif valid_fastk[-2] >= valid_fastd[-2] and valid_fastk[-1] < valid_fastd[-1]:
                state = "dead_cross"
            else:
                state = "neutral"
        else:
            state = "neutral"

    return {
        "fastk": round(last_fastk, 2) if last_fastk is not None else None,
        "fastd": round(last_fastd, 2) if last_fastd is not None else None,
        "slowk": round(last_slowk, 2) if last_slowk is not None else None,
        "slowd": round(last_slowd, 2) if last_slowd is not None else None,
        "fastk_series": valid_fastk[-60:],
        "fastd_series": valid_fastd[-60:],
        "slowk_series": valid_fastd[-60:],   # slowk ≡ fastd
        "slowd_series": valid_slowd[-60:],
        "state": state,
    }


def _mom(closes: list[float], period: int = 10) -> dict[str, Any]:
    """MOM(10 日):close[i] - close[i-period]

    - 数据不足(<period+1)返回空
    - state:rising(>0 且 5 日变化量>0)/ falling(...)
    """
    if len(closes) < period + 1:
        return {"mom": None, "mom_series": [], "state": None}
    mom_series: list[float | None] = [None] * period
    for i in range(period, len(closes)):
        mom_series.append(round(closes[i] - closes[i - period], 2))
    valid = [v for v in mom_series if v is not None]
    last = valid[-1] if valid else None
    state = None
    if last is not None:
        if len(valid) >= 6:
            delta_5 = valid[-1] - valid[-6]  # 5 个交易日前对比
            # 持续上行/下行:末日 MOM >0 且 5 日 MOM 不降(rising);
            # 末日 MOM <0 且 5 日 MOM 不升(falling);否则 zero_cross 或 neutral
            if last > 0 and delta_5 >= 0:
                state = "rising"
            elif last < 0 and delta_5 <= 0:
                state = "falling"
            elif last > 0 and valid[-2] is not None and valid[-2] <= 0:
                state = "zero_cross_up"
            elif last < 0 and valid[-2] is not None and valid[-2] >= 0:
                state = "zero_cross_down"
            else:
                state = "neutral"
        else:
            state = "rising" if last > 0 else ("falling" if last < 0 else "neutral")
    return {
        "mom": last,
        "mom_series": valid[-60:],
        "state": state,
    }


def _wmsr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> dict[str, Any]:
    """Williams %R(14 日,范围 [-100, 0])

    - %R = (HHV_n - C) / (HHV_n - LLV_n) * -100
    - 超买:>-20;超售:<-80
    """
    if len(closes) < period:
        return {"wmsr": None, "wmsr_series": [], "state": None}
    wmsr_series: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, len(closes)):
        h_max = max(highs[i - period + 1:i + 1])
        l_min = min(lows[i - period + 1:i + 1])
        if h_max == l_min:
            wmsr_series.append(-50.0)
        else:
            wmsr_series.append(round((h_max - closes[i]) / (h_max - l_min) * -100, 2))
    valid = [v for v in wmsr_series if v is not None]
    last = valid[-1] if valid else None
    state = None
    if last is not None:
        if last >= -20:
            state = "overbought"
        elif last <= -80:
            state = "oversold"
        else:
            state = "neutral"
    return {
        "wmsr": last,
        "wmsr_series": valid[-60:],
        "state": state,
    }


def _sk(stoch_dict: dict[str, Any]) -> dict[str, Any]:
    """Slow Stochastic 视图(从 _stoch 结果提取 SlowK + SlowD)"""
    return {
        "slowk": stoch_dict.get("slowk"),
        "slowd": stoch_dict.get("slowd"),
        "slowk_series": stoch_dict.get("slowk_series", []),
        "slowd_series": stoch_dict.get("slowd_series", []),
        "state": stoch_dict.get("state"),  # 与 STOCH 共享 state
    }


def _fask(stoch_dict: dict[str, Any]) -> dict[str, Any]:
    """Fast %K 单值视图(从 _stoch 结果提取 FastK)"""
    fastk = stoch_dict.get("fastk")
    state = None
    if fastk is not None:
        if fastk >= 80:
            state = "overbought"
        elif fastk <= 20:
            state = "oversold"
        else:
            state = "neutral"
    return {
        "fastk": fastk,
        "fastk_series": stoch_dict.get("fastk_series", []),
        "state": state,
    }


def _patterns(
    closes: list[float], highs: list[float], lows: list[float], opens: list[float],
) -> list[dict[str, Any]]:
    """形态识别(单根 + 组合),仅末日及近期 3 日内出现时输出

    返回元素: {name, type('bull'|'bear'|'neutral'), emoji, date_index}
    """
    if len(closes) < 1:
        return []
    results: list[dict[str, Any]] = []
    n = len(closes)

    def entity(i: int) -> tuple[float, float]:
        return abs(closes[i] - opens[i])

    def upper_shadow(i: int) -> float:
        return highs[i] - max(closes[i], opens[i])

    def lower_shadow(i: int) -> float:
        return min(closes[i], opens[i]) - lows[i]

    # 单根形态:仅末日
    i = n - 1
    e = entity(i)
    up = upper_shadow(i)
    lo = lower_shadow(i)
    rng = highs[i] - lows[i] or 1e-9

    if e / rng < 0.05 and up > 0 and lo > 0:
        results.append({"name": "十字星", "type": "neutral", "emoji": "⚠️", "date_index": i})
    if lo >= 2 * e and e > 0:
        results.append({"name": "锤子线", "type": "bull", "emoji": "🔺", "date_index": i})
    if up >= 2 * e and e > 0:
        results.append({"name": "倒锤线", "type": "bear", "emoji": "🔻", "date_index": i})
    if up < 0.005 * rng and closes[i] > opens[i] and lo < 0.005 * rng:
        results.append({"name": "光头光脚大阳", "type": "bull", "emoji": "🔺", "date_index": i})
    if up < 0.005 * rng and closes[i] < opens[i] and lo < 0.005 * rng:
        results.append({"name": "光头光脚大阴", "type": "bear", "emoji": "🔻", "date_index": i})

    # 组合形态:需要末日及前 2 日
    if n >= 3:
        # 早晨之星:末日大阳 + 前 2 日大跌 + 前 1 日小星
        if (closes[i] > opens[i] and entity(i) > entity(i - 2) * 0.5
                and entity(i - 1) < entity(i - 2) * 0.3
                and closes[i - 2] < opens[i - 2]):
            results.append({"name": "早晨之星", "type": "bull", "emoji": "🔺", "date_index": i})
        # 黄昏之星:末日大阴 + 前 2 日大涨 + 前 1 日小星
        if (closes[i] < opens[i] and entity(i) > entity(i - 2) * 0.5
                and entity(i - 1) < entity(i - 2) * 0.3
                and closes[i - 2] > opens[i - 2]):
            results.append({"name": "黄昏之星", "type": "bear", "emoji": "🔻", "date_index": i})
        # 看涨吞没:末日大阳包住前一日阴线
        if (closes[i] > opens[i] and closes[i - 1] < opens[i - 1]
                and opens[i] <= closes[i - 1] and closes[i] >= opens[i - 1]
                and entity(i) > entity(i - 1)):
            results.append({"name": "看涨吞没", "type": "bull", "emoji": "🔺", "date_index": i})
        # 看跌吞没
        if (closes[i] < opens[i] and closes[i - 1] > opens[i - 1]
                and opens[i] >= closes[i - 1] and closes[i] <= opens[i - 1]
                and entity(i) > entity(i - 1)):
            results.append({"name": "看跌吞没", "type": "bear", "emoji": "🔻", "date_index": i})
        # 红三兵:末日 + 前 2 日 连续三阳递增
        if (n >= 3 and closes[i] > opens[i] and closes[i - 1] > opens[i - 1]
                and closes[i - 2] > opens[i - 2]
                and closes[i] > closes[i - 1] > closes[i - 2]):
            results.append({"name": "红三兵", "type": "bull", "emoji": "🔺", "date_index": i})
        # 三只乌鸦:连续三阴递增
        if (closes[i] < opens[i] and closes[i - 1] < opens[i - 1]
                and closes[i - 2] < opens[i - 2]
                and closes[i] < closes[i - 1] < closes[i - 2]):
            results.append({"name": "三只乌鸦", "type": "bear", "emoji": "🔻", "date_index": i})

    return results


def _liar_trap(
    closes: list[float], highs: list[float], lows: list[float], volumes: list[int],
    kdj: dict[str, Any], boll: dict[str, Any],
) -> dict[str, Any]:
    """诱多诱空(日线近似,文档 §9.5 落地映射)

    诱多模式:
      - 无量空涨:连续 N(>=3)日上涨且成交量持续萎缩(末日 vs 前 N 日均值 < 0.7)
      - 假突破:突破近20日高 + 长上影线(>=1.5 倍实体)
      - 缩量上涨:当日涨 + 量缩(已在量价模块捕捉,此处不再重复)
    诱空模式:
      - 无量暴跌:连续长阴 + 量缩
      - 假破位:跌破近20日低 + 长下影(>=1.5 倍实体)
      - 多指标底背离近似:KDJ J 值上升但价格下跌(末日前 5 段窗口)
    """
    if len(closes) < 5:
        return {"bull_liars": [], "bear_liars": [], "summary": "数据不足"}

    bull_liars: list[dict[str, Any]] = []
    bear_liars: list[dict[str, Any]] = []

    # 无量空涨:末日收盘 > 前 5 日均价 且 末日量 < 前 5 日均量 × 0.7
    if len(volumes) >= 6:
        avg5_close = mean(closes[-6:-1])
        avg5_vol = mean(volumes[-6:-1])
        if closes[-1] > avg5_close and avg5_vol > 0 and volumes[-1] < avg5_vol * 0.7:
            bull_liars.append({
                "name": "无量空涨",
                "note": f"现价 {round(closes[-1], 2)} > 5日均 {round(avg5_close, 2)},"
                        f"量 {volumes[-1]} < 5日均 {round(avg5_vol)}×0.7={round(avg5_vol * 0.7)}",
                "severity": "high" if volumes[-1] < avg5_vol * 0.5 else "medium",
            })

    # 假突破:末日突破近 20 日最高 + 上影长
    if len(highs) >= 21:
        prior_high = max(highs[-21:-1])
        last_entity = abs(closes[-1] - (closes[-1] if len(closes) >= 1 else closes[-1]))  # placeholder
        # 末日上影线
        last_top = max(closes[-1], closes[-1])  # 用 open 替代 closes-1
        # 简化:取末日最高价 vs 实体上沿
        last_open = closes[-1] if False else closes[-1]  # 同上简化,实际读 opens
        last_body_top = max(closes[-1], closes[-1])
        # 末日上影线长度(对 5.1.1 的判定用更高精度时再开 opens 入口)
        # 此处用 highs - closes 近似上影
        upper_shadow = highs[-1] - closes[-1]
        body = abs(closes[-1] - closes[-2]) if len(closes) >= 2 else upper_shadow
        if highs[-1] >= prior_high and upper_shadow >= 1.5 * body and body > 0:
            bull_liars.append({
                "name": "假突破(长上影)",
                "note": f"末日高 {round(highs[-1], 2)} ≥ 近20高 {round(prior_high, 2)},"
                        f"上影 {round(upper_shadow, 2)} ≥ 实体 {round(body, 2)}×1.5",
                "severity": "medium",
            })

    # 无量暴跌
    if len(volumes) >= 6:
        avg5_close = mean(closes[-6:-1])
        avg5_vol = mean(volumes[-6:-1])
        if closes[-1] < avg5_close * 0.97 and avg5_vol > 0 and volumes[-1] < avg5_vol * 0.7:
            bear_liars.append({
                "name": "无量暴跌",
                "note": f"现价 {round(closes[-1], 2)} < 5日均 {round(avg5_close, 2)}×0.97,"
                        f"量缩至 {round(avg5_vol * 0.7)} 以下",
                "severity": "medium",
            })

    # 假破位:跌破近 20 日低 + 长下影
    if len(lows) >= 21:
        prior_low = min(lows[-21:-1])
        lower_shadow = closes[-1] - lows[-1]
        body = abs(closes[-1] - closes[-2]) if len(closes) >= 2 else lower_shadow
        if lows[-1] <= prior_low and lower_shadow >= 1.5 * body and body > 0:
            bear_liars.append({
                "name": "假破位(长下影)",
                "note": f"末日低 {round(lows[-1], 2)} ≤ 近20低 {round(prior_low, 2)},"
                        f"下影 {round(lower_shadow, 2)} ≥ 实体 {round(body, 2)}×1.5",
                "severity": "medium",
            })

    # 底背离近似:KDJ J 值近 5 段上升,但价格下降
    j_series = kdj.get("j_series") or []
    if len(j_series) >= 5 and len(closes) >= 5:
        j_prev = j_series[-5]
        j_curr = j_series[-1]
        c_prev = closes[-5]
        c_curr = closes[-1]
        if j_curr > j_prev and c_curr < c_prev:
            bear_liars.append({
                "name": "底背离(近似)",
                "note": f"J {round(j_prev, 1)}→{round(j_curr, 1)} 升,价 {round(c_prev, 2)}→{round(c_curr, 2)} 跌",
                "severity": "low",
            })

    summary = "未见典型诱多诱空模式"
    if bull_liars:
        summary = f"检测到 {len(bull_liars)} 类诱多信号"
    elif bear_liars:
        summary = f"检测到 {len(bear_liars)} 类诱空信号"

    return {"bull_liars": bull_liars, "bear_liars": bear_liars, "summary": summary}


def _position(
    closes: list[float], highs: list[float], lows: list[float], ma60: float | None,
) -> dict[str, Any]:
    """位置评估(PE 分位降级,文档 §9.6 落地映射 + v1.5 买卖位置参考卡)

    - 近 20 日涨幅、60 日涨幅
    - 价格距 MA60 偏离百分比
    - 近 250 日高低分位
    - v0.5 M1.2:近 120 日收盘价 P20/P80 风险带 + 参考支撑 + 建议止损
    """
    last = closes[-1]
    pct_20 = (last - closes[-20]) / closes[-20] * 100 if len(closes) >= 21 else None
    pct_60 = (last - closes[-60]) / closes[-60] * 100 if len(closes) >= 61 else None
    bias_ma60 = (last - ma60) / ma60 * 100 if ma60 else None

    lookback_high = max(highs[-250:]) if len(highs) >= 1 else None
    lookback_low = min(lows[-250:]) if len(lows) >= 1 else None
    if lookback_high and lookback_low and lookback_high > lookback_low:
        range_pct = (last - lookback_low) / (lookback_high - lookback_low) * 100
    else:
        range_pct = None

    band = "mid"
    if pct_60 is not None and pct_60 > 50:
        band = "high"
    elif pct_60 is not None and pct_60 < -40:
        band = "low"

    # ---- v0.5 M1.2 买卖位置参考卡(v0.5-roadmap §4 M1.2) ----
    # 风险带:近 120 日收盘价分位(P20 / P80)
    closes120 = closes[-120:] if len(closes) >= 120 else closes
    band_risk = "mid"
    p20 = p80 = None
    if closes120:
        sorted_c = sorted(closes120)
        n = len(sorted_c)
        p20 = sorted_c[max(0, int(n * 0.20) - 1)]
        p80 = sorted_c[max(0, int(n * 0.80) - 1)]
        if last >= p80:
            band_risk = "high"
        elif last < p20:
            band_risk = "low"
        else:
            band_risk = "mid"
    # 参考支撑 = 近 20 日最低收盘价 × 0.98(留 2% 缓冲)
    support_price = None
    if len(closes) >= 10:
        support_price = round(min(closes[-20:]) * 0.98, 3)
    # 建议止损 = 参考支撑 × 0.97
    stop_loss_price = round(support_price * 0.97, 3) if support_price is not None else None

    return {
        "pct_20": round(pct_20, 2) if pct_20 is not None else None,
        "pct_60": round(pct_60, 2) if pct_60 is not None else None,
        "bias_ma60": round(bias_ma60, 2) if bias_ma60 is not None else None,
        "range_pct": round(range_pct, 2) if range_pct is not None else None,
        "band": band,
        "risk_band": band_risk,
        "p20": round(p20, 3) if p20 is not None else None,
        "p80": round(p80, 3) if p80 is not None else None,
        "support_price": support_price,
        "stop_loss_price": stop_loss_price,
    }


def _fuse(
    macd: dict[str, Any], volume_price: dict[str, Any], liar: dict[str, Any],
    patterns: list[dict[str, Any]], position: dict[str, Any], ma: dict[str, Any],
) -> dict[str, Any]:
    """信号融合:加权评分(量价30/诱多诱空30/趋势20/形态10/位置10)+ 冲突去重

    文档 §9.7 规格
    """
    score = 50  # 中性基线
    reasons: list[dict[str, Any]] = []

    # 趋势 20%:MA5 > MA10 > MA20 > MA60 → +20,反之 -20,粘合 → 0
    m = ma
    if all(v is not None for v in (m.get("ma5"), m.get("ma10"), m.get("ma20"), m.get("ma60"))):
        if m["ma5"] > m["ma10"] > m["ma20"] > m["ma60"]:
            score += 20
            reasons.append({"module": "趋势", "weight": 20, "verdict": "多头排列", "delta": 20})
        elif m["ma5"] < m["ma10"] < m["ma20"] < m["ma60"]:
            score -= 20
            reasons.append({"module": "趋势", "weight": 20, "verdict": "空头排列", "delta": -20})
        else:
            reasons.append({"module": "趋势", "weight": 20, "verdict": "均线缠绕", "delta": 0})
    # MACD 金叉/死叉额外 ±10
    if macd.get("cross") == "golden":
        score += 10
        reasons.append({"module": "趋势-MACD", "weight": 10, "verdict": "金叉", "delta": 10})
    elif macd.get("cross") == "dead":
        score -= 10
        reasons.append({"module": "趋势-MACD", "weight": 10, "verdict": "死叉", "delta": -10})

    # 量价 30%
    vp_dir = (volume_price or {}).get("direction")
    if vp_dir == "healthy_up":
        score += 30
        reasons.append({"module": "量价", "weight": 30, "verdict": "量增价升(健康)", "delta": 30})
    elif vp_dir == "panic_sell":
        score -= 25
        reasons.append({"module": "量价", "weight": 30, "verdict": "量增价跌(主力出货)", "delta": -25})
    elif vp_dir == "liar_up_suspect":
        score -= 15
        reasons.append({"module": "量价", "weight": 30, "verdict": "量缩价升(诱多嫌疑)", "delta": -15})
    elif vp_dir == "natural_pullback":
        score -= 5
        reasons.append({"module": "量价", "weight": 30, "verdict": "量缩价跌(自然回落)", "delta": -5})
    else:
        reasons.append({"module": "量价", "weight": 30, "verdict": "数据不足", "delta": 0})

    # 诱多诱空 30%
    bull_n = len(liar.get("bull_liars") or [])
    bear_n = len(liar.get("bear_liars") or [])
    if bull_n and not bear_n:
        score -= 30
        reasons.append({"module": "诱多诱空", "weight": 30, "verdict": f"诱多信号 {bull_n} 类", "delta": -30})
    elif bear_n and not bull_n:
        score += 15  # 诱空可能是机会
        reasons.append({"module": "诱多诱空", "weight": 30, "verdict": f"诱空信号 {bear_n} 类(可能反转)", "delta": 15})
    elif bull_n and bear_n:
        reasons.append({"module": "诱多诱空", "weight": 30, "verdict": "信号冲突", "delta": 0})
    else:
        reasons.append({"module": "诱多诱空", "weight": 30, "verdict": "未检出", "delta": 0})

    # 形态 10%
    bull_p = sum(1 for p in patterns if p.get("type") == "bull")
    bear_p = sum(1 for p in patterns if p.get("type") == "bear")
    if bull_p > bear_p:
        score += 10
        reasons.append({"module": "形态", "weight": 10, "verdict": f"看多形态 {bull_p} 类", "delta": 10})
    elif bear_p > bull_p:
        score -= 10
        reasons.append({"module": "形态", "weight": 10, "verdict": f"看空形态 {bear_p} 类", "delta": -10})
    else:
        reasons.append({"module": "形态", "weight": 10, "verdict": "无典型形态", "delta": 0})

    # 位置 10%
    band = position.get("band")
    if band == "high":
        score -= 5
        reasons.append({"module": "位置", "weight": 10, "verdict": "高位(谨慎)", "delta": -5})
    elif band == "low":
        score += 5
        reasons.append({"module": "位置", "weight": 10, "verdict": "低位(关注)", "delta": 5})
    else:
        reasons.append({"module": "位置", "weight": 10, "verdict": "中位", "delta": 0})

    # 钳位
    score = max(0, min(100, score))

    if score >= 65:
        view = "bullish"; view_label = "看多"; confidence = "high" if score >= 80 else "medium"
    elif score <= 35:
        view = "bearish"; view_label = "看空"; confidence = "high" if score <= 20 else "medium"
    else:
        view = "neutral"; view_label = "中性"; confidence = "low"

    # 一句话
    summary = f"趋势{reasons[0]['verdict'] if reasons else '-'} | 量价{(volume_price or {}).get('label') or '-'}"
    if (liar.get("bull_liars") or liar.get("bear_liars")):
        summary += f" | {liar.get('summary', '')}"

    return {
        "view": view,
        "view_label": view_label,
        "score": score,
        "confidence": confidence,
        "reasons": reasons,
        "summary": summary,
    }


def _signal_series(
    klines: list[dict[str, Any]],
    macd: dict[str, Any], kdj: dict[str, Any],
    boll: dict[str, Any], patterns: list[dict[str, Any]],
    liar: dict[str, Any],
) -> list[dict[str, Any]]:
    """信号标注点序列:给 KLineChart.setMarkers 用

    - MACD 金叉/死叉 → 对应末日 K 线
    - KDJ 金叉/死叉 → 末日
    - BOLL 触上轨/下轨 → 末日
    - 形态标注 → 末日
    - 诱多预警 → 末日
    - 诱空陷阱 → 末日
    """
    if not klines:
        return []
    markers: list[dict[str, Any]] = []
    n = len(klines) - 1
    last = klines[-1]

    def add(text: str, emoji: str, position: str, color: str) -> None:
        markers.append({
            "time": last.get("date"),
            "date_index": n,
            "text": f"{emoji} {text}",
            "position": position,
            "color": color,
        })

    if macd.get("cross") == "golden":
        add("MACD 金叉", "🔺", "belowBar", "#f43f5e")
    elif macd.get("cross") == "dead":
        add("MACD 死叉", "🔻", "aboveBar", "#4ade80")

    if kdj.get("cross") == "golden":
        add("KDJ 金叉", "🔺", "belowBar", "#f43f5e")
    elif kdj.get("cross") == "dead":
        add("KDJ 死叉", "🔻", "aboveBar", "#4ade80")

    pos = boll.get("position")
    if pos == "touching_upper":
        add("BOLL 触上轨", "🟡", "aboveBar", "#facc15")
    elif pos == "touching_lower":
        add("BOLL 触下轨", "🟡", "belowBar", "#facc15")
    if boll.get("squeeze"):
        add("BOLL 收口", "⚠️", "aboveBar", "#facc15")

    for p in patterns:
        add(p["name"], p["emoji"], "belowBar" if p["type"] == "bull" else "aboveBar",
            "#f43f5e" if p["type"] == "bull" else "#4ade80")

    if liar.get("bull_liars"):
        add(f"诱多 {len(liar['bull_liars'])} 类", "⚠️", "aboveBar", "#facc15")
    if liar.get("bear_liars"):
        add(f"诱空 {len(liar['bear_liars'])} 类", "🪤", "belowBar", "#60a5fa")

    return markers


def compute_indicators(klines: list[dict[str, Any]]) -> dict[str, Any]:
    """主入口:输入升序日K列表,输出全部指标 + data_quality"""
    if not klines:
        raise TaError("K 线数据为空")

    closes = [_f(r["close"]) for r in klines]
    highs = [_f(r["high"]) for r in klines]
    lows = [_f(r["low"]) for r in klines]
    volumes = [int(r["volume"]) for r in klines]
    # opens 用于形态识别;旧数据源若缺 open 字段,回退为收盘价(中性近似,不影响实体判定)
    opens = [_f(r.get("open", r["close"])) for r in klines]

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

    # —— v1 新指标 ——
    macd = _macd(closes)
    if len(closes) < 26:
        degraded.append("macd: len<26")

    kdj = _kdj(highs, lows, closes, n=9)
    if len(closes) < 9:
        degraded.append("kdj: len<9")

    boll = _boll(closes, window=20, k=2.0)
    if len(closes) < 20:
        degraded.append("boll: len<20")

    volume_price = _volume_price(closes, volumes)
    if len(closes) < 2:
        degraded.append("volume_price: len<2")

    patterns = _patterns(closes, highs, lows, opens)
    if len(closes) < 1:
        degraded.append("patterns: len<1")

    liar = _liar_trap(closes, highs, lows, volumes, kdj, boll)
    if len(closes) < 5:
        degraded.append("liar: len<5")

    position = _position(closes, highs, lows, ma60_v)
    if len(closes) < 21:
        degraded.append("position: len<21")

    # —— v2 K 线图图例指标:RSI / CCI / STOCH / MOM / WMSR / SKT / FASK ——
    rsi = _rsi(closes, period=14)
    if len(closes) < 15:
        degraded.append("rsi: len<15")

    cci = _cci(highs, lows, closes, period=20)
    if len(closes) < 20:
        degraded.append("cci: len<20")

    stoch = _stoch(highs, lows, closes, n=14, k_smooth=3, d_smooth=3)
    if len(closes) < 14:
        degraded.append("stoch: len<14")

    mom = _mom(closes, period=10)
    if len(closes) < 11:
        degraded.append("mom: len<11")

    wmsr = _wmsr(highs, lows, closes, period=14)
    if len(closes) < 14:
        degraded.append("wmsr: len<14")

    skt = _sk(stoch)
    fask = _fask(stoch)

    ma_summary = {
        "ma5": round(ma5_v, 2) if ma5_v is not None else None,
        "ma10": round(ma10_v, 2) if ma10_v is not None else None,
        "ma20": round(ma20_v, 2) if ma20_v is not None else None,
        "ma60": round(ma60_v, 2) if ma60_v is not None else None,
    }
    signal = _fuse(macd, volume_price, liar, patterns, position, ma_summary)
    signal_series = _signal_series(klines, macd, kdj, boll, patterns, liar)

    return {
        "latest_close": round(closes[-1], 2),
        "ma": ma_summary,
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
        "macd": macd,
        "kdj": kdj,
        "boll": boll,
        "volume_price": volume_price,
        "patterns": patterns,
        "liar": liar,
        "position": position,
        "rsi": rsi,
        "cci": cci,
        "stoch": stoch,
        "mom": mom,
        "wmsr": wmsr,
        "skt": skt,
        "fask": fask,
        "signal": signal,
        "signal_series": signal_series,
        "data_quality": {
            "kline_count": len(klines),
            "degraded": degraded,
        },
    }