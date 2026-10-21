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


# ---- L3 解套路径(父代理补实现:设计文档 §6.5) ----


def _loss_ctx(monkeypatch, p80: float, cost_basis: float | None = 15.0):
    closes = [10.0 + (i % 5) * 0.4 for i in range(60)]
    ctx = _ctx(closes, position_status="loss", shares=100, cost_basis=cost_basis)
    monkeypatch.setitem(ctx.indicators["position"], "p80", p80)
    return ctx


def _unlock_actions(actions):
    return [a for a in actions if a["label"] == "解套路径"]


def test_loss_plan_gives_unlock_path_when_p80_above_cost(monkeypatch):
    # 现价 11.60,成本 15.00,P80 16.00 > 成本 → 能解套,告诉用户要涨多少
    ctx = _loss_ctx(monkeypatch, p80=16.0)
    acts = _unlock_actions(judge_loss_plan(ctx))
    assert len(acts) == 1
    a = acts[0]
    assert a["kind"] == "watch"
    assert a["status"] == "armed"
    assert "可解套" in a["condition"]
    assert "需涨" in a["condition"]
    assert a["price"] == 16.0          # 价格可追溯:就是 indicators.position.p80
    assert any("持仓成本 15.00" in b for b in a["basis"])


def test_loss_plan_says_cannot_breakeven_when_p80_below_cost(monkeypatch):
    # 成本 20.00(现价 11.60 → 需涨 72.4% > 30%),P80 12.00 < 成本 → 回不了本 + 不建议死扛
    ctx = _loss_ctx(monkeypatch, p80=12.0, cost_basis=20.0)
    acts = _unlock_actions(judge_loss_plan(ctx))
    assert len(acts) == 1
    assert "回不了本" in acts[0]["condition"]
    assert "不建议死扛" in acts[0]["condition"]


def test_loss_plan_no_dead_hold_wording_when_need_pct_under_30(monkeypatch):
    # 成本 15.00(需涨 29.3%,未过 30% 阈值)→ 只说回不了本,不加「不建议死扛」
    ctx = _loss_ctx(monkeypatch, p80=12.0, cost_basis=15.0)
    acts = _unlock_actions(judge_loss_plan(ctx))
    assert len(acts) == 1
    assert "回不了本" in acts[0]["condition"]
    assert "不建议死扛" not in acts[0]["condition"]


def test_loss_plan_no_unlock_action_without_cost_basis(monkeypatch):
    # 缺成本 → 不生成解套路径,更不编数字
    ctx = _loss_ctx(monkeypatch, p80=16.0, cost_basis=None)
    assert _unlock_actions(judge_loss_plan(ctx)) == []


def test_loss_plan_no_unlock_action_without_p80(monkeypatch):
    closes = [10.0 + (i % 5) * 0.4 for i in range(60)]
    ctx = _ctx(closes, position_status="loss", shares=100, cost_basis=15.0)
    monkeypatch.setitem(ctx.indicators["position"], "p80", None)
    assert _unlock_actions(judge_loss_plan(ctx)) == []


def test_loss_plan_unlock_path_shows_in_build_decision(monkeypatch):
    # 端到端:亏损持仓的决策卡里要能直接看到解套路径
    closes = [10.0 + (i % 5) * 0.4 for i in range(60)]
    ctx = _ctx(closes, position_status="loss", shares=100, cost_basis=15.0)
    monkeypatch.setitem(ctx.indicators["position"], "p80", 16.0)
    d = build_decision(ctx)
    assert d["role"] == "解套参考"
    assert len(_unlock_actions(d["actions"])) == 1
    assert "可解套" in d["headline"]


# ==================================================================
# 买入候选的 status 契约(2026-10-21 父代理评审新增)
#
# 背景:实跑发现卡片会同时出现
#   「可以建仓 · 现在可做」  +  「🚫 别动: 下跌通道中不要抄底」
# 且 C2 的 condition 写着「站回 15.19 元且 KDJ 出金叉」,
# 现价 14.35(未站回)却标「现在可做」—— 与设计文档 §5
# 「now = 此刻条件已满足」直接冲突。
# ==================================================================


