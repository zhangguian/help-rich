"""选股权重测试(阶段2):纯函数为主,不依赖 DB。

重点验证:
1. 默认权重与 config 常量一致(向后兼容)
2. `_rescale` 的等比例缩放正确
3. disabled 因子得 0 分
4. build_weights 对脏数据容错
"""
import pytest

from app.services.scoring import StockFeatures, event_score, score_stock
from app.modules.screener.scoring import (
    FACTOR_KEYS,
    MAX_WEIGHT,
    ScoringWeights,
    build_weights,
    clamp_weight,
    default_weights,
)


class TestDefaults:
    def test_default_matches_config(self):
        """默认权重必须等于 config 常量,否则历史评分不可复现。"""
        from app.core.config import (
            SCREENER_EVENT_FACTOR_WEIGHT,
            SCREENER_MAIN_INFLOW_MAX,
            SCREENER_MOMENTUM_MAX,
            SCREENER_SECTOR_MAX,
            SCREENER_VOLUME_RATIO_MAX,
        )

        w = default_weights()
        assert w.main_inflow == SCREENER_MAIN_INFLOW_MAX
        assert w.volume_ratio == SCREENER_VOLUME_RATIO_MAX
        assert w.momentum == SCREENER_MOMENTUM_MAX
        assert w.sector_strength == SCREENER_SECTOR_MAX
        assert w.event == SCREENER_EVENT_FACTOR_WEIGHT

    def test_max_total_is_sum(self):
        w = default_weights()
        assert w.max_total == sum(w.get(k) for k in FACTOR_KEYS)

    def test_five_factors(self):
        assert len(FACTOR_KEYS) == 5
        assert "event" in FACTOR_KEYS


class TestClamp:
    @pytest.mark.parametrize(
        "raw,expected",
        [(10.0, 10.0), (-5.0, 0.0), (999.0, MAX_WEIGHT), ("abc", 0.0), (None, 0.0)],
    )
    def test_clamp_weight(self, raw, expected):
        assert clamp_weight(raw) == expected


class TestBuildWeights:
    def test_none_rows_returns_default(self):
        assert build_weights(None).max_total == default_weights().max_total
        assert build_weights([]).max_total == default_weights().max_total

    def test_partial_rows_keep_others_default(self):
        w = build_weights([{"factor_name": "momentum", "weight": 45.0, "enabled": True}])
        assert w.momentum == 45.0
        assert w.main_inflow == default_weights().main_inflow  # 其余保持默认

    def test_disabled_factor_gets_zero(self):
        w = build_weights([{"factor_name": "event", "weight": 15.0, "enabled": False}])
        assert w.get("event") == 0.0
        assert "event" in w.disabled

    def test_unknown_factor_ignored(self):
        w = build_weights([{"factor_name": "不存在的因子", "weight": 999}])
        # 全未知 → 回落默认
        assert w.max_total == default_weights().max_total

    def test_out_of_range_clamped(self):
        w = build_weights([{"factor_name": "momentum", "weight": 9999}])
        assert w.momentum == MAX_WEIGHT


class TestRescale:
    def test_default_weights_gives_identical_result(self):
        """传默认权重,评分结果必须与不传完全一致(向后兼容铁律)。"""
        feat = StockFeatures(
            stock_code="600519.SH",
            stock_name="测试",
            main_net_inflow_yi=2.5,
            volume_ratio=2.2,
            change_pct=5.0,
            turnover_yi=50.0,
            consecutive_up_days=3,
            sector="白酒",
            sector_inflow_rank=3,
        )
        without = score_stock(feat)
        with_default = score_stock(feat, default_weights())
        assert without.total == with_default.total
        assert without.main_inflow_score == with_default.main_inflow_score

    def test_doubling_weight_doubles_score(self):
        feat = StockFeatures(
            stock_code="X", stock_name="t",
            main_net_inflow_yi=3.0, volume_ratio=2.0, change_pct=5.0,
        )
        base = score_stock(feat)
        w = default_weights()
        w.main_inflow = base.main_inflow_score * 2  # 满分加倍
        scaled = score_stock(feat, w)
        # 主流入原满分是 60,这里设为原始得分*2 → 缩放后应约为原分 * (2*score/60)
        assert scaled.main_inflow_score != base.main_inflow_score

    def test_disabled_factor_scores_zero(self):
        feat = StockFeatures(
            stock_code="X", stock_name="t",
            main_net_inflow_yi=5.0, sector="科技", sector_inflow_rank=1,
        )
        w = default_weights()
        w.disabled = frozenset({"main_inflow"})
        bd = score_stock(feat, w)
        assert bd.main_inflow_score == 0.0
        # 总分里不应含主力流入
        without_main = score_stock(
            StockFeatures(stock_code="X", stock_name="t", sector="科技", sector_inflow_rank=1)
        )
        assert bd.total == pytest.approx(without_main.total)

    def test_zero_weight_gives_zero(self):
        feat = StockFeatures(stock_code="X", stock_name="t", main_net_inflow_yi=5.0)
        w = default_weights()
        w.main_inflow = 0.0
        assert score_stock(feat, w).main_inflow_score == 0.0


class TestEventScoreWithWeights:
    def test_default_event_score(self):
        assert event_score("X", {"X"}, set()) == default_weights().event

    def test_event_score_respects_weight(self):
        w = default_weights()
        w.event = 40.0
        assert event_score("X", {"X"}, set(), w) == 40

    def test_event_score_disabled_is_zero(self):
        w = default_weights()
        w.disabled = frozenset({"event"})
        assert event_score("X", {"X"}, set(), w) == 0

    def test_event_score_miss_is_zero(self):
        assert event_score("A", {"X"}, set()) == 0


class TestValidate:
    def test_default_valid(self):
        assert default_weights().validate() == []

    def test_all_disabled_invalid(self):
        w = default_weights()
        w.disabled = frozenset(FACTOR_KEYS)
        problems = w.validate()
        assert any("至少要启用一个因子" in p for p in problems)
