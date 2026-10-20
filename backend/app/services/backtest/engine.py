"""回测引擎(阶段2)。

设计约束(刻意简化,不追求高频/撮合精度):
- **日线级事件驱动**:按交易日推进,信号在 T 日收盘后产生,T+1 日开盘/收盘成交
- **不复权假设**:使用传入的已复权价格序列(由调用方负责)
- **纯逻辑**:引擎只吃「信号 + 行情」,吐净值与交易记录,不碰 DB
- **A 股规则**:T+1 卖出(当日买入不可当日卖)、100 股整手、10% 涨跌停不阻断回测

时间轴约定(明确写死,避免回测与实盘语义不一致):
```text
D 日: 收到 buy 信号 → 以 D 日 close 建仓
D 日: 收到 sell 信号 → 只能卖出 D 日之前建的仓(T+1)
```
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.backtest.cost_model import CostModel, DEFAULT_COST_MODEL
from app.services.backtest.metrics import compute_metrics

LOT_SIZE = 100  # A 股一手 = 100 股


@dataclass
class Trade:
    """一笔已平仓交易。"""

    stock_code: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    shares: int
    pnl: float
    return_pct: float
    holding_days: int


@dataclass
class BacktestResult:
    """回测输出。"""

    equity_curve: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "dates": self.dates,
            "equity_curve": [round(x, 6) for x in self.equity_curve],
            "trades": [
                {
                    "stock_code": t.stock_code,
                    "entry_date": t.entry_date,
                    "entry_price": round(t.entry_price, 4),
                    "exit_date": t.exit_date,
                    "exit_price": round(t.exit_price, 4),
                    "shares": t.shares,
                    "pnl": round(t.pnl, 2),
                    "return_pct": round(t.return_pct, 6),
                    "holding_days": t.holding_days,
                }
                for t in self.trades
            ],
            "metrics": self.metrics,
        }


@dataclass
class Position:
    """持仓。shares 记录数量,用于 T+1 卖出限制。"""

    stock_code: str
    shares: int
    entry_date: str
    entry_price: float
    buy_cost: float
    bought_on: str  # 建仓交易日,用于 T+1 判断


class BacktestEngine:
    """日线回测引擎。

    signals: {stock_code: {date_str: "buy"|"sell"|None}}
    prices:  {stock_code: {date_str: close_price}}
    """

    def __init__(self, cost_model: CostModel | None = None) -> None:
        self.cost = cost_model or DEFAULT_COST_MODEL

    def run(
        self,
        signals: dict[str, dict[str, str]],
        prices: dict[str, dict[str, float]],
        trading_days: list[str],
        initial_capital: float = 1_000_000.0,
        max_positions: int = 10,
    ) -> BacktestResult:
        """执行回测。

        - 每个交易日先处理「卖出信号」(T+1),再处理「买入信号」
        - 资金不足或已达 max_positions 则跳过买入
        - 收盘按当日收盘价重估净值
        """
        cash = initial_capital
        positions: dict[str, Position] = {}
        equity: list[float] = []
        closed: list[Trade] = []

        all_codes = set(signals) | set(prices)

        for day in trading_days:
            # --- 1. 卖出(T+1:只能卖之前建的仓)---
            for code in list(positions):
                sig = signals.get(code, {}).get(day)
                if sig != "sell":
                    continue
                pos = positions[code]
                if pos.bought_on == day:  # T+1 限制
                    continue
                px = prices.get(code, {}).get(day)
                if px is None:
                    continue
                fill = self.cost.sell_fill_price(px)
                proceeds = fill * pos.shares - self.cost.sell_cost(pos.shares, px)
                cash += proceeds
                cost_basis = pos.entry_price * pos.shares + pos.buy_cost
                pnl = proceeds - cost_basis
                ret = pnl / cost_basis if cost_basis else 0.0
                closed.append(
                    Trade(
                        stock_code=code,
                        entry_date=pos.entry_date,
                        entry_price=pos.entry_price,
                        exit_date=day,
                        exit_price=fill,
                        shares=pos.shares,
                        pnl=pnl,
                        return_pct=ret,
                        holding_days=trading_days.index(day) - trading_days.index(pos.entry_date),
                    )
                )
                positions.pop(code, None)

            # --- 2. 买入 ---
            for code in sorted(all_codes):
                if len(positions) >= max_positions:
                    break
                if code in positions:
                    continue
                if signals.get(code, {}).get(day) != "buy":
                    continue
                px = prices.get(code, {}).get(day)
                if px is None or px <= 0:
                    continue
                fill = self.cost.buy_fill_price(px)
                # 按整手向下取整
                shares = int(cash / fill / LOT_SIZE) * LOT_SIZE
                if shares < LOT_SIZE:
                    continue
                amount = fill * shares
                fee = self.cost.buy_cost(shares, px)
                if amount + fee > cash:
                    shares = int((cash - fee) / fill / LOT_SIZE) * LOT_SIZE
                    if shares < LOT_SIZE:
                        continue
                    amount = fill * shares
                    fee = self.cost.buy_cost(shares, px)
                cash -= (amount + fee)
                positions[code] = Position(
                    stock_code=code,
                    shares=shares,
                    entry_date=day,
                    entry_price=fill,
                    buy_cost=fee,
                    bought_on=day,
                )

            # --- 3. 收盘重估净值 ---
            market_value = 0.0
            for code, pos in positions.items():
                px = prices.get(code, {}).get(day)
                # 停牌/缺价时沿用最后已知价
                last = px if px is not None else pos.entry_price
                market_value += last * pos.shares
            equity.append(cash + market_value)

        trade_returns = [t.return_pct for t in closed]
        metrics = compute_metrics(
            equity,
            initial_capital=initial_capital,
            trade_returns=trade_returns,
        ).to_dict()

        return BacktestResult(
            equity_curve=equity,
            dates=list(trading_days[: len(equity)]),
            trades=closed,
            metrics=metrics,
        )


__all__ = ["BacktestEngine", "BacktestResult", "Position", "Trade", "LOT_SIZE"]