def _ind(**over) -> dict:
    """一份最小可用的 indicators(只给判定器真正读到的字段)"""
    base = {
        "latest_close": 14.35,
        "ma": {"ma5": 14.0, "ma10": 14.2, "ma20": 14.8, "ma60": 15.0},
        "volume": {"ratio": 1.0, "state": "normal"},
        "volume_price": {"direction": "flat"},
        "channel": {"state": "sideways"},
        "support_pressure": {"support": [], "pressure": []},
        "stabilize": {"state": False, "price": None, "reasons": []},
        "macd": {"dif": 0.0, "dea": 0.0, "hist": 0.0, "cross": None},
        "kdj": {"k": 50.0, "d": 50.0, "j": 50.0, "zone": "neutral", "cross": None},
        "boll": {"upper": 15.0, "mid": 14.0, "lower": 13.0, "bandwidth": 0.1,
                 "squeeze": False, "position": "middle"},
        "position": {"p20": 15.19, "p80": 19.16, "support_price": 13.61,
                     "stop_loss_price": 13.2, "risk_band": "mid", "band": "mid"},
        "liar": {"bull_liars": [], "bear_liars": []},
        "signal": {"view": "neutral", "score": 50, "confidence": "medium",
                   "reasons": [], "summary": ""},
        "data_quality": {"kline_count": 190, "degraded": []},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def _ctx_ind(ind: dict, current_price: float, klines=None, **kw) -> DecisionContext:
    klines = klines if klines is not None else _kline([current_price] * 60)
    return DecisionContext(
        stock_code="002185.SZ", stock_name="华天科技",
        indicators=ind, klines=klines,
        current_price=current_price,
        prev_close=kw.get("prev_close", current_price),
        cost_basis=kw.get("cost_basis"), shares=kw.get("shares", 0),
        position_status=kw.get("position_status", "empty"),
        env=kw.get("env", MarketContext()),
    )


def test_entry_c2_not_now_when_price_below_p20():
    """C2 的 condition 是合取式:未站回 P20 就不能标「现在可做」"""
    ind = _ind(
        position={"risk_band": "low"},
        kdj={"zone": "oversold", "cross": "golden", "k": 12.0, "d": 10.0},
    )
    ctx = _ctx_ind(ind, current_price=14.35)   # 14.35 < P20 15.19
    c2 = [a for a in judge_entry(ctx) if a["label"] == "超跌反弹建仓"]
    assert len(c2) == 1
    assert c2[0]["status"] == "armed", "未站回 P20 却标 now = 卡片自相矛盾"
    assert any("未站回" in b for b in c2[0]["basis"]), "必须写明还差什么"


def test_entry_c2_now_when_reclaimed_and_golden():
    """站回 P20 且 KDJ 金叉 → 才允许「现在可做」"""
    ind = _ind(
        position={"risk_band": "low"},
        kdj={"zone": "oversold", "cross": "golden", "k": 12.0, "d": 10.0},
    )
    ctx = _ctx_ind(ind, current_price=15.5)     # 15.5 > P20 15.19
    c2 = [a for a in judge_entry(ctx) if a["label"] == "超跌反弹建仓"]
    assert len(c2) == 1
    assert c2[0]["status"] == "now"


def test_entry_c2_armed_when_no_golden_cross_even_if_reclaimed():
    """已站回 P20 但 KDJ 未金叉 → 仍只能「待触发」"""
    ind = _ind(
        position={"risk_band": "low"},
        kdj={"zone": "oversold", "cross": None, "k": 10.0, "d": 11.0},
    )
    ctx = _ctx_ind(ind, current_price=15.5)
    c2 = [a for a in judge_entry(ctx) if a["label"] == "超跌反弹建仓"]
    assert len(c2) == 1
    assert c2[0]["status"] == "armed"
    assert any("金叉" in b for b in c2[0]["basis"])


def test_entry_not_now_in_down_channel():
    """下跌通道 = 全局「别动」规则生效,建仓候选一律不得标「现在可做」"""
    ind = _ind(
        channel={"state": "down"},
        stabilize={"state": True, "price": 14.0, "reasons": []},
    )
    ctx = _ctx_ind(ind, current_price=14.5)     # ep 14.5 > 企稳价 14.0 → 技术条件已满足
    c1 = [a for a in judge_entry(ctx) if a["label"] == "支撑企稳建仓"]
    assert len(c1) == 1
    assert c1[0]["status"] == "armed", "下跌通道里不得出现「现在可做」"
    assert any("下跌通道" in b for b in c1[0]["basis"])


def test_entry_c3_not_now_in_down_channel():
    """C3 放量突破同样受下跌通道守卫约束"""
    ind = _ind(
        channel={"state": "down"},
        volume={"ratio": 2.0, "state": "expand"},
        support_pressure={"support": [], "pressure": [14.0]},
    )
    ctx = _ctx_ind(ind, current_price=14.5)     # 已突破 14.0 且量比 2.0 → 技术条件全满足
    c3 = [a for a in judge_entry(ctx) if a["label"] == "放量突破追进"]
    assert len(c3) == 1
    assert c3[0]["status"] == "armed"


def test_build_decision_no_buy_verdict_in_down_channel():
    """端到端:下跌通道里结论不能是「可以建仓」,也不能和「别动」打架"""
    ind = _ind(
        channel={"state": "down"},
        stabilize={"state": True, "price": 14.0, "reasons": []},
    )
    ctx = _ctx_ind(ind, current_price=14.5)
    d = build_decision(ctx)
    assert d["verdict"] != "buy", "下跌通道里不该给「可以建仓」"
    assert any("下跌通道" in s for s in d["do_not"])
    # 卡片里「现在可做」的动作一个都不能有
    assert not [a for a in d["actions"] if a["status"] == "now"]


def test_build_decision_buy_verdict_outside_down_channel():
    """对照组:非下跌通道时,技术条件满足就该给「可以建仓」"""
    ind = _ind(
        channel={"state": "sideways"},
        stabilize={"state": True, "price": 14.0, "reasons": []},
    )
    ctx = _ctx_ind(ind, current_price=14.5)
    d = build_decision(ctx)
    assert d["verdict"] == "buy"
    assert [a for a in d["actions"] if a["status"] == "now"]


# ==================================================================
# blocked 动作的 missing 契约(2026-10-21 跨任务契约)
#
# 背景:「明日预案」要写「解锁条件」,必须知道**真正没满足的条件**是什么。
# L4 补仓摊薄的 basis 是两条**事实**(持仓多少股 / 摊薄后均价多少),
# 转换层若拿 basis[1:] 当缺失条件,就会写出「补 100 股后均价 9.87 元未满足
# 则不解锁」—— 那不是条件,是事实,用户读到的是假前提。
# 所以决策层必须显式给出 missing。
# ==================================================================


def test_l4_blocked_action_carries_missing_conditions():
    """补仓摊薄被 blocked 时:必须带 missing,且 missing 是**条件**不是事实"""
    ind = _ind(channel={"state": "down"})   # 下跌通道 + 默认 stabilize.state=False → 两条 reasons
    ctx = _ctx_ind(ind, current_price=14.35,
                   cost_basis=15.578, shares=600, position_status="loss")
    l4 = [a for a in judge_loss_plan(ctx) if a["label"] == "补仓摊薄"]
    assert len(l4) == 1
    act = l4[0]
    assert act["status"] == "blocked", "下跌通道 + 无企稳信号 → 必须 blocked"
    assert "missing" in act, (
        "blocked 动作必须显式给出缺失条件,否则转换层只能猜 basis[1:] 里的事实"
    )
    txt = " ".join(act["missing"])
    assert any(k in txt for k in ("下跌通道", "企稳", "大盘")), act["missing"]
    assert "均价" not in txt and "持仓" not in txt, f"missing 里只能是条件,不能是事实:{txt}"

