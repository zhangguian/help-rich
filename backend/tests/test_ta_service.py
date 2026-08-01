"""T1.2 技术指标单测(ta_service 纯函数,全确定性)"""
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
