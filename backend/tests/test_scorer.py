"""P4.1 scorer 单测(目标 100% 覆盖 core/scorer.py)

结构:
- 5 个维度每个:满分支测试
- 0 数据降级
- 边界(score clamp、日期兼容、无同向操作)
- ground truth 对照(10 样本,差 <= 10 分)
"""
import json
from datetime import date, datetime
from pathlib import Path
import pytest

from app.core.scorer import (
    CONCENTRATION,
    DEGRADED_CONCENTRATION,
    DEGRADED_INTERVAL,
    INTERVAL,
    MARKET_ENV,
    PRICE_REASON,
    SECTOR_HEAT,
    score_trade,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ground_truth.json"

# 公共上下文
_MKT = {"index_change_pct": 0.0, "sector_rank": 5}
_POS_4 = [
    {"stock_code": "600519.SH", "shares": 100, "avg_cost": "1400.000"},
    {"stock_code": "000001.SZ", "shares": 1000, "avg_cost": "10.500"},
    {"stock_code": "300750.SZ", "shares": 200, "avg_cost": "180.000"},
    {"stock_code": "002594.SZ", "shares": 300, "avg_cost": "120.000"},
]
_RECENT_5 = [
    {"action": "buy", "trade_date": "2026-07-10"},
    {"action": "sell", "trade_date": "2026-07-05"},
    {"action": "buy", "trade_date": "2026-06-25"},
    {"action": "buy", "trade_date": "2026-06-15"},
    {"action": "buy", "trade_date": "2026-06-01"},
]


def _trade(**kw):
    base = {
        "stock_code": "600519.SH",
        "stock_name": "贵州茅台",
        "action": "buy",
        "shares": 100,
        "price": "1400.000",
        "trade_date": "2026-07-20",
    }
    base.update(kw)
    return base


class TestConcentration:
    def test_below_30(self):
        r = score_trade(
            _trade(shares=50, price="1400.000"),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5, _MKT, True, _POS_4,
        )
        assert r["score_breakdown"][CONCENTRATION] == 20

    def test_30_to_50(self):
        r = score_trade(
            _trade(shares=100, price="1400.000"),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5, _MKT, True, _POS_4,
        )
        assert r["score_breakdown"][CONCENTRATION] == 15

    def test_above_50(self):
        r = score_trade(
            _trade(shares=5000, price="1400.000"),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5, _MKT, True, _POS_4,
        )
        assert r["score_breakdown"][CONCENTRATION] == 0

    def test_holdings_less_than_3_degraded(self):
        r = score_trade(
            _trade(),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5, _MKT, True,
            _POS_4[:2],
        )
        assert r["score_breakdown"][CONCENTRATION] == DEGRADED_CONCENTRATION

    def test_total_value_zero_degraded(self):
        r = score_trade(
            _trade(shares=0, price="0"),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5, _MKT, True,
            [{"stock_code": "600519.SH", "shares": 0, "avg_cost": "0"},
             {"stock_code": "000001.SZ", "shares": 0, "avg_cost": "0"},
             {"stock_code": "300750.SZ", "shares": 0, "avg_cost": "0"}],
        )
        assert r["score_breakdown"][CONCENTRATION] == DEGRADED_CONCENTRATION


class TestPriceReason:
    def test_new_position_default(self):
        r = score_trade(_trade(), None, _RECENT_5, _MKT, True, _POS_4)
        assert r["score_breakdown"][PRICE_REASON] == 15

    def test_sell_default(self):
        r = score_trade(
            _trade(action="sell"),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5, _MKT, True, _POS_4,
        )
        assert r["score_breakdown"][PRICE_REASON] == 15

    def test_within_5_percent(self):
        r = score_trade(
            _trade(price="1430.000"),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5, _MKT, True, _POS_4,
        )
        assert r["score_breakdown"][PRICE_REASON] == 20

    def test_5_to_10_percent(self):
        r = score_trade(
            _trade(price="1490.000"),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5, _MKT, True, _POS_4,
        )
        assert r["score_breakdown"][PRICE_REASON] == 10

    def test_above_10_percent(self):
        r = score_trade(
            _trade(price="1600.000"),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5, _MKT, True, _POS_4,
        )
        assert r["score_breakdown"][PRICE_REASON] == 5

    def test_position_no_avg_cost_default(self):
        r = score_trade(
            _trade(),
            {"shares": 100, "avg_cost": None},
            _RECENT_5, _MKT, True, _POS_4,
        )
        assert r["score_breakdown"][PRICE_REASON] == 15


class TestInterval:
    def test_above_7_days(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5, _MKT, True, _POS_4)
        assert r["score_breakdown"][INTERVAL] == 20

    def test_3_to_7_days(self):
        recent = [dict(t, trade_date="2026-07-16") for t in _RECENT_5]
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, recent, _MKT, True, _POS_4)
        assert r["score_breakdown"][INTERVAL] == 15

    def test_below_3_days(self):
        recent = [dict(t, trade_date="2026-07-19") for t in _RECENT_5]
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, recent, _MKT, True, _POS_4)
        assert r["score_breakdown"][INTERVAL] == 10

    def test_no_same_direction_full(self):
        recent = [{"action": "sell", "trade_date": "2026-07-10"}]
        recent += _RECENT_5
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, recent, _MKT, True, _POS_4)
        assert r["score_breakdown"][INTERVAL] == 20

    def test_only_opposite_direction_full(self):
        recent = [{"action": "sell", "trade_date": d} for d in
                  ["2026-07-10", "2026-07-05", "2026-06-25", "2026-06-15", "2026-06-01"]]
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, recent, _MKT, True, _POS_4)
        assert r["score_breakdown"][INTERVAL] == 20

    def test_history_less_than_2_degraded(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5[:1], _MKT, True, _POS_4)
        assert r["score_breakdown"][INTERVAL] == DEGRADED_INTERVAL


