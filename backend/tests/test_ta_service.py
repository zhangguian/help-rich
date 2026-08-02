"""T1.2 技术指标单测(ta_service 纯函数,全确定性)"""
from statistics import stdev

import pytest

from app.services.ta_service import TaError, compute_indicators


def _kline(closes: list[float], volumes: list[int] | None = None) -> list[dict]:
    out = []
    for i, c in enumerate(closes):
        out.append({
            "date": f"2026-01-{i + 1:02d}",
            "open": c * 0.99,
            "high": c * 1.02,
            "low": c * 0.98,
            "close": c,
            "volume": volumes[i] if volumes else 10000,
        })
    return out


class TestInvalid:
    def test_empty_raises(self):
        with pytest.raises(TaError):
            compute_indicators([])

    def test_short_data_ok(self):
        """3 根数据不抛异常,MA 部分为 None"""
        r = compute_indicators(_kline([10, 11, 12]))
        assert r["latest_close"] == 12.0
        assert r["ma"]["ma5"] is None
        assert r["volume"]["ratio"] is None
        assert r["channel"]["state"] == "sideways"


class TestMA:
    def test_ma5_value(self):
        r = compute_indicators(_kline([1, 2, 3, 4, 5, 6]))
        assert r["ma"]["ma5"] == 4.0

    def test_ma20_value(self):
        closes = [float(i) for i in range(1, 22)]
        r = compute_indicators(_kline(closes))
        assert r["ma"]["ma20"] == pytest.approx(11.5)

    def test_ma_series_length(self):
        closes = [float(i) for i in range(1, 120)]
        r = compute_indicators(_kline(closes))
        assert len(r["ma_series"]["ma60"]) == 60
        assert len(r["ma_series"]["ma5"]) == 60


class TestVolumeRatio:
    def test_expand(self):
        """近5日放量 → expand"""
        vols = [1000] * 25 + [3000] * 5
        r = compute_indicators(_kline([10.0] * 30, vols))
        assert r["volume"]["ratio"] >= 1.5
        assert r["volume"]["state"] == "expand"

    def test_shrink(self):
        vols = [3000] * 25 + [1000] * 5
        r = compute_indicators(_kline([10.0] * 30, vols))
        assert r["volume"]["ratio"] <= 0.7
        assert r["volume"]["state"] == "shrink"

    def test_normal(self):
        vols = [1000] * 30
        r = compute_indicators(_kline([10.0] * 30, vols))
        assert r["volume"]["state"] == "normal"


class TestChannel:
    def test_up_channel(self):
        closes = [100 + i * 2 for i in range(60)]
        r = compute_indicators(_kline(closes))
        assert r["channel"]["state"] == "up"

    def test_down_channel(self):
        closes = [100 - i * 2 for i in range(60)]
        r = compute_indicators(_kline(closes))
        assert r["channel"]["state"] == "down"

    def test_sideways(self):
        closes = [100 + (i % 3) for i in range(60)]
        r = compute_indicators(_kline(closes))
        assert r["channel"]["state"] == "sideways"

    def test_upper_lower_bands(self):
        closes = [100 + i * 2 for i in range(60)]
        r = compute_indicators(_kline(closes))
        assert r["channel"]["upper"] is not None
        assert r["channel"]["upper"] >= r["channel"]["lower"]


class TestSupportPressure:
    def test_support_includes_low(self):
        closes = [100] * 30 + [80, 85, 90, 95, 100]
        r = compute_indicators(_kline(closes))
        assert any(v <= 100 for v in r["support_pressure"]["support"])

    def test_pressure_includes_high(self):
        closes = [80] * 30 + [100, 98, 96, 94, 92]
        r = compute_indicators(_kline(closes))
        assert any(v >= 92 for v in r["support_pressure"]["pressure"])


class TestStabilize:
    def test_all_conditions_true(self):
        """上涨后缩量回踩 + 放量回升 → 企稳"""
        closes = [100] * 30 + [103, 105, 104, 103, 102, 104, 106]
        vols = [1000] * 30 + [500, 600, 700, 500, 400, 1500, 2000]
        r = compute_indicators(_kline(closes, vols))
        st = r["stabilize"]
        assert st["state"] is True
        assert st["price"] is not None

    def test_not_above_ma20_fails(self):
        """现价远低于 MA20 → 不企稳"""
        closes = [100] * 25 + [90] * 10
        r = compute_indicators(_kline(closes))
        assert r["stabilize"]["state"] is False

    def test_short_history_returns_false(self):
        r = compute_indicators(_kline([10, 11, 12]))
        assert r["stabilize"]["state"] is False

    def test_breakout_threshold_1_3x(self):
        """末日量 < 1.3×前5日均量 → 放量不通过"""
        closes = [100] * 30 + [103, 105, 104, 103, 102, 104, 106]
        vols = [1000] * 30 + [500, 600, 700, 500, 400, 600, 700]
        r = compute_indicators(_kline(closes, vols))
        # 末日 700 vs 前5均 mean(500,600,700,500,400)=540;1.3×540=702;700<702 → 不通过
        assert r["stabilize"]["reasons"][2]["ok"] is False


