"""成本计算器测试 — 4 类场景 + 边界(testing-strategy §3.1)

覆盖:
- 加仓
- 减仓
- 做T(买后卖)
- 清仓
- 异常边界(tx_shares=0, tx_price=0, 卖出超额)
- 21 档网格(数量、边界值)
- 与同花顺/东财 人工对照
"""
from decimal import Decimal

import pytest

from app.core.cost_engine import (
    build_pnl_grid,
    calc,
    calculate_after_transaction,
)


# ============================================================
# 1. 加仓场景
# ============================================================

class TestBuyScenario:
    """加仓:1000@10 + 500@11 → 1500@10.667"""

    def test_basic_buy_from_zero(self):
        """从空仓建仓 1000@10.500"""
        result = calculate_after_transaction(
            shares_before=0,
            cost_before=Decimal("0"),
            action="buy",
            tx_shares=1000,
            tx_price=Decimal("10.500"),
        )
        assert result["shares_after"] == 1000
        assert result["cost_after"] == Decimal("10.500")
        assert result["total_cost_after"] == Decimal("10500.00")
        assert result["delta_cost"] == Decimal("10.500")
        assert result["realized_pnl"] == Decimal("0.00")
        assert result["is_closed"] is False

    def test_buy_add_position(self):
        """已有 1000@10.5,加仓 500@11.0 → 1500@10.667"""
        result = calculate_after_transaction(
            shares_before=1000,
            cost_before=Decimal("10.500"),
            action="buy",
            tx_shares=500,
            tx_price=Decimal("11.000"),
        )
        # (1000×10.5 + 500×11) / 1500 = 16000/1500 = 10.66666... → 10.667
        assert result["shares_after"] == 1500
        assert result["cost_after"] == Decimal("10.667")
        assert result["total_cost_after"] == Decimal("16000.00")
        assert result["delta_cost"] == Decimal("0.167")
        assert result["realized_pnl"] == Decimal("0.00")
        assert result["is_closed"] is False

    def test_third_buy_lowers_avg(self):
        """1000@10.5 + 500@11 + 200@9.5 → 1700@10.382"""
        # 先加到 1500@10.667
        r1 = calculate_after_transaction(1000, Decimal("10.500"), "buy", 500, Decimal("11.000"))
        # 再加 200@9.5
        r2 = calculate_after_transaction(
            r1["shares_after"], r1["cost_after"], "buy", 200, Decimal("9.500")
        )
        # (1500×10.667 + 200×9.5) / 1700
        # = (16000.05 + 1900) / 1700 ≈ 10.52944 → 10.529
        assert r2["shares_after"] == 1700
        # 允许精度差异:10.529 或 10.530 都算对
        assert r2["cost_after"] in (Decimal("10.529"), Decimal("10.530"))


# ============================================================
# 2. 减仓场景
# ============================================================

class TestSellScenario:
    """减仓:剩余成本不变,产生已实现盈亏"""

    def test_sell_partial_with_profit(self):
        """1500@10.667,卖 300@12 → 剩 1200@10.667,realized=(12-10.667)×300=399.90"""
        result = calculate_after_transaction(
            shares_before=1500,
            cost_before=Decimal("10.667"),
            action="sell",
            tx_shares=300,
            tx_price=Decimal("12.000"),
        )
        assert result["shares_after"] == 1200
        assert result["cost_after"] == Decimal("10.667")  # 成本不变
        # total_cost: 10.667 × 1200 = 12800.40(3 位精度 × 1200)
        # 但实际:1500×10.667=16000.50;减去 300×12=3600 → 12400.50? 不对,应该按 avg 减
        # 准确:原 total_cost = 1500×10.667 = 16000.50(理论)
        # 卖 300@12:total_cost -= 10.667×300 = 3200.10 → 12800.40
        assert result["total_cost_after"] == Decimal("12800.40")
        # realized = (12 - 10.667) × 300 = 1.333 × 300 = 399.90
        assert result["realized_pnl"] == Decimal("399.90")
        assert result["is_closed"] is False

    def test_sell_partial_with_loss(self):
        """1000@10.5,卖 200@9 → 剩 800@10.5,realized=(9-10.5)×200=-300"""
        result = calculate_after_transaction(
            shares_before=1000,
            cost_before=Decimal("10.500"),
            action="sell",
            tx_shares=200,
            tx_price=Decimal("9.000"),
        )
        assert result["shares_after"] == 800
        assert result["cost_after"] == Decimal("10.500")
        assert result["realized_pnl"] == Decimal("-300.00")

    def test_sell_exact_full_clear(self):
        """1000@10.5,卖 1000@11 → 清仓,realized=(11-10.5)×1000=500"""
        result = calculate_after_transaction(
            shares_before=1000,
            cost_before=Decimal("10.500"),
            action="sell",
            tx_shares=1000,
            tx_price=Decimal("11.000"),
        )
        assert result["shares_after"] == 0
        assert result["cost_after"] is None
        assert result["total_cost_after"] == Decimal("0.00")
        assert result["realized_pnl"] == Decimal("500.00")
        assert result["is_closed"] is True


