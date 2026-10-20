"""回测绩效指标测试(纯函数)。"""
import pytest

from app.services.backtest.metrics import (
    annual_return,
    annual_volatility,
    compute_metrics,
    max_drawdown,
    sharpe_ratio,
    total_return,
    trade_statistics,
)


class TestTotalReturn:
    def test_basic(self):
        assert total_return([1.0, 1.5], initial_capital=1.0) == pytest.approx(0.5)

    def test_with_initial_capital(self):
        assert total_return([100.0, 150.0], initial_capital=100.0) == pytest.approx(0.5)

    def test_loss(self):
        assert total_return([1.0, 0.8]) == pytest.approx(-0.2)

    def test_empty_returns_zero(self):
        assert total_return([]) == 0.0


class TestMaxDrawdown:
    def test_no_drawdown_monotonic_up(self):
        dd, _, _ = max_drawdown([1.0, 1.1, 1.2, 1.3])
        assert dd == 0.0

    def test_simple_drawdown(self):
        dd, peak, trough = max_drawdown([1.0, 1.5, 1.2, 1.6])
        assert dd == pytest.approx(1.2 / 1.5 - 1.0)  # -20%
        assert peak == 1
        assert trough == 2

    def test_insufficient_data(self):
        assert max_drawdown([1.0]) == (None, None, None)
        assert max_drawdown([]) == (None, None, None)

    def test_full_loss(self):
        dd, _, _ = max_drawdown([1.0, 0.5, 0.0])
        assert dd == pytest.approx(-1.0)


class TestAnnualReturn:
    def test_single_day_is_compounded_to_year(self):
        """1 天 +10% 按 252 天复利年化 —— 数值夸张但数学正确。

        这是年化的固有性质(样本越短外推越极端),调用方应在展示层
        对「样本不足 20 个交易日」加提示,而不是让函数返回 None 假装有信息。
        """
        ann = annual_return([1.0, 1.1], initial_capital=1.0)
        assert ann == pytest.approx(1.1 ** 252 - 1.0)

    def test_empty_curve_none(self):
        assert annual_return([]) is None

    def test_flat_curve_zero(self):
        assert annual_return([1.0, 1.0, 1.0]) == pytest.approx(0.0)

    def test_one_year_doubles(self):
        # 252 个交易日翻倍 → 年化约 100%
        curve = [1.0 * (2 ** (i / 252)) for i in range(253)]
        ann = annual_return(curve, initial_capital=1.0)
        assert ann == pytest.approx(1.0, abs=0.01)


class TestVolatility:
    def test_flat_curve_zero(self):
        assert annual_volatility([1.0, 1.0, 1.0]) == 0.0

    def test_insufficient_returns_none(self):
        assert annual_volatility([1.0]) is None


class TestSharpe:
    def test_zero_volatility_returns_none(self):
        assert sharpe_ratio([1.0, 1.0, 1.0]) is None

    def test_flat_loss_zero_volatility_none(self):
        assert sharpe_ratio([1.0, 1.0]) is None

    def test_positive_sharpe_for_uptrend(self):
        curve = [1.0 * (1 + 0.001 * i + 0.0005 * ((i % 3) - 1)) for i in range(200)]
        s = sharpe_ratio(curve)
        assert s is not None


class TestTradeStats:
    def test_win_loss_stats(self):
        stats = trade_statistics([0.10, -0.05, 0.20, -0.10])
        assert stats["total_trades"] == 4
        assert stats["winning_trades"] == 2
        assert stats["losing_trades"] == 2
        assert stats["win_rate"] == pytest.approx(0.5)
        # avg_win = 0.15, avg_loss = 0.075 → 2.0
        assert stats["profit_factor"] == pytest.approx(2.0)

    def test_all_wins(self):
        stats = trade_statistics([0.1, 0.2])
        assert stats["win_rate"] == pytest.approx(1.0)
        assert stats["profit_factor"] is None  # 无亏损,比值无定义

    def test_all_losses(self):
        stats = trade_statistics([-0.1, -0.2])
        assert stats["win_rate"] == 0.0
        assert stats["profit_factor"] is None

    def test_empty(self):
        stats = trade_statistics([])
        assert stats["total_trades"] == 0
        assert stats["win_rate"] is None

    def test_zero_return_neither_win_nor_loss(self):
        stats = trade_statistics([0.0, 0.1])
        assert stats["winning_trades"] == 1
        assert stats["losing_trades"] == 0


class TestComputeMetrics:
    def test_full_bundle(self):
        curve = [1.0, 1.05, 1.02, 1.1, 1.15]
        m = compute_metrics(curve, initial_capital=1.0, trade_returns=[0.05, -0.03, 0.08])
        d = m.to_dict()
        assert d["total_trades"] == 3
        assert d["total_return"] == pytest.approx(0.15)
        # to_dict 是展示层,保留 6 位小数,断言要给舍入余量
        assert d["max_drawdown"] == pytest.approx(1.02 / 1.05 - 1.0, abs=1e-6)
        # 内部字段保留完整精度
        assert m.total_return == pytest.approx(0.15)
        assert m.max_drawdown == pytest.approx(1.02 / 1.05 - 1.0)

    def test_to_dict_rounds_for_display(self):
        m = compute_metrics([1.0, 1.0 / 3])
        d = m.to_dict()
        assert d["total_return"] == pytest.approx(-0.666667, abs=1e-6)

    def test_to_dict_serializable(self):
        m = compute_metrics([1.0, 1.1])
        d = m.to_dict()
        for k, v in d.items():
            assert isinstance(v, (int, float, type(None))), f"{k}={v} 不可序列化"
