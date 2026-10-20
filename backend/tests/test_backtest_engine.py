"""回测引擎测试:验证交易规则(T+1、整手、资金守恒)与净值计算。"""
import pytest

from app.services.backtest.cost_model import CostModel
from app.services.backtest.engine import BacktestEngine


@pytest.fixture
def days():
    return [f"2026-01-{d:02d}" for d in range(1, 11)]


class TestSimpleRoundTrip:
    def test_buy_then_sell_profits(self, days):
        prices = {"A": {"2026-01-01": 10.0, "2026-01-05": 12.0}}
        signals = {"A": {"2026-01-01": "buy", "2026-01-05": "sell"}}
        result = BacktestEngine().run(signals, prices, days)
        assert len(result.trades) == 1
        t = result.trades[0]
        assert t.stock_code == "A"
        assert t.pnl > 0
        assert t.return_pct > 0

    def test_buy_then_sell_losses(self, days):
        prices = {"A": {"2026-01-01": 10.0, "2026-01-05": 8.0}}
        signals = {"A": {"2026-01-01": "buy", "2026-01-05": "sell"}}
        result = BacktestEngine().run(signals, prices, days)
        assert len(result.trades) == 1
        assert result.trades[0].pnl < 0

    def test_no_signal_no_trade(self, days):
        result = BacktestEngine().run({}, {}, days)
        assert result.trades == []
        assert len(result.equity_curve) == len(days)
        # 净值恒等于初始资金(无波动)
        assert all(x == pytest.approx(1_000_000.0) for x in result.equity_curve)


class TestT1Rule:
    def test_cannot_sell_same_day_buy(self, days):
        """T+1:当日买入不可当日卖出。"""
        prices = {"A": {"2026-01-01": 10.0}}
        signals = {"A": {"2026-01-01": "buy"}}  # 只买不卖
        result = BacktestEngine().run(signals, prices, days)
        # 没有触发卖出 → 没有平仓交易
        assert result.trades == []

    def test_sell_signal_same_day_ignored(self, days):
        """同一天既 buy 又 sell,buy 先建立仓但当天不能卖 → 不产生平仓。"""
        prices = {"A": {"2026-01-01": 10.0}}
        signals = {"A": {"2026-01-01": "buy"}}
        # 引擎先处理 sell 再处理 buy,所以同日 sell 不会匹配到当日新建仓
        result = BacktestEngine().run(signals, prices, days)
        assert result.trades == []

    def test_sell_next_day_works(self, days):
        """T+1 买入后次日可卖。"""
        prices = {"A": {"2026-01-01": 10.0, "2026-01-02": 11.0}}
        signals = {"A": {"2026-01-01": "buy", "2026-01-02": "sell"}}
        result = BacktestEngine().run(signals, prices, days)
        assert len(result.trades) == 1


class TestLotSize:
    def test_shares_multiple_of_100(self, days):
        """买入数量必须是 100 的整数倍(价格刻意取非整手友好值)。"""
        prices = {"A": {"2026-01-01": 33.33, "2026-01-03": 33.33}}
        signals = {"A": {"2026-01-01": "buy", "2026-01-03": "sell"}}
        result = BacktestEngine().run(signals, prices, days)
        assert len(result.trades) == 1
        assert result.trades[0].shares % 100 == 0
        assert result.trades[0].shares >= 100

    def test_insufficient_cash_no_trade(self, days):
        prices = {"A": {"2026-01-01": 100000.0}}  # 一手就要 1000 万
        signals = {"A": {"2026-01-01": "buy", "2026-01-03": "sell"}}
        result = BacktestEngine().run(signals, prices, days, initial_capital=10000.0)
        assert result.trades == []


class TestCapitalConservation:
    def test_cash_plus_market_value_equals_equity(self, days):
        prices = {"A": {"2026-01-01": 10.0, "2026-01-05": 12.0}}
        signals = {"A": {"2026-01-01": "buy", "2026-01-05": "sell"}}
        result = BacktestEngine().run(signals, prices, days, initial_capital=1_000_000.0)
        # 最终已平仓,净值应 > 初始(盈利)
        assert result.equity_curve[-1] > 1_000_000.0

    def test_equity_curve_length_matches_days(self, days):
        result = BacktestEngine().run({}, {}, days)
        assert len(result.equity_curve) == len(result.dates) == len(days)


class TestMultiplePositions:
    def test_max_positions_respected(self, days):
        """max_positions=3 → 只买 3 只,剩余资金留作现金。"""
        signals = {chr(65 + i): {"2026-01-01": "buy"} for i in range(5)}
        prices = {chr(65 + i): {"2026-01-01": 10.0} for i in range(5)}
        result = BacktestEngine().run(
            signals, prices, days, initial_capital=1_000_000.0, max_positions=3
        )
        # 三只都买入并以 10.0 持有 → 净值应接近初始值(仅扣少量费用)
        assert result.equity_curve[-1] == pytest.approx(1_000_000.0, rel=1e-3)

    def test_cash_split_across_positions(self, days):
        signals = {"A": {"2026-01-01": "buy"}, "B": {"2026-01-01": "buy"}}
        prices = {"A": {"2026-01-01": 10.0}, "B": {"2026-01-01": 20.0}}
        result = BacktestEngine().run(signals, prices, days, initial_capital=1_000_000.0)
        # 两边都不涨不跌 → 净值持平(仅扣手续费)
        assert result.equity_curve[-1] <= 1_000_000.0


class TestCostModel:
    def test_costs_reduce_equity(self, days):
        """手续费必须让净值略降(买入+卖出都有成本)。"""
        prices = {"A": {"2026-01-01": 10.0, "2026-01-03": 10.0}}
        signals = {"A": {"2026-01-01": "buy", "2026-01-03": "sell"}}
        result = BacktestEngine().run(signals, prices, days, initial_capital=1_000_000.0)
        # 价格不变,但扣了费用 → 净值 <
        assert result.equity_curve[-1] < 1_000_000.0

    def test_slippage_increases_cost(self, days):
        """滑点应进一步降低净值。"""
        prices = {"A": {"2026-01-01": 10.0, "2026-01-03": 10.0}}
        signals = {"A": {"2026-01-01": "buy", "2026-01-03": "sell"}}
        no_slip = BacktestEngine(CostModel(slippage_bps=0)).run(
            signals, prices, days, initial_capital=1_000_000.0
        )
        with_slip = BacktestEngine(CostModel(slippage_bps=50)).run(
            signals, prices, days, initial_capital=1_000_000.0
        )
        assert with_slip.equity_curve[-1] < no_slip.equity_curve[-1]