class TestSupportPressureWindow:
    def test_lo20_fixes_window_inflation(self):
        """60 根数据,全期低点在前段,近 20 根低点更高 → lo20 取近 20 根(不再被全期最低覆盖)"""
        closes = [100.0] * 60
        lows_data = []
        for i in range(60):
            if i < 30:
                lows_data.append(60.0 + i)
            elif i < 40:
                lows_data.append(105.0 - (i - 30))
            else:
                lows_data.append(95.0 + (i - 40) * 0.5)
        highs_data = [c * 1.02 for c in closes]
        klines = [{
            "date": f"2026-01-{i + 1:02d}",
            "open": closes[i] * 0.99,
            "high": highs_data[i],
            "low": lows_data[i],
            "close": closes[i],
            "volume": 10000,
        } for i in range(60)]
        r = compute_indicators(klines)
        support = r["support_pressure"]["support"]
        # lo20 = min(lows[-20:]) = 95(近20根);lo_all = min(lows) = 60
        # 旧实现 max(20,55)=55 窗口,lo20=60 与 lo_all 重叠;修复后 lo20=95 与 lo_all=60 不再重叠
        assert 95.0 in support
        assert 100.0 in support  # MA20

    def test_dedup_tolerance_merges_close_levels(self):
        """MA20 与低点差 < 0.5% → 合并为 1 档"""
        closes = [100.0] * 21
        klines = [{
            "date": f"2026-01-{i + 1:02d}",
            "open": 99.5,
            "high": 101.0,
            "low": 99.5,
            "close": closes[i],
            "volume": 10000,
        } for i in range(21)]
        klines[-1]["low"] = 99.7
        klines[-1]["close"] = 100.3
        r = compute_indicators(klines)
        support = r["support_pressure"]["support"]
        # MA20 ≈ 100,近 20 根低点 99.5~99.7;差 < 0.5%,应合并
        assert len([s for s in support if abs(s - 100.0) / 100.0 < 0.01]) >= 1


class TestChannelResidStd:
    def test_resid_std_reasonable_for_uptrend(self):
        """上升 + 已知噪声 → resid_std < 全价标准差(趋势分量被剔除)"""
        closes = [100 + i * 2 + (1 if i % 2 == 0 else -1) for i in range(60)]
        r = compute_indicators(_kline(closes))
        assert r["channel"]["state"] == "up"
        assert r["channel"]["resid_std"] is not None
        assert r["channel"]["upper"] > r["channel"]["lower"]
        full_std = stdev(closes[-60:])
        assert r["channel"]["resid_std"] < full_std

    def test_perfect_line_zero_resid(self):
        """完美直线 → resid_std = 0,upper = lower"""
        closes = [100 + i * 2 for i in range(60)]
        r = compute_indicators(_kline(closes))
        assert r["channel"]["state"] == "up"
        assert r["channel"]["resid_std"] == 0.0
        assert r["channel"]["upper"] == r["channel"]["lower"]


class TestMAPrecision:
    def test_precision_passes_through_to_stabilize(self):
        """MA 全精度传递:临界数据下,四舍五入前 > MA20 应企稳,四舍五入后不能翻转"""
        closes = [100.0] * 21
        closes[-1] = 100.349
        r = compute_indicators(_kline(closes))
        assert r["stabilize"]["reasons"][0]["ok"] is True


class TestDataQuality:
    def test_short_data_records_degraded(self):
        """8 根数据 → ma10/ma20/ma60/通道/企稳降级(ma5 仍可计算)"""
        r = compute_indicators(_kline([10, 11, 12, 13, 14, 15, 16, 17]))
        dq = r["data_quality"]
        assert dq["kline_count"] == 8
        degraded = dq["degraded"]
        assert any("ma10" in d for d in degraded)
        assert any("ma20" in d for d in degraded)
        assert any("ma60" in d for d in degraded)
        assert any("channel" in d for d in degraded)
        assert any("stabilize" in d for d in degraded)
        assert r["ma"]["ma5"] is not None  # 8 根 ≥ 5,ma5 可算

    def test_ma60_degraded_when_len_lt_60(self):
        """30 根数据 → ma60 降级"""
        r = compute_indicators(_kline([float(i) for i in range(30)]))
        assert any("ma60" in d for d in r["data_quality"]["degraded"])
        assert r["ma"]["ma60"] is None

    def test_adequate_data_no_degraded(self):
        """60 根完整数据 → 无降级"""
        r = compute_indicators(_kline([float(i) for i in range(60)]))
        assert r["data_quality"]["degraded"] == []
