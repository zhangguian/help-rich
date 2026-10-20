"""确定性决策引擎单测(decision_service 纯函数)"""
import pytest

from app.services.decision_service import (
    DecisionContext,
    MarketContext,
    effective_price,
    judge_trend,
    judge_t_plan,
)


def _kline(closes: list[float], volumes: list[int] | None = None,
           highs: list[float] | None = None, lows: list[float] | None = None) -> list[dict]:
    out = []
    for i, c in enumerate(closes):
        out.append({
            "date": f"2026-01-{i + 1:02d}",
            "open": c * 0.99,
            "high": highs[i] if highs else c * 1.02,
            "low": lows[i] if lows else c * 0.98,
            "close": c,
            "volume": volumes[i] if volumes else 10000,
        })
    return out


def _ctx(closes, **kw) -> DecisionContext:
    from app.services.ta_service import compute_indicators
    klines = _kline(closes, highs=kw.get("highs"), lows=kw.get("lows"))
    ind = compute_indicators(klines)
    return DecisionContext(
        stock_code="002185.SZ",
        stock_name="华天科技",
        indicators=ind,
        klines=klines,
        current_price=kw.get("current_price", closes[-1]),
        prev_close=kw.get("prev_close", closes[-2] if len(closes) > 1 else closes[-1]),
        cost_basis=kw.get("cost_basis"),
        shares=kw.get("shares", 0),
        position_status=kw.get("position_status", "empty"),
        env=kw.get("env", MarketContext()),
    )


def test_effective_price_prefers_realtime():
    ctx = _ctx([10.0] * 30, current_price=12.5)
    assert effective_price(ctx) == 12.5


def test_effective_price_falls_back_to_latest_close():
    ctx = _ctx([10.0, 11.0] + [11.0] * 28, current_price=None)
    assert effective_price(ctx) == 11.0


def test_judge_trend_up_channel_accelerate():
    # 持续上涨 → 通道向上 + 量价健康
    closes = [10.0 + i * 0.3 for i in range(60)]
    ctx = _ctx(closes)
    phase = judge_trend(ctx)["phase"]
    assert "上涨通道" in phase


def test_judge_trend_note_contains_numbers():
    closes = [10.0 + i * 0.3 for i in range(60)]
    note = judge_trend(_ctx(closes))["note"]
    assert "量比" in note


def test_t_plan_unsuitable_when_amplitude_too_small():
    # 几乎无波动 → 振幅不足
    # 注:振幅 =(high-low)/昨收(设计文档 §6 G1)。默认夹具 ±2% 会造出 4% 振幅,
    #   反而高于 3% 门槛,故这里显式给窄幅 high/low,让"波动不足"场景真实成立。
    closes = [10.0] * 60
    ctx = _ctx(
        closes,
        highs=[c * 1.002 for c in closes],
        lows=[c * 0.998 for c in closes],
    )
    plan = judge_t_plan(ctx)
    assert plan["suitable"] is False
    assert "振幅" in plan["unsuitable_signals"]


def test_t_plan_needs_position_flag_when_empty():
    closes = [10.0 + (i % 5) * 0.4 for i in range(60)]
    ctx = _ctx(closes, shares=0)
    plan = judge_t_plan(ctx)
    assert plan["needs_position"] is True


def test_t_plan_all_prices_traceable():
    closes = [10.0 + (i % 7) * 0.5 for i in range(60)]
    ctx = _ctx(closes)
    plan = judge_t_plan(ctx)
    if plan["suitable"]:
        ks = ctx.klines[-5:]
        hi = max(float(k["high"]) for k in ks)
        lo = min(float(k["low"]) for k in ks)
        assert plan["t_high"] <= round(hi, 6) + 1e-6
        assert plan["t_low"] >= round(lo, 6) - 1e-6
