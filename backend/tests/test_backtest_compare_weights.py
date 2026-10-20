"""权重对比回测测试(阶段2 校准能力)。

核心回归:**不同权重必须真的选出不同的股票**。

历史 Bug:早期 `compare_weights` 对每套权重复用同一批历史 picks,
循环里从头到尾没用到 `wdict`,导致各套权重回测结果完全相同 ——
"对比"输出一堆相同数字,用户会误以为权重对结果毫无影响。
"""
from datetime import date, timedelta

import pytest

from app.services.backtest import service as bt


class FakePick:
    """模拟 ScreenerPick:带齐 score_stock 需要的因子字段。"""

    def __init__(self, code, inflow, vol_ratio, change, up_days, rank):
        self.stock_code = code
        self.stock_name = code
        self.main_net_inflow_yi = inflow
        self.volume_ratio = vol_ratio
        self.change_pct = change
        self.consecutive_up_days = up_days
        self.sector = None
        self.sector_inflow_rank = rank


def _patch_loaders(monkeypatch, picks_by_date, prices, trading_days):
    async def fake_dates(days):
        return list(picks_by_date)

    async def fake_features(dates):
        return picks_by_date

    async def fake_prices(codes, dates, hold):
        return prices, trading_days

    monkeypatch.setattr(bt, "_load_pick_dates", fake_dates)
    monkeypatch.setattr(bt, "_load_pick_features", fake_features)
    monkeypatch.setattr(bt, "_load_prices", fake_prices)


def _setup_two_picks():
    d0 = date(2026, 10, 1)
    trading_days = [(d0 + timedelta(days=i)).isoformat() for i in range(20)]
    # A 资金极强、量比弱;B 量比极强、资金弱
    picks = [
        FakePick("AAA", inflow=5.0, vol_ratio=0.5, change=0.0, up_days=0, rank=None),
        FakePick("BBB", inflow=0.0, vol_ratio=5.0, change=9.9, up_days=5, rank=1),
    ]
    # 两只票走势必须不同,否则"换了一只票但收益一样",无法证明重排生效
    prices = {
        "AAA": {d: 10.0 + i * 0.10 for i, d in enumerate(trading_days)},
        "BBB": {d: 10.0 - i * 0.05 for i, d in enumerate(trading_days)},
    }
    return {d0: picks}, prices, trading_days


class TestCompareWeights:
    @pytest.mark.asyncio
    async def test_different_weights_select_different_stocks(self, monkeypatch):
        picks_by_date, prices, trading_days = _setup_two_picks()
        _patch_loaders(monkeypatch, picks_by_date, prices, trading_days)

        out = await bt.compare_weights(
            weight_sets={
                "只看资金": {
                    "main_inflow": 200,
                    "volume_ratio": 0,
                    "momentum": 0,
                    "sector_strength": 0,
                    "event": 0,
                },
                "只看量能": {
                    "main_inflow": 0,
                    "volume_ratio": 200,
                    "momentum": 200,
                    "sector_strength": 200,
                    "event": 0,
                },
            },
            days=30,
            hold_days=5,
            max_positions=1,  # 每天只买 1 只 → 权重差异必须体现为不同标的
        )

        assert out["ok"] is True
        assert out["has_lookahead_bias"] is True

        traded_a = out["results"]["只看资金"]["selected_codes"]
        traded_b = out["results"]["只看量能"]["selected_codes"]
        # 每套权重各选 1 只票;两套应当选出**不同**的票
        assert len(traded_a) == 1
        assert len(traded_b) == 1
        assert traded_a != traded_b, (
            f"不同权重选出了相同标的({traded_a}),说明重排逻辑没生效(历史 Bug 复现)"
        )
        assert out["weights_sensitive"] is True

    @pytest.mark.asyncio
    async def test_identical_weights_reports_insensitive(self, monkeypatch):
        """各套权重完全相同时,应明确告知"不敏感",而不是让用户自己看一堆相同数字。"""
        picks_by_date, prices, trading_days = _setup_two_picks()
        _patch_loaders(monkeypatch, picks_by_date, prices, trading_days)

        same = {"main_inflow": 60, "volume_ratio": 40, "momentum": 30, "sector_strength": 25}
        out = await bt.compare_weights(
            weight_sets={"A": same, "B": same},
            days=30,
            hold_days=5,
            max_positions=5,
        )
        assert out["ok"] is True
        assert out["weights_sensitive"] is False
        assert "不敏感" in out["note"]

    @pytest.mark.asyncio
    async def test_no_history_returns_not_ok(self, monkeypatch):
        async def empty(_days):
            return []

        monkeypatch.setattr(bt, "_load_pick_dates", empty)
        out = await bt.compare_weights({"A": {}}, days=30)
        assert out["ok"] is False
        assert "没有可用历史记录" in out["reason"]

    @pytest.mark.asyncio
    async def test_missing_prices_returns_not_ok(self, monkeypatch):
        d0 = date(2026, 10, 1)
        picks = [FakePick("AAA", 1.0, 1.0, 1.0, 0, None)]

        async def fake_dates(_days):
            return [d0]

        async def fake_features(_dates):
            return {d0: picks}

        async def no_prices(*_a, **_k):
            return {}, []

        monkeypatch.setattr(bt, "_load_pick_dates", fake_dates)
        monkeypatch.setattr(bt, "_load_pick_features", fake_features)
        monkeypatch.setattr(bt, "_load_prices", no_prices)

        out = await bt.compare_weights({"A": {}}, days=30)
        assert out["ok"] is False
        assert "K 线" in out["reason"]

    @pytest.mark.asyncio
    async def test_returns_weights_and_max_total_per_set(self, monkeypatch):
        picks_by_date, prices, trading_days = _setup_two_picks()
        _patch_loaders(monkeypatch, picks_by_date, prices, trading_days)

        out = await bt.compare_weights(
            weight_sets={"重资金": {"main_inflow": 120, "volume_ratio": 10}},
            days=30,
            hold_days=5,
        )
        r = out["results"]["重资金"]
        assert r["max_total_weight"] > 0
        assert "main_inflow" in r["weights"]
        assert r["weights"]["main_inflow"]["value"] == pytest.approx(120)
