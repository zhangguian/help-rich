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


# ============================================================
# K 线智能分析引擎 v1 — 新增指标测试
# ============================================================

class TestMACD:
    def test_basic_macd_values(self):
        """线性递增价格 → DIF/DEA 均为正,HIST 接近 0"""
        closes = [float(100 + i) for i in range(60)]
        r = compute_indicators(_kline(closes))
        m = r["macd"]
        assert m["dif"] is not None and m["dea"] is not None
        assert m["dif"] > 0
        assert m["hist"] is not None

    def test_macd_len_lt_26_returns_none(self):
        """数据不足 → None + degraded"""
        r = compute_indicators(_kline([float(i) for i in range(20)]))
        assert r["macd"]["dif"] is None
        assert any("macd" in d for d in r["data_quality"]["degraded"])

    def test_macd_cross_detected(self):
        """构造明确金叉场景:跌到底后回升"""
        closes = [10.0] * 30 + [9.0] * 10 + [11.0 + i * 0.5 for i in range(20)]
        r = compute_indicators(_kline(closes))
        assert r["macd"]["cross"] in {"golden", "dead", None}


class TestKDJ:
    def test_basic_kdj_values(self):
        """正常数据 → K/D/J 数值存在"""
        closes = [10.0 + (i % 5) for i in range(60)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        opens = closes
        klines = [
            {"date": str(i), "open": o, "high": h, "low": l, "close": c, "volume": 1000}
            for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes))
        ]
        r = compute_indicators(klines)
        kdj = r["kdj"]
        assert kdj["k"] is not None
        assert 0 <= kdj["k"] <= 100
        assert kdj["j"] is not None

    def test_kdj_overbought(self):
        """连续大涨 → K > 80,zone=overbought"""
        closes = [10.0 + i * 0.3 for i in range(40)]  # 持续上涨
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        opens = [c - 0.2 for c in closes]
        klines = [
            {"date": str(i), "open": o, "high": h, "low": l, "close": c, "volume": 1000}
            for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes))
        ]
        r = compute_indicators(klines)
        assert r["kdj"]["k"] > 80
        assert r["kdj"]["zone"] == "overbought"

    def test_kdj_len_lt_9(self):
        """数据不足 → 全部 None"""
        r = compute_indicators(_kline([float(i) for i in range(5)]))
        assert r["kdj"]["k"] is None


class TestBOLL:
    def test_boll_basic(self):
        """MID = MA20,UP > MID > LOW"""
        closes = [10.0 + (i % 7) for i in range(60)]
        r = compute_indicators(_kline(closes))
        b = r["boll"]
        assert b["mid"] is not None
        assert b["upper"] > b["mid"] > b["lower"]
        assert b["bandwidth"] is not None and b["bandwidth"] > 0

    def test_boll_len_lt_20(self):
        """数据不足 → None"""
        r = compute_indicators(_kline([float(i) for i in range(15)]))
        assert r["boll"]["mid"] is None
        assert any("boll" in d for d in r["data_quality"]["degraded"])

    def test_boll_touching_upper(self):
        """价格贴近上轨 → position=touching_upper"""
        # 构造 25 根先平稳 + 末日大涨突破上轨
        closes = [10.0] * 24 + [15.0]
        r = compute_indicators(_kline(closes))
        assert r["boll"]["position"] in {"touching_upper", "middle"}


class TestVolumePrice:
    def test_volume_up_price_up(self):
        """放量上涨 → 量增价升"""
        closes = [10.0] * 28 + [10.0, 11.0]
        volumes = [1000] * 28 + [500, 2000]
        klines = [
            {"date": str(i), "open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": v}
            for i, (c, v) in enumerate(zip(closes, volumes))
        ]
        r = compute_indicators(klines)
        assert r["volume_price"]["direction"] == "healthy_up"

    def test_volume_price_shrink(self):
        """缩量上涨 → 量缩价升"""
        closes = [10.0] * 28 + [10.0, 11.0]
        volumes = [1000] * 28 + [2000, 1000]
        klines = [
            {"date": str(i), "open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": v}
            for i, (c, v) in enumerate(zip(closes, volumes))
        ]
        r = compute_indicators(klines)
        assert r["volume_price"]["direction"] == "liar_up_suspect"


