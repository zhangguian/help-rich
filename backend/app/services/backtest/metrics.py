"""回测绩效指标(纯函数,无 IO)。

指标口径(与常见券商/量化平台一致):
- **总收益率** = 期末净值 / 期初净值 - 1
- **年化收益** = (期末/期初)^(252/交易日数) - 1  (按 A 股 252 交易日)
- **最大回撤** = min(净值/历史最高净值 - 1),报负值
- **年化波动率** = 日收益标准差 * sqrt(252)
- **夏普比率** = 年化收益 / 年化波动率(无风险利率默认 0,可传参)
- **胜率**   = 盈利交易数 / 总交易数
- **盈亏比** = 平均盈利 / 平均亏损的绝对值

所有函数都接受纯 Python 列表(净值序列或收益率序列),便于单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field

TRADING_DAYS_PER_YEAR = 252


@dataclass(slots=True)
class PerformanceMetrics:
    """一套回测绩效指标。所有比率类指标在样本不足时为 None(不编造)。"""

    total_return: float = 0.0
    annual_return: float | None = None
    max_drawdown: float | None = None
    max_drawdown_start: int | None = None   # 回撤谷底在净值序列中的下标
    max_drawdown_peak: int | None = None    # 回撤前的峰值下标
    annual_volatility: float | None = None
    sharpe: float | None = None
    # 交易统计
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float | None = None
    profit_factor: float | None = None     # 盈亏比
    trading_days: int = 0

    def to_dict(self) -> dict:
        return {
            "total_return": round(self.total_return, 6),
            "annual_return": _r(self.annual_return),
            "max_drawdown": _r(self.max_drawdown),
            "annual_volatility": _r(self.annual_volatility),
            "sharpe": _r(self.sharpe, 4),
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": _r(self.win_rate),
            "profit_factor": _r(self.profit_factor),
            "trading_days": self.trading_days,
        }


def _r(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _daily_returns(equity_curve: list[float]) -> list[float]:
    """净值序列 → 日收益率序列。首日视为 0(无前值可比)。"""
    if len(equity_curve) < 2:
        return []
    rets: list[float] = []
    for prev, curr in zip(equity_curve, equity_curve[1:]):
        if prev <= 0:
            rets.append(0.0)
        else:
            rets.append(curr / prev - 1.0)
    return rets


def total_return(equity_curve: list[float], initial_capital: float = 1.0) -> float:
    if not equity_curve or initial_capital <= 0:
        return 0.0
    return equity_curve[-1] / initial_capital - 1.0


def annual_return(
    equity_curve: list[float], initial_capital: float = 1.0, trading_days: int | None = None
) -> float | None:
    """年化收益。交易日不足 1 天或样本太短时返回 None(不外推)。"""
    if not equity_curve or initial_capital <= 0:
        return None
    n = trading_days if trading_days is not None else len(equity_curve) - 1
    if n <= 0:
        return None
    growth = equity_curve[-1] / initial_capital
    if growth <= 0:
        return -1.0
    return growth ** (TRADING_DAYS_PER_YEAR / n) - 1.0


def max_drawdown(equity_curve: list[float]) -> tuple[float | None, int | None, int | None]:
    """最大回撤(负值或 0)及其峰/谷下标。净值单调上升时返回 0.0。"""
    if len(equity_curve) < 2:
        return None, None, None
    peak = equity_curve[0]
    peak_idx = 0
    worst = 0.0
    worst_peak = 0
    worst_trough = 0
    for i, value in enumerate(equity_curve):
        if value > peak:
            peak = value
            peak_idx = i
        if peak > 0:
            dd = value / peak - 1.0
            if dd < worst:
                worst = dd
                worst_peak = peak_idx
                worst_trough = i
    return worst, worst_peak, worst_trough


def annual_volatility(equity_curve: list[float]) -> float | None:
    """年化波动率(日收益标准差 * sqrt(252))。样本 <2 返回 None。"""
    rets = _daily_returns(equity_curve)
    n = len(rets)
    if n < 2:
        return None
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return (var ** 0.5) * (TRADING_DAYS_PER_YEAR ** 0.5)


def sharpe_ratio(
    equity_curve: list[float], initial_capital: float = 1.0, risk_free: float = 0.0
) -> float | None:
    """夏普比率 = (年化收益 - 无风险) / 年化波动率。波动率为 0 时返回 None。"""
    vol = annual_volatility(equity_curve)
    if not vol:
        return None
    ann = annual_return(equity_curve, initial_capital)
    if ann is None:
        return None
    return (ann - risk_free) / vol


def trade_statistics(trade_returns: list[float]) -> dict:
    """按单笔交易收益率统计胜率/盈亏比。

    trade_returns: 每笔已平仓交易的收益率(小数,0.01 = +1%)。
    """
    total = len(trade_returns)
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r < 0]
    out = {
        "total_trades": total,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": None,
        "profit_factor": None,
    }
    if total > 0:
        out["win_rate"] = len(wins) / total
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = abs(sum(losses) / len(losses)) if losses else None
    if avg_win is not None and avg_loss:
        out["profit_factor"] = avg_win / avg_loss
    return out


def compute_metrics(
    equity_curve: list[float],
    initial_capital: float = 1.0,
    trade_returns: list[float] | None = None,
    risk_free: float = 0.0,
) -> PerformanceMetrics:
    """一次性算齐所有指标(主入口)。"""
    mdd, peak, trough = max_drawdown(equity_curve)
    stats = trade_statistics(trade_returns or [])
    return PerformanceMetrics(
        total_return=total_return(equity_curve, initial_capital),
        annual_return=annual_return(equity_curve, initial_capital),
        max_drawdown=mdd,
        max_drawdown_peak=peak,
        max_drawdown_start=trough,
        annual_volatility=annual_volatility(equity_curve),
        sharpe=sharpe_ratio(equity_curve, initial_capital, risk_free),
        **stats,
    )


__all__ = [
    "PerformanceMetrics",
    "TRADING_DAYS_PER_YEAR",
    "annual_return",
    "annual_volatility",
    "compute_metrics",
    "max_drawdown",
    "sharpe_ratio",
    "total_return",
    "trade_statistics",
]
