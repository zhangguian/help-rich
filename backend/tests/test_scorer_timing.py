"""「交易时机」评分维(第 6 维,满分 120)

覆盖:
- 6 维总分上限 120
- 子项 A 日内价格位置:低吸好 / 追高差 / 边界 / 缺 K 线降级
- 子项 B 时段适配:开盘半小时 / 早盘 / 尾盘 / 午休 / 时间未知
- 合成 = 子项 A + 子项 B
"""
from datetime import time

from app.core.scorer import (
    DIMENSIONS,
    SCORE_MAX,
    TIMING,
    _timing_position_score,
    _timing_score,
    _timing_session_score,
    score_trade,
)


def _trade(**over):
    t = {
        "stock_code": "600519.SH",
        "stock_name": "贵州茅台",
        "action": "buy",
        "shares": 100,
        "price": "1400.000",
        "trade_date": "2026-07-20",
    }
    t.update(over)
    return t


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


class TestScoreMax:
    def test_six_dimensions(self):
        assert len(DIMENSIONS) == 6
        assert TIMING in DIMENSIONS

    def test_score_max_is_120(self):
        assert SCORE_MAX == 120

    def test_score_clamped_to_120(self):
        # day_bar low=1400 high=1500,买在 1400 → pos=0(当日最低)→ 价格位置 10 分
        # 时段 10:30 → 10 分 → 交易时机 20
        r = score_trade(
            _trade(),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5,
            {"index_change_pct": 5.0, "sector_rank": 1},
            True,
            _POS_4,
            day_bar={"low": "1400", "high": "1500"},
            trade_time=time(10, 30),
        )
        assert r["score"] <= 120
        assert r["score"] == sum(r["score_breakdown"].values())
        assert r["score_breakdown"][TIMING] == 20

    def test_timing_degrades_to_neutral_without_data(self):
        """既没有时间也没有当日 K 线 → 子项各 5 分(中性,不编数字)"""
        r = score_trade(
            _trade(),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5,
            _MKT,
            True,
            _POS_4,
        )
        assert r["score_breakdown"][TIMING] == 10


class TestPricePosition:
    """子项 A:日内价格位置(0~10)"""

    def test_buy_low_in_day_is_best(self):
        # low=100, high=200, 买在 120 → pos=0.2 → 10 分
        assert _timing_position_score("buy", "120", {"low": "100", "high": "200"}) == 10

    def test_buy_high_in_day_is_worst(self):
        # 买在 190 → pos=0.9 → 2 分
        assert _timing_position_score("buy", "190", {"low": "100", "high": "200"}) == 2

    def test_buy_middle_is_neutral(self):
        assert _timing_position_score("buy", "150", {"low": "100", "high": "200"}) == 6

    def test_sell_high_in_day_is_best(self):
        assert _timing_position_score("sell", "190", {"low": "100", "high": "200"}) == 10

    def test_sell_low_in_day_is_worst(self):
        assert _timing_position_score("sell", "110", {"low": "100", "high": "200"}) == 2

    def test_boundary_030(self):
        """pos 恰好 0.30 → 10 分(买入)"""
        assert _timing_position_score("buy", "130", {"low": "100", "high": "200"}) == 10

    def test_boundary_070(self):
        """pos 恰好 0.70 → 6 分(买入,>0.70 才扣到 2)"""
        assert _timing_position_score("buy", "170", {"low": "100", "high": "200"}) == 6

    def test_price_above_high_is_clamped(self):
        """成交价高于当日最高(数据异常/盘后成交)→ 钳制到 1.0"""
        assert _timing_position_score("buy", "250", {"low": "100", "high": "200"}) == 2

    def test_missing_bar_degrades_to_neutral(self):
        assert _timing_position_score("buy", "120", None) == 5

    def test_flat_day_degrades_to_neutral(self):
        """一字板(high == low)→ 无法判定位置 → 中性"""
        assert _timing_position_score("buy", "120", {"low": "120", "high": "120"}) == 5

    def test_garbage_bar_degrades_to_neutral(self):
        assert _timing_position_score("buy", "120", {"low": None, "high": None}) == 5


class TestSession:
    """子项 B:时段适配(0~10)"""

    def test_buy_open_half_hour_is_penalised(self):
        assert _timing_session_score("buy", time(9, 30)) == 3
        assert _timing_session_score("buy", time(9, 59)) == 3

    def test_buy_morning_is_best(self):
        assert _timing_session_score("buy", time(10, 0)) == 10
        assert _timing_session_score("buy", time(11, 29)) == 10

    def test_buy_afternoon_is_best(self):
        assert _timing_session_score("buy", time(13, 0)) == 10
        assert _timing_session_score("buy", time(13, 59)) == 10

    def test_buy_late_afternoon(self):
        assert _timing_session_score("buy", time(14, 0)) == 7
        assert _timing_session_score("buy", time(14, 29)) == 7

    def test_buy_close_is_penalised(self):
        assert _timing_session_score("buy", time(14, 30)) == 3
        assert _timing_session_score("buy", time(15, 0)) == 3

    def test_sell_open_half_hour(self):
        assert _timing_session_score("sell", time(9, 30)) == 7

    def test_sell_close(self):
        assert _timing_session_score("sell", time(14, 30)) == 8

    def test_lunch_break_degrades_to_neutral(self):
        assert _timing_session_score("buy", time(12, 0)) == 5
        assert _timing_session_score("buy", time(11, 30)) == 5

    def test_unknown_time_degrades_to_neutral(self):
        assert _timing_session_score("buy", None) == 5

    def test_out_of_session_degrades_to_neutral(self):
        assert _timing_session_score("buy", time(8, 0)) == 5
        assert _timing_session_score("buy", time(16, 0)) == 5


class TestCombined:
    def test_timing_is_sum_of_two_sub_items(self):
        v = _timing_score(
            "buy",
            "120",
            time(10, 30),
            {"low": "100", "high": "200"},
        )
        assert v == 20  # 价格位置 10 + 时段 10

    def test_timing_partial(self):
        # 买在当日最高(pos=0.9 → 2)且尾盘(3)→ 5
        v = _timing_score("buy", "190", time(14, 45), {"low": "100", "high": "200"})
        assert v == 5

    def test_timing_from_trade_dict(self):
        """score_trade 也接受 trade 字典里的 trade_time"""
        r = score_trade(
            _trade(trade_time=time(10, 30)),
            {"shares": 100, "avg_cost": "1400.000"},
            _RECENT_5,
            _MKT,
            True,
            _POS_4,
            day_bar={"low": "1400", "high": "1500"},
        )
        assert r["score_breakdown"][TIMING] == 20