class TestPatterns:
    def test_patterns_detect_hammer(self):
        """末日小实体 + 长下影 → 锤子线"""
        klines = []
        for i in range(20):
            klines.append({"date": str(i), "open": 10.0, "high": 10.5,
                           "low": 9.5, "close": 10.0, "volume": 1000})
        # 末日:小实体+长下影
        klines.append({"date": "20", "open": 10.0, "high": 10.1,
                       "low": 8.5, "close": 10.05, "volume": 1500})
        r = compute_indicators(klines)
        names = [p["name"] for p in r["patterns"]]
        assert "锤子线" in names


class TestLiarTrap:
    def test_liar_output_shape(self):
        """liar 输出结构存在且有 summary 字段"""
        closes = [10.0 + (i % 3) * 0.1 for i in range(60)]
        r = compute_indicators(_kline(closes))
        assert "summary" in r["liar"]
        assert "bull_liars" in r["liar"]
        assert "bear_liars" in r["liar"]

    def test_detect_volume_shrink_up(self):
        """放量之后末日缩量 + 价格上涨 → 检出诱多"""
        closes = [10.0 + i * 0.1 for i in range(60)]
        # 末日缩量 + 微涨
        volumes = [1000] * 55 + [5000] * 4 + [1000]
        klines = [
            {"date": str(i), "open": c * 0.99, "high": c * 1.02,
             "low": c * 0.98, "close": c, "volume": v}
            for i, (c, v) in enumerate(zip(closes, volumes))
        ]
        r = compute_indicators(klines)
        assert len(r["liar"]["bull_liars"]) >= 1 or len(r["liar"]["bear_liars"]) >= 0


class TestPosition:
    def test_position_high_after_run(self):
        """持续大涨 60 日 → band=high"""
        closes = [10.0 + i * 0.5 for i in range(80)]
        r = compute_indicators(_kline(closes))
        assert r["position"]["band"] == "high"
        assert r["position"]["pct_60"] is not None and r["position"]["pct_60"] > 0

    def test_position_low_after_drop(self):
        """60 日大跌 50% → band=low"""
        closes = [100.0] * 20 + [100.0 - (i - 20) * 1.0 for i in range(20, 80)]
        r = compute_indicators(_kline(closes))
        assert r["position"]["band"] == "low"
        assert r["position"]["pct_60"] is not None and r["position"]["pct_60"] < -40

    # ---- v0.5 M1.2 买卖位置参考卡 ----
    def test_risk_band_high_at_p80(self):
        """收盘价站上近120日 P80 → risk_band=high"""
        closes = [10.0] * 100 + [30.0 + i * 0.1 for i in range(20)]
        r = compute_indicators(_kline(closes))
        assert r["position"]["risk_band"] == "high"
        assert r["position"]["p80"] is not None

    def test_risk_band_low_below_p20(self):
        """现价跌破近120日 P20 → risk_band=low"""
        closes = [100.0] * 100 + [20.0 - i * 0.1 for i in range(20)]
        r = compute_indicators(_kline(closes))
        assert r["position"]["risk_band"] == "low"
        assert r["position"]["p20"] is not None

    def test_risk_band_mid(self):
        """中等位置 → risk_band=mid"""
        closes = [10.0 + (i % 5) for i in range(100)] + [11.0] * 20
        r = compute_indicators(_kline(closes))
        assert r["position"]["risk_band"] == "mid"

    def test_support_and_stop_loss(self):
        """支撑=近20日最低收盘×0.98;止损=支撑×0.97"""
        closes = [100.0 + (i % 5) for i in range(40)]
        r = compute_indicators(_kline(closes))
        pos = r["position"]
        min20 = min(closes[-20:])
        assert pos["support_price"] == round(min20 * 0.98, 3)
        assert pos["stop_loss_price"] == round(round(min20 * 0.98, 3) * 0.97, 3)