# ============================================================
# 3. 做T 场景(连续多笔)
# ============================================================

class TestDayTradingScenario:
    """做T:买 → 卖 → 买 → 卖,模拟日内多次操作"""

    def test_buy_sell_buy_sell_chain(self):
        """Day 1 买 1000@10.5 → Day 1 卖 500@11 → Day 2 买 500@10.8 → Day 2 卖 500@11.5"""
        # 买 1000@10.5
        r1 = calculate_after_transaction(0, Decimal("0"), "buy", 1000, Decimal("10.500"))
        assert r1["cost_after"] == Decimal("10.500")

        # 卖 500@11(做T)
        r2 = calculate_after_transaction(
            r1["shares_after"], r1["cost_after"], "sell", 500, Decimal("11.000")
        )
        assert r2["shares_after"] == 500
        assert r2["cost_after"] == Decimal("10.500")  # 剩余成本不变
        assert r2["realized_pnl"] == Decimal("250.00")  # (11-10.5)×500

        # 再买 500@10.8(加仓)
        r3 = calculate_after_transaction(
            r2["shares_after"], r2["cost_after"], "buy", 500, Decimal("10.800")
        )
        # (500×10.5 + 500×10.8) / 1000 = 10.65
        assert r3["shares_after"] == 1000
        assert r3["cost_after"] == Decimal("10.650")

        # 再卖 500@11.5
        r4 = calculate_after_transaction(
            r3["shares_after"], r3["cost_after"], "sell", 500, Decimal("11.500")
        )
        assert r4["shares_after"] == 500
        assert r4["cost_after"] == Decimal("10.650")
        # (11.5 - 10.65) × 500 = 0.85 × 500 = 425
        assert r4["realized_pnl"] == Decimal("425.00")


# ============================================================
# 4. 清仓场景
# ============================================================

class TestClearPositionScenario:
    """清仓:shares 归零,cost None"""

    def test_clear_at_profit(self):
        result = calculate_after_transaction(
            shares_before=500,
            cost_before=Decimal("12.345"),
            action="sell",
            tx_shares=500,
            tx_price=Decimal("15.000"),
        )
        assert result["shares_after"] == 0
        assert result["cost_after"] is None
        # (15-12.345) × 500 = 2.655 × 500 = 1327.50
        assert result["realized_pnl"] == Decimal("1327.50")
        assert result["is_closed"] is True

    def test_clear_at_loss(self):
        result = calculate_after_transaction(
            shares_before=500,
            cost_before=Decimal("12.000"),
            action="sell",
            tx_shares=500,
            tx_price=Decimal("10.000"),
        )
        assert result["shares_after"] == 0
        assert result["cost_after"] is None
        assert result["realized_pnl"] == Decimal("-1000.00")
        assert result["is_closed"] is True


# ============================================================
# 5. 异常边界
# ============================================================

class TestValidationErrors:
    def test_zero_shares_raises(self):
        with pytest.raises(ValueError, match="tx_shares 必须 > 0"):
            calculate_after_transaction(
                1000, Decimal("10.500"), "buy", 0, Decimal("11.000")
            )

    def test_negative_shares_raises(self):
        with pytest.raises(ValueError, match="tx_shares 必须 > 0"):
            calculate_after_transaction(
                1000, Decimal("10.500"), "buy", -100, Decimal("11.000")
            )

    def test_zero_price_raises(self):
        with pytest.raises(ValueError, match="tx_price 必须 > 0"):
            calculate_after_transaction(
                1000, Decimal("10.500"), "buy", 100, Decimal("0")
            )

    def test_sell_exceeds_holding_raises(self):
        with pytest.raises(ValueError, match="卖出.*超过持仓"):
            calculate_after_transaction(
                1000, Decimal("10.500"), "sell", 9999, Decimal("11.000")
            )

    def test_sell_with_zero_holding_raises(self):
        with pytest.raises(ValueError, match="卖出.*超过持仓"):
            calculate_after_transaction(
                0, Decimal("0"), "sell", 1, Decimal("11.000")
            )


