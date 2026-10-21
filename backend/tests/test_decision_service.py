"""确定性决策引擎单测(decision_service 纯函数)"""
import pytest

from app.services.decision_service import (
    DecisionContext,
    MarketContext,
    build_decision,
    derive_verdict,
    effective_price,
    judge_do_not,
    judge_entry,
    judge_exit,
    judge_loss_plan,
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


# ============================ Task 2: 买/卖/亏损/别动判定 + verdict 组装 ============================


def _action_kinds(actions):
    return [a["kind"] for a in actions]


def test_derive_verdict_priority_stop_beats_exit():
    actions = [
        {"kind": "exit", "status": "now"},
        {"kind": "stop", "status": "now"},
    ]
    assert derive_verdict(actions, "loss") == "sell"


def test_derive_verdict_wait_when_nothing_now():
    assert derive_verdict([{"kind": "entry", "status": "armed"}], "empty") == "wait"


def test_derive_verdict_hold_for_position_without_signal():
    assert derive_verdict([], "profit") == "hold"


def test_entry_produces_actions_with_traceable_price():
    closes = [10.0 + (i % 9) * 0.4 for i in range(60)]
    ctx = _ctx(closes, position_status="empty", shares=0)
    actions = judge_entry(ctx)
    ind = ctx.indicators
    known = set()
    for v in (ind.get("ma") or {}).values():
        if v is not None:
            known.add(round(float(v), 3))
    pos = ind.get("position") or {}
    for key in ("p20", "p80", "support_price", "stop_loss_price"):
        if pos.get(key) is not None:
            known.add(round(float(pos[key]), 3))
    st = ind.get("stabilize") or {}
    if st.get("price") is not None:
        known.add(round(float(st["price"]), 3))
    for a in actions:
        if a["price"] is not None:
            assert round(a["price"], 3) in known
        assert a["basis"]           # 每条都要有依据
        assert a["status"] in ("now", "armed", "blocked")


def test_do_not_contains_stop_instruction_when_klines_short():
    from app.services.ta_service import compute_indicators
    klines = _kline([10.0] * 10)
    ctx = DecisionContext(
        stock_code="002185.SZ", stock_name="x",
        indicators=compute_indicators(klines), klines=klines,
        current_price=10.0, prev_close=10.0, cost_basis=None, shares=0,
        position_status="empty", env=MarketContext(),
    )
    assert any("K 线不足" in s for s in judge_do_not(ctx))


def test_build_decision_shape_and_no_llm_fields():
    closes = [10.0 + (i % 11) * 0.3 for i in range(60)]
    d = build_decision(_ctx(closes))
    for key in ("verdict", "headline", "confidence", "role", "actions",
                "stop_loss", "position_pct", "do_not", "t_plan",
                "trend_state", "market_env", "data_quality"):
        assert key in d
    assert d["verdict"] in ("buy", "add", "hold", "reduce", "sell", "wait")
    assert d["role"] in ("建仓参考", "止盈参考", "解套参考")
    assert isinstance(d["actions"], list)
    assert isinstance(d["do_not"], list)


def test_build_decision_role_follows_position_status():
    closes = [10.0 + (i % 11) * 0.3 for i in range(60)]
    d_profit = build_decision(_ctx(closes, position_status="profit", shares=100, cost_basis=9.0))
    d_loss = build_decision(_ctx(closes, position_status="loss", shares=100, cost_basis=20.0))
    assert d_profit["role"] == "止盈参考"
    assert d_loss["role"] == "解套参考"


def test_build_decision_actions_kinds_are_from_allowed_vocabulary():
    closes = [10.0 + (i % 11) * 0.3 for i in range(60)]
    allowed = {"entry", "add", "exit", "stop", "t_sell", "t_buyback", "watch"}
    for status in ("empty", "profit", "loss"):
        d = build_decision(_ctx(closes, position_status=status, shares=100, cost_basis=9.0))
        assert set(_action_kinds(d["actions"])) <= allowed


# ---- 父代理补充修正 4:G5 T 区间正宽度 / unsuitable_signals 语义归位 ----


def test_t_plan_unsuitable_when_t_range_has_no_width():
    # p20 == p80 的横盘 → T 区间退化为 0 宽 → 不适合做 T。
    # 注:brief 原夹具给 highs/lows ±0.1%(振幅 0.2%),会先命中 G1「振幅不足」,
    #   走不到 G5;这里用默认夹具(±2%,振幅 4%)让「分位带退化」这一 G5 条件真实成立。
    closes = [10.0] * 60
    ctx = _ctx(closes)
    plan = judge_t_plan(ctx)
    assert plan["suitable"] is False
    assert "无宽度" in plan["unsuitable_signals"]


def test_t_plan_unsuitable_when_p20_equals_p80_forced(monkeypatch):
    # 直接构造 0 宽上下文:P20 与 P80 取同一值 → t_high == t_low
    closes = [10.0] * 60
    ctx = _ctx(closes)
    monkeypatch.setitem(ctx.indicators["position"], "p20", 10.05)
    monkeypatch.setitem(ctx.indicators["position"], "p80", 10.05)
    plan = judge_t_plan(ctx)
    assert plan["suitable"] is False
    assert "无宽度" in plan["unsuitable_signals"]


def test_t_plan_suitable_has_empty_unsuitable_signals():
    closes = [10.0 + (i % 7) * 0.5 for i in range(60)]
    ctx = _ctx(closes)
    plan = judge_t_plan(ctx)
    if plan["suitable"]:
        # 止损提示归位到顶层 stop_loss,TPlan 不再承载
        assert plan["unsuitable_signals"] == ""