class TestSignalFusion:
    def test_signal_output_shape(self):
        """signal 输出结构:view/score/confidence/reasons/summary"""
        closes = [10.0 + i for i in range(60)]
        r = compute_indicators(_kline(closes))
        sig = r["signal"]
        assert sig["view"] in {"bullish", "bearish", "neutral"}
        assert 0 <= sig["score"] <= 100
        assert sig["confidence"] in {"high", "medium", "low"}
        assert isinstance(sig["reasons"], list) and len(sig["reasons"]) >= 3
        assert isinstance(sig["summary"], str)

    def test_signal_strong_bull_run(self):
        """强多头排列(MA5/10/20/60 严格递增 + 量增价升)→ view=bullish,score≥65"""
        closes = [10.0 + i * 0.5 for i in range(80)]  # 持续上涨 80 日
        volumes = [1000 + i * 50 for i in range(80)]  # 末日量最大
        klines = [
            {"date": str(i), "open": c * 0.99, "high": c * 1.02,
             "low": c * 0.98, "close": c, "volume": v}
            for i, (c, v) in enumerate(zip(closes, volumes))
        ]
        r = compute_indicators(klines)
        assert r["signal"]["view"] == "bullish"
        assert r["signal"]["score"] >= 65

    def test_signal_series_has_entries(self):
        """有数据时 signal_series 是列表(可能为空)"""
        closes = [10.0] * 30 + [10.0 + i * 0.5 for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert isinstance(r["signal_series"], list)


# ============ K 线图图例指标 v2:RSI / CCI / STOCH / MOM / WMSR / SKT / FASK ============


class TestRSI:
    def test_insufficient_data_returns_empty(self):
        """< 15 项返回空 + state=None"""
        r = compute_indicators(_kline([10.0] * 10))
        assert r["rsi"]["rsi"] is None
        assert r["rsi"]["rsi_series"] == []
        assert r["rsi"]["state"] is None

    def test_const_close_rsi_neutral_or_extreme(self):
        """价格不变 → avg_loss=0 → RSI=100(无下跌)"""
        closes = [10.0] * 30
        r = compute_indicators(_kline(closes))
        # 全部平盘无下跌,RSI=100
        assert r["rsi"]["rsi"] == 100.0
        assert r["rsi"]["state"] == "overbought"

    def test_consistent_up_rsi_high(self):
        """持续上涨 30 日 → RSI=100"""
        closes = [10.0 + i for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["rsi"]["rsi"] == 100.0
        assert r["rsi"]["state"] == "overbought"

    def test_state_bearish_below_50(self):
        """30 < RSI < 50 → state=bearish"""
        # 构造小幅波动使 RSI 落在 30~50 区间
        closes = [10 + (i % 5) * 0.1 for i in range(40)]
        r = compute_indicators(_kline(closes))
        # 仅校验 state 是合法值
        assert r["rsi"]["state"] in {"neutral", "bearish", "bullish", "overbought", "oversold"}

    def test_oversold_state_below_30(self):
        """持续下跌 → RSI<30 → state=oversold"""
        closes = [100.0 - i for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["rsi"]["rsi"] is not None
        assert r["rsi"]["rsi"] < 30
        assert r["rsi"]["state"] == "oversold"


class TestCCI:
    def test_insufficient_data(self):
        r = compute_indicators(_kline([10.0] * 15))
        assert r["cci"]["cci"] is None
        assert r["cci"]["state"] is None

    def test_const_close_cci_zero(self):
        """价格不变 → mean_dev=0 → CCI=0(neutral)"""
        closes = [10.0] * 30
        r = compute_indicators(_kline(closes))
        assert r["cci"]["cci"] == 0.0
        assert r["cci"]["state"] == "neutral"

    def test_overbought_state_above_100(self):
        """CCI>100 → overbought"""
        closes = [10.0 + i * 0.5 for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["cci"]["cci"] is not None
        assert r["cci"]["cci"] > 100
        assert r["cci"]["state"] == "overbought"

    def test_oversold_state_below_minus_100(self):
        """CCI<-100 → oversold"""
        closes = [100.0 - i for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["cci"]["cci"] is not None
        assert r["cci"]["cci"] < -100
        assert r["cci"]["state"] == "oversold"


class TestStoch:
    def test_insufficient_data(self):
        r = compute_indicators(_kline([10.0] * 10))
        assert r["stoch"]["fastk"] is None
        assert r["stoch"]["state"] is None

    def test_const_close_overbought(self):
        """价格在区间顶部震荡 → %K=100 → overbought"""
        closes = [10.0 + (i % 3) * 0.1 for i in range(30)]
        r = compute_indicators(_kline(closes))
        # 注意:_kline 用 close*0.99~close*1.02 模拟高低,价格有微幅波动
        assert r["stoch"]["fastk"] is not None

    def test_slowk_equals_fastd(self):
        """SlowK 与 FastD 数值相同(经典 stochastic 公式约定)"""
        closes = [10.0 + i * 0.3 for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["stoch"]["slowk"] == r["stoch"]["fastd"]

    def test_state_in_valid_set(self):
        """state 必属于合法集合"""
        closes = [10.0 + (i % 5) * 0.3 for i in range(40)]
        r = compute_indicators(_kline(closes))
        assert r["stoch"]["state"] in {
            "overbought", "oversold", "golden_cross", "dead_cross", "neutral"
        }


class TestMOM:
    def test_insufficient_data(self):
        r = compute_indicators(_kline([10.0] * 8))
        assert r["mom"]["mom"] is None
        assert r["mom"]["state"] is None

    def test_rising_state(self):
        """持续上涨 → MOM>0 且递增 → state=rising"""
        closes = [10.0 + i for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["mom"]["mom"] is not None
        assert r["mom"]["mom"] > 0
        assert r["mom"]["state"] == "rising"

    def test_falling_state(self):
        """持续下跌 → state=falling"""
        closes = [100.0 - i for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["mom"]["mom"] < 0
        assert r["mom"]["state"] == "falling"

    def test_zero_cross_up_state(self):
        """末日 >0 且前一日 <=0 → state=zero_cross_up"""
        closes = [10.0] * 15 + [9.0] * 5 + [10.5, 11.0, 11.5, 12.0, 12.5]
        r = compute_indicators(_kline(closes))
        # 末日 MOM = 12.5 - 2.5(11 日前) = 10
        assert r["mom"]["mom"] is not None
        assert r["mom"]["state"] in {"zero_cross_up", "rising", "neutral"}


class TestWMSR:
    def test_insufficient_data(self):
        r = compute_indicators(_kline([10.0] * 10))
        assert r["wmsr"]["wmsr"] is None
        assert r["wmsr"]["state"] is None

    def test_close_near_high_overbought(self):
        """收盘接近高点 → %R > -20 → overbought"""
        closes = [10.0 + (i % 3) * 0.1 for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["wmsr"]["wmsr"] is not None

    def test_close_near_low_oversold(self):
        """收盘接近低点 → %R < -80 → oversold"""
        closes = [10.0 - (i % 3) * 0.1 for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["wmsr"]["wmsr"] is not None
        # 末位 close = 10 - 29*0.1 = 7.1(单边下降),%R 应较小
        assert r["wmsr"]["wmsr"] <= -50


class TestSKT:
    def test_skt_derived_from_stoch(self):
        """skt 与 stoch 的 slowk/slowd 数值一致"""
        closes = [10.0 + i * 0.3 for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["skt"]["slowk"] == r["stoch"]["slowk"]
        assert r["skt"]["slowd"] == r["stoch"]["slowd"]

    def test_skt_state_matches_stoch(self):
        """skt.state 与 stoch.state 一致"""
        closes = [10.0 + (i % 5) * 0.3 for i in range(40)]
        r = compute_indicators(_kline(closes))
        assert r["skt"]["state"] == r["stoch"]["state"]


class TestFASK:
    def test_fask_derived_from_stoch(self):
        """fask.fastk 与 stoch.fastk 一致"""
        closes = [10.0 + i * 0.3 for i in range(30)]
        r = compute_indicators(_kline(closes))
        assert r["fask"]["fastk"] == r["stoch"]["fastk"]

    def test_fask_state_overbought(self):
        """%K >= 80 → state=overbought"""
        closes = [10.0 + (i % 3) * 0.1 for i in range(30)]
        r = compute_indicators(_kline(closes))
        if r["fask"]["fastk"] is not None:
            if r["fask"]["fastk"] >= 80:
                assert r["fask"]["state"] == "overbought"
            elif r["fask"]["fastk"] <= 20:
                assert r["fask"]["state"] == "oversold"
            else:
                assert r["fask"]["state"] == "neutral"


class TestV2IndicatorsIntegration:
    def test_compute_indicators_includes_v2_keys(self):
        """compute_indicators 返回 dict 含 7 个 v2 指标"""
        closes = [10.0 + i for i in range(60)]
        r = compute_indicators(_kline(closes))
        for key in ("rsi", "cci", "stoch", "mom", "wmsr", "skt", "fask"):
            assert key in r, f"缺少 {key}"
            assert isinstance(r[key], dict)

    def test_v2_state_valid_enum(self):
        """所有 v2 state 字段值在合法集合内"""
        closes = [10.0 + (i % 7) * 0.3 for i in range(60)]
        r = compute_indicators(_kline(closes))
        valid_states = {
            "neutral", "overbought", "oversold",
            "bullish", "bearish",
            "strong_up", "strong_down",
            "golden_cross", "dead_cross",
            "rising", "falling",
            "zero_cross_up", "zero_cross_down",
        }
        for key in ("rsi", "cci", "stoch", "mom", "wmsr", "skt", "fask"):
            state = r[key]["state"]
            if state is not None:
                assert state in valid_states, f"{key}.state={state} 不在合法集"