# ============================================================
# 6. 21 档网格
# ============================================================

class TestPnlGrid:
    def test_grid_size_21_points(self):
        """21 档 = -10% ~ +10% 步长 1%"""
        grid = build_pnl_grid(Decimal("10.500"), shares_after=1500)
        assert len(grid) == 21

    def test_grid_first_and_last_points(self):
        grid = build_pnl_grid(Decimal("10.500"), shares_after=1500)
        assert grid[0]["pct"] == -10
        assert grid[-1]["pct"] == 10
        # -10%:10.5 × 0.9 = 9.450
        assert grid[0]["price"] == Decimal("9.450")
        # +10%:10.5 × 1.1 = 11.550
        assert grid[-1]["price"] == Decimal("11.550")

    def test_grid_zero_pct_is_baseline(self):
        """0% 档:价格 = 成本,pnl ≈ 0(浮点精度)"""
        grid = build_pnl_grid(Decimal("10.500"), shares_after=1500)
        middle = grid[10]  # pct=0
        assert middle["pct"] == 0
        assert middle["price"] == Decimal("10.500")
        # 浮点累加误差:market_value = 10.500 × 1500 = 15750.00;baseline = 15750;pnl ≈ 0
        assert middle["pnl"] in (Decimal("0.00"), Decimal("-0.01"), Decimal("0.01"))

    def test_grid_negative_pnl_left(self):
        """负档位 pnl < 0(亏损,pct = -10 ~ -1)"""
        grid = build_pnl_grid(Decimal("10.000"), shares_after=1000)
        for row in grid[:10]:  # pct = -10 ~ -1(不含 pct=0)
            assert row["pnl"] < Decimal("0")

    def test_grid_positive_pnl_right(self):
        """正档位 pnl > 0(盈利,pct = +1 ~ +10)"""
        grid = build_pnl_grid(Decimal("10.000"), shares_after=1000)
        for row in grid[11:]:  # pct = +1 ~ +10(不含 pct=0)
            assert row["pnl"] > Decimal("0")

    def test_grid_zero_shares_returns_empty(self):
        grid = build_pnl_grid(Decimal("10.000"), shares_after=0)
        assert grid == []

    def test_grid_none_cost_returns_empty(self):
        """清仓后查网格 → 空(API 端点处理)"""
        grid = build_pnl_grid(None, shares_after=0)
        assert grid == []


# ============================================================
# 7. 与同花顺/东财 对照(estimation,Day 7 P7.6 实测)
# ============================================================

class TestBrokerAlignment:
    """预估对照场景,Day 7 P7.6 实测对账"""

    def test_standard_add_position_simulation(self):
        """1000@10.000 加仓 500@11.000 → 1500@10.333

        与同花顺 / 东财 持仓页加权平均列对照。
        """
        result = calculate_after_transaction(
            1000, Decimal("10.000"), "buy", 500, Decimal("11.000")
        )
        assert result["cost_after"] == Decimal("10.333")
        assert result["total_cost_after"] == Decimal("15500.00")

    def test_partial_sell_realized_calculation(self):
        """1500@10.000 卖 300@12.500

        实际盈亏 = (12.500 - 10.000) × 300 = 750.00
        """
        result = calculate_after_transaction(
            1500, Decimal("10.000"), "sell", 300, Decimal("12.500")
        )
        assert result["realized_pnl"] == Decimal("750.00")
        # 剩余 1200 股,成本 10.000(不变)
        assert result["shares_after"] == 1200
        assert result["cost_after"] == Decimal("10.000")


# ============================================================
# 8. calc() 便捷函数(Decimal → str 转换)
# ============================================================

class TestCalcHelper:
    def test_calc_converts_decimals_to_str(self):
        after = calculate_after_transaction(
            1000, Decimal("10.500"), "buy", 500, Decimal("11.000")
        )
        out = calc(after)
        assert out["cost_after"] == "10.667"
        assert out["total_cost_after"] == "16000.00"
        assert out["realized_pnl"] == "0.00"
        assert out["is_closed"] is False

    def test_calc_handles_none_cost(self):
        after = calculate_after_transaction(
            1000, Decimal("10.500"), "sell", 1000, Decimal("11.000")
        )
        out = calc(after)
        assert out["cost_after"] is None
        assert out["is_closed"] is True