"""M1.3 信号历史胜率回检(纯函数,确定性)

对最近 LOOKBACK 根,逐日以「当天及其之前」的 K 线调用 compute_indicators,
把当天机械信号 view(=看多/看空)记作一次历史信号;若与当前 view 相同,
再看该信号出现后 5 / 20 个交易日的收盘涨跌,汇总胜率。

口径(与 v0.5-roadmap M1.3 一致):
- 「N 日后上涨」= 信号日收盘价 < N 个交易日后收盘价(不含信号日当日收益)。
- 历史同 view 样本过少(< MIN_SAMPLES)时 insufficient=True,前端提示「样本不足」。
"""
from __future__ import annotations

from app.services.ta_service import TaError, compute_indicators

#: 回检窗口(交易日)
LOOKBACK = 120
#: 样本数下限,低于则不给出胜率结论
MIN_SAMPLES = 3
#: 观察窗口(交易日)
HORIZON_5 = 5
HORIZON_20 = 20

_VIEW_LABEL = {"bullish": "看多", "bearish": "看空"}


def compute_signal_winrate(klines: list[dict]) -> dict:
    """回检当前信号(view)的历史胜率

    输入升序日 K;返回 {signal, signal_label, count, up5, up20,
    sample5, sample20, insufficient}。
    """
    if not klines:
        raise TaError("K 线数据为空")

    closes = [float(r["close"]) for r in klines]
    n = len(closes)
    if n < HORIZON_20 + 3:
        raise TaError(f"K 线数据过短(需至少 {HORIZON_20 + 3} 根)")

    # 当前信号 view(对全部数据计算最后一根)
    current = compute_indicators(klines)["signal"]["view"]
    current_label = _VIEW_LABEL.get(current, "中性")

    # 仅回检有意义的样本:信号日之后能留给 HORIZON_20 根,窗口起点留 3 根历史
    start = max(3, n - LOOKBACK)
    up5_count = up20_count = 0
    sample5 = sample20 = 0

    for j in range(start, n - HORIZON_20):
        view = compute_indicators(klines[: j + 1])["signal"]["view"]
        if view != current:
            continue
        cat_close = closes[j]
        if closes[j + HORIZON_5] > cat_close:
            up5_count += 1
        sample5 += 1
        if closes[j + HORIZON_20] > cat_close:
            up20_count += 1
        sample20 += 1

    insufficient = sample5 < MIN_SAMPLES or sample20 < MIN_SAMPLES
    return {
        "signal": current,
        "signal_label": current_label,
        "count": sample5,
        "up5": round(up5_count / sample5, 4) if sample5 else 0.0,
        "up20": round(up20_count / sample20, 4) if sample20 else 0.0,
        "sample5": sample5,
        "sample20": sample20,
        "insufficient": insufficient,
    }


__all__ = ["compute_signal_winrate", "LOOKBACK", "MIN_SAMPLES"]