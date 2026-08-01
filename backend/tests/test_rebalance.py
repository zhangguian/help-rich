"""A4 智能调仓建议测试(纯结构判断)"""
import pytest

from app.services.rebalance_service import PositionLite, calculate_rebalance


def _make(code, name, shares, cost):
    return PositionLite(
        stock_code=code,
        stock_name=name,
        shares=shares,
        avg_cost=cost,
        market_value=shares * float(cost),
    )


class TestEmptyOrInvalid:
    def test_no_positions(self):
        r = calculate_rebalance([])
        assert r["total_market_value"] == 0.0
        assert r["actions"] == []
        assert "无持仓" in r["summary"]


class TestReduceSuggestion:
    def test_high_ratio(self):
        """单股占比 70% → 高优先级减仓"""
        positions = [_make("600519.SH", "茅台", 700, "1500")]
        r = calculate_rebalance(positions)
        reduces = [a for a in r["actions"] if a["type"] == "reduce"]
        assert len(reduces) == 1
        assert reduces[0]["stock_code"] == "600519.SH"
        assert reduces[0]["priority"] == "high"
        assert "10-20%" in reduces[0]["reason"]

    def test_low_ratio_no_reduce(self):
        positions = [
            _make("600519.SH", "A", 100, "100"),
            _make("000001.SZ", "B", 100, "100"),
            _make("300750.SZ", "C", 100, "100"),
            _make("002185.SZ", "D", 100, "100"),
            _make("600036.SH", "E", 100, "100"),
        ]
        r = calculate_rebalance(positions)
        reduces = [a for a in r["actions"] if a["type"] == "reduce"]
        assert len(reduces) == 0


class TestTopConcentration:
    def test_top_above_50(self):
        """top1 占比 60% > 50% → 整仓偏重提示"""
        positions = [
            _make("600519.SH", "A", 600, "100"),
            _make("000001.SZ", "B", 200, "100"),
            _make("300750.SZ", "C", 200, "100"),
        ]
        r = calculate_rebalance(positions)
        alerts = [
            a for a in r["actions"]
            if a["type"] == "alert" and a["stock_code"] is not None
        ]
        assert len(alerts) == 1
        assert "整仓偏重" in alerts[0]["title"]


class TestDiversify:
    def test_too_few_positions(self):
        positions = [_make("600519.SH", "A", 100, "100")]
        r = calculate_rebalance(positions)
        adds = [a for a in r["actions"] if a["type"] == "add"]
        assert len(adds) == 1
        assert "加仓" in adds[0]["title"]
        assert adds[0]["priority"] == "medium"

    def test_same_sector_concentration(self):
        """3 只同板块(沪主板)→ 分散建议"""
        positions = [
            _make("600519.SH", "A", 100, "100"),
            _make("600036.SH", "B", 100, "100"),
            _make("601318.SH", "C", 100, "100"),
        ]
        r = calculate_rebalance(positions)
        diversifies = [a for a in r["actions"] if a["type"] == "diversify"]
        assert len(diversifies) >= 1
        assert "沪主板" in diversifies[0]["title"]


class TestWellDiversified:
    def test_no_actions_when_healthy(self):
        positions = [
            _make("600519.SH", "A", 100, "100"),
            _make("000001.SZ", "B", 100, "100"),
            _make("300750.SZ", "C", 100, "100"),
            _make("002185.SZ", "D", 100, "100"),
            _make("600036.SH", "E", 100, "100"),
        ]
        r = calculate_rebalance(positions)
        assert r["summary"].startswith("✅")


class TestSummary:
    def test_summary_counts_priorities(self):
        positions = [
            _make("600519.SH", "A", 800, "100"),  # 80% → high reduce
            _make("600036.SH", "B", 100, "100"),
            _make("601318.SH", "C", 100, "100"),
        ]
        r = calculate_rebalance(positions)
        # 1 reduce (high) + 1 top alert (medium, top > 50%) + 1 same_sector (medium, 3 SH 主板)
        assert "高优先级" in r["summary"] or "中优先级" in r["summary"]