class TestMarketEnv:
    def test_buy_up_trend(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"index_change_pct": 0.8}, True, _POS_4)
        assert r["score_breakdown"][MARKET_ENV] == 20

    def test_sell_down_trend(self):
        r = score_trade(_trade(action="sell"), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"index_change_pct": -0.8}, True, _POS_4)
        assert r["score_breakdown"][MARKET_ENV] == 20

    def test_neutral(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"index_change_pct": 0.2}, True, _POS_4)
        assert r["score_breakdown"][MARKET_ENV] == 10

    def test_against_trend(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"index_change_pct": -0.8}, True, _POS_4)
        assert r["score_breakdown"][MARKET_ENV] == 0

    def test_default_pct_neutral(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {}, True, _POS_4)
        assert r["score_breakdown"][MARKET_ENV] == 10


class TestSectorHeat:
    def test_rank_1_to_5(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"sector_rank": 3}, True, _POS_4)
        assert r["score_breakdown"][SECTOR_HEAT] == 20

    def test_rank_6_to_10(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"sector_rank": 8}, True, _POS_4)
        assert r["score_breakdown"][SECTOR_HEAT] == 10

    def test_rank_above_10(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"sector_rank": 15}, True, _POS_4)
        assert r["score_breakdown"][SECTOR_HEAT] == 0

    def test_top5_list_fallback(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"top5_sector_stocks": ["600519.SH", "000001.SZ"]}, True, _POS_4)
        assert r["score_breakdown"][SECTOR_HEAT] == 20

    def test_top5_list_miss(self):
        r = score_trade(_trade(stock_code="601318.SH"), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"top5_sector_stocks": ["600519.SH", "000001.SZ"]}, True, _POS_4)
        assert r["score_breakdown"][SECTOR_HEAT] == 0

    def test_no_context_zero(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {}, True, _POS_4)
        assert r["score_breakdown"][SECTOR_HEAT] == 0


class TestScoreAggregation:
    def test_negative_clamped(self):
        r = score_trade(
            _trade(shares=999999, price="999.000"),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5,
            {"index_change_pct": -5.0, "sector_rank": 99},
            True, _POS_4,
        )
        assert r["score"] >= 0

    def test_max_clamped_to_100(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5,
                        {"index_change_pct": 0.0, "sector_rank": 1}, True, _POS_4)
        assert r["score"] <= 100
        assert r["score"] == sum(r["score_breakdown"].values())

    def test_breakdown_has_all_5_dimensions(self):
        r = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5, _MKT, True, _POS_4)
        assert set(r["score_breakdown"].keys()) == {
            CONCENTRATION, PRICE_REASON, INTERVAL, MARKET_ENV, SECTOR_HEAT,
        }

    def test_is_in_watchlist_does_not_affect_score(self):
        r1 = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5, _MKT, True, _POS_4)
        r2 = score_trade(_trade(), {"shares": 100, "avg_cost": "1400.000"}, _RECENT_5, _MKT, False, _POS_4)
        assert r1["score"] == r2["score"]

    def test_date_as_datetime(self):
        recent = [dict(t, trade_date=datetime(2026, 7, 10)) for t in _RECENT_5]
        r = score_trade(
            _trade(trade_date=datetime(2026, 7, 20)),
            {"shares": 100, "avg_cost": "1400.000"}, recent, _MKT, True, _POS_4,
        )
        assert r["score_breakdown"][INTERVAL] == 20

    def test_invalid_trade_date_degraded(self):
        r = score_trade(_trade(trade_date="not-a-date"), {"shares": 100, "avg_cost": "1400.000"},
                        _RECENT_5, _MKT, True, _POS_4)
        assert r["score_breakdown"][INTERVAL] == DEGRADED_INTERVAL

    def test_non_date_type_degraded(self):
        r = score_trade(_trade(trade_date=12345), {"shares": 100, "avg_cost": "1400.000"},
                        _RECENT_5, _MKT, True, _POS_4)
        assert r["score_breakdown"][INTERVAL] == DEGRADED_INTERVAL


class TestGroundTruth:
    """验收:10 样本与人工打分差 <= 10 分(P4.1)"""

    def test_all_samples(self):
        data = json.loads(FIXTURES.read_text(encoding="utf-8"))
        samples = data["samples"]
        assert len(samples) == 10
        for s in samples:
            r = score_trade(
                s["trade"],
                s["position_before"],
                s["recent_trades"],
                s["market_ctx"],
                s["is_in_watchlist"],
                s["all_positions"],
            )
            exp = s["expected"]
            assert abs(r["score"] - exp["score"]) <= 10, (
                f"{s['name']}: got {r['score']}, expected {exp['score']} "
                f"(breakdown {r['score_breakdown']} vs {exp['breakdown']})"
            )
            for dim, val in exp["breakdown"].items():
                assert r["score_breakdown"][dim] == val, (
                    f"{s['name']} {dim}: got {r['score_breakdown'][dim]}, expected {val}"
                )

    def test_breakdown_sum_matches_score(self):
        data = json.loads(FIXTURES.read_text(encoding="utf-8"))
        for s in data["samples"]:
            assert sum(s["expected"]["breakdown"].values()) == s["expected"]["score"]
