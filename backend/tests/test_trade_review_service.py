"""拟交易复核单测(trade_review_service 纯函数)

三条铁律的验证:
1. 纯函数 —— 同样输入永远同样输出,无 IO / 无 LLM
2. 价格只能来自 indicators / 持仓 / 显式四则运算 —— 不编数字
3. 缺数据 → unknown + degraded,绝不硬给结论
"""
from dataclasses import dataclass
from decimal import Decimal

from app.services.decision_service import DecisionContext, MarketContext
from app.services.trade_review_service import (
    ProposedTrade,
    review_trade,
)


@dataclass
class _Pos:
    """持仓桩(duck typing:只需要 shares / total_cost / avg_cost)"""

    shares: int
    total_cost: Decimal
    realized_pnl: Decimal = Decimal("0")

    @property
    def avg_cost(self) -> Decimal:
        if self.shares <= 0:
            return Decimal("0")
        return self.total_cost / self.shares


def _klines(n: int = 60, close: float = 10.0) -> list[dict]:
    return [
        {
            "date": f"2026-01-{i + 1:02d}",
            "open": close,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": 10000,
        }
        for i in range(n)
    ]


def _ctx(
    price: float = 10.0,
    p20: float | None = 8.0,
    p80: float | None = 12.0,
    n: int = 60,
    shares: int = 0,
    code: str = "002185.SZ",
    t0: bool = False,
) -> DecisionContext:
    position_ind: dict = {}
    if p20 is not None:
        position_ind["p20"] = p20
    if p80 is not None:
        position_ind["p80"] = p80
    return DecisionContext(
        stock_code=code,
        stock_name="华天科技",
        indicators={"position": position_ind},
        klines=_klines(n),
        current_price=price,
        prev_close=price,
        cost_basis=None,
        shares=shares,
        position_status="profit",
        env=MarketContext(),
        t0=t0,
    )


def _action(
    kind: str,
    status: str,
    price: float | None = None,
    label: str = "动作",
    condition: str = "条件",
    missing: list[str] | None = None,
) -> dict:
    a: dict = {
        "kind": kind,
        "status": status,
        "label": label,
        "condition": condition,
        "price": price,
        "basis": [],
    }
    if missing:
        a["missing"] = missing
    return a


def _t_plan(
    suitable: bool = True,
    t_high: float | None = 12.0,
    t_low: float | None = 9.0,
    base: str = "≥50%",
    unsuitable: str = "",
) -> dict:
    return {
        "suitable": suitable,
        "t_high": t_high,
        "t_low": t_low,
        "amplitude_pct": 6.0,
        "sell_trigger": "冲高至 12.00 元附近且量能未超 5 日均量 1.5 倍时卖出 T 仓",
        "buyback_trigger": "回落至 9.00 元附近且缩量企稳(MACD 绿柱不放大)时买回",
        "base_position_pct": base,
        "unsuitable_signals": unsuitable,
        "needs_position": False,
    }


def _decision(
    actions: list[dict] | None = None,
    do_not: list[str] | None = None,
    t_plan: dict | None = None,
    stop_loss: dict | None = None,
    headline: str = "测试结论",
    degraded: list[str] | None = None,
    env_degraded: list[str] | None = None,
) -> dict:
    return {
        "verdict": "hold",
        "headline": headline,
        "actions": actions or [],
        "do_not": do_not or [],
        "t_plan": t_plan if t_plan is not None else _t_plan(),
        "stop_loss": stop_loss,
        "position_pct": "分批止盈",
        "market_env": {"degraded": env_degraded or []},
        "data_quality": {"degraded": degraded or []},
    }


def _pos(shares: int = 1000, total_cost: str = "17021.46") -> _Pos:
    return _Pos(shares=shares, total_cost=Decimal(total_cost))


# ============================================================
# ok 档
# ============================================================

def test_sell_at_stop_loss_is_ok():
    """已跌破止损位 → 卖出是符合纪律的操作 → ok"""
    ctx = _ctx(price=9.0)
    decision = _decision(
        actions=[_action("stop", "now", price=9.5, label="无条件止损", condition="跌破 9.50 元止损")],
        stop_loss={"price": 9.5, "basis": "参考支撑 × 0.97"},
    )
    r = review_trade(ctx, decision, ProposedTrade("sell", 100, 9.0), _pos())
    assert r["verdict"] == "ok"
    assert any("止损" in x for x in r["reasons"])


def test_buy_entry_now_is_ok():
    ctx = _ctx(price=10.0)
    decision = _decision(actions=[_action("entry", "now", price=10.0, label="支撑企稳建仓", condition="回踩 10.00 元不破")])
    r = review_trade(ctx, decision, ProposedTrade("buy", 100, 10.0), _pos())
    assert r["verdict"] == "ok"
    assert r["price_check"]["verdict"] == "ok"
    assert any("支撑企稳建仓" in x for x in r["reasons"])


def test_sell_exit_now_price_within_tolerance_is_ok():
    ctx = _ctx(price=11.9)
    decision = _decision(actions=[_action("exit", "now", price=12.0, label="分批止盈", condition="涨到 12.00 元先减 1/3")])
    r = review_trade(ctx, decision, ProposedTrade("sell", 100, 11.9), _pos())
    assert r["verdict"] == "ok"
    assert r["price_check"]["verdict"] == "ok"


def test_buy_below_suggested_price_is_ok():
    """比建议价更低 → 价位更划算 → ok"""
    ctx = _ctx(price=10.0)
    decision = _decision(actions=[_action("entry", "now", price=10.0, label="支撑企稳建仓", condition="回踩 10.00 元不破")])
    r = review_trade(ctx, decision, ProposedTrade("buy", 100, 9.0), _pos())
    assert r["verdict"] == "ok"
    assert "更划算" in r["price_check"]["note"]


# ============================================================
# conditional 档
# ============================================================

def test_armed_action_is_conditional():
    ctx = _ctx(price=10.0)
    decision = _decision(actions=[_action("entry", "armed", price=10.0, label="支撑企稳建仓", condition="回踩 10.00 元不破")])
    r = review_trade(ctx, decision, ProposedTrade("buy", 100, 10.0), _pos())
    assert r["verdict"] == "conditional"


def test_buy_price_far_above_suggested_is_conditional():
    ctx = _ctx(price=11.0)
    decision = _decision(actions=[_action("entry", "now", price=10.0, label="支撑企稳建仓", condition="回踩 10.00 元不破")])
    r = review_trade(ctx, decision, ProposedTrade("buy", 100, 11.0), _pos())
    assert r["verdict"] == "conditional"
    assert any("追高" in b for b in r["blockers"])


def test_sell_price_far_below_suggested_is_conditional():
    ctx = _ctx(price=11.0)
    decision = _decision(actions=[_action("exit", "now", price=12.0, label="分批止盈", condition="涨到 12.00 元先减 1/3")])
    r = review_trade(ctx, decision, ProposedTrade("sell", 100, 11.0), _pos())
    assert r["verdict"] == "conditional"
    assert any("价差没拿到" in b for b in r["blockers"])


def test_sell_more_than_one_third_is_conditional():
    ctx = _ctx(price=11.9)
    decision = _decision(actions=[_action("exit", "now", price=12.0, label="分批止盈", condition="涨到 12.00 元先减 1/3")])
    r = review_trade(ctx, decision, ProposedTrade("sell", 500, 11.9), _pos(shares=1000))
    assert r["verdict"] == "conditional"
    assert any("建议分批减仓" in b for b in r["blockers"])
    assert r["size_check"]["suggested_shares"] == 333


def test_sell_exactly_one_third_is_not_flagged():
    """1000 股的 1/3 = 333.33 → floor 333;卖 333 股不算超量"""
    ctx = _ctx(price=11.9)
    decision = _decision(actions=[_action("exit", "now", price=12.0, label="分批止盈", condition="涨到 12.00 元先减 1/3")])
    r = review_trade(ctx, decision, ProposedTrade("sell", 333, 11.9), _pos(shares=1000))
    assert not any("建议分批减仓" in b for b in r["blockers"])
    assert r["verdict"] == "ok"


def test_sell_all_shares_without_stop_is_conditional():
    ctx = _ctx(price=11.9)
    decision = _decision(actions=[_action("exit", "now", price=12.0, label="分批止盈", condition="涨到 12.00 元先减 1/3")])
    r = review_trade(ctx, decision, ProposedTrade("sell", 1000, 11.9), _pos(shares=1000))
    assert r["verdict"] == "conditional"
    assert any("清仓是重大决策" in b for b in r["blockers"])
    assert "清仓" in r["risk_flags"]


# ============================================================
# not_recommended 档
# ============================================================

def test_buy_blocked_action_is_not_recommended():
    ctx = _ctx(price=10.0)
    decision = _decision(
        actions=[_action("add", "blocked", price=10.0, label="补仓摊薄", condition="暂不补仓", missing=["下跌通道"])]
    )
    r = review_trade(ctx, decision, ProposedTrade("buy", 100, 10.0), _pos())
    assert r["verdict"] == "not_recommended"
    assert any("下跌通道" in b for b in r["blockers"])


def test_buy_while_signal_points_to_sell_is_not_recommended():
    ctx = _ctx(price=10.0)
    decision = _decision(actions=[_action("exit", "now", price=12.0, label="分批止盈", condition="涨到 12.00 元先减 1/3")])
    r = review_trade(ctx, decision, ProposedTrade("buy", 100, 10.0), _pos())
    assert r["verdict"] == "not_recommended"
    assert any("当前信号指向卖出" in b for b in r["blockers"])


def test_buy_below_stop_loss_is_not_recommended():
    ctx = _ctx(price=8.0)
    decision = _decision(
        actions=[_action("entry", "now", price=8.0, label="支撑企稳建仓", condition="回踩 8.00 元不破")],
        stop_loss={"price": 9.0, "basis": "参考支撑 × 0.97"},
    )
    r = review_trade(ctx, decision, ProposedTrade("buy", 100, 8.0), _pos())
    assert r["verdict"] == "not_recommended"
    assert any("不应加仓" in b for b in r["blockers"])


def test_down_channel_conflict_forces_not_recommended():
    ctx = _ctx(price=10.0)
    decision = _decision(
        actions=[_action("entry", "now", price=10.0, label="支撑企稳建仓", condition="回踩 10.00 元不破")],
        do_not=["下跌通道中不要抄底"],
    )
    r = review_trade(ctx, decision, ProposedTrade("buy", 100, 10.0), _pos())
    assert r["verdict"] == "not_recommended"


# ============================================================
# unknown 档(数据不足 → 不猜)
# ============================================================

def test_missing_p20_p80_gives_unknown():
    ctx = _ctx(price=10.0, p20=None, p80=None)
    r = review_trade(ctx, _decision(), ProposedTrade("buy", 100, 10.0), _pos())
    assert r["verdict"] == "unknown"
    assert any("P20/P80" in d for d in r["degraded"])


def test_short_klines_gives_unknown():
    ctx = _ctx(price=10.0, n=10)
    r = review_trade(ctx, _decision(), ProposedTrade("buy", 100, 10.0), _pos())
    assert r["verdict"] == "unknown"
    assert any("K 线不足" in d for d in r["degraded"])


def test_unknown_does_not_fabricate_prices():
    ctx = _ctx(price=10.0, n=10)
    r = review_trade(ctx, _decision(), ProposedTrade("buy", 100, 10.0), _pos())
    assert r["price_check"]["suggested"] is None
    assert r["t_assessment"]["t_high"] is None
    assert r["t_assessment"]["t_low"] is None


# ============================================================
# 做 T 评估
# ============================================================

def test_t_not_suitable_passes_reason_through():
    ctx = _ctx(price=10.0)
    decision = _decision(
        t_plan=_t_plan(suitable=False, t_high=None, t_low=None, unsuitable="近 5 日平均振幅 2.10% 不足 3.00%,做 T 赚不到差价")
    )
    r = review_trade(ctx, decision, ProposedTrade("sell", 100, 10.0), _pos())
    assert r["t_assessment"]["suitable"] is False
    assert "振幅" in r["t_assessment"]["note"]


def test_t_suitable_exposes_high_low_and_triggers():
    ctx = _ctx(price=10.0)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 10.0), _pos())
    t = r["t_assessment"]
    assert t["suitable"] is True
    assert t["t_high"] == 12.0
    assert t["t_low"] == 9.0
    assert "卖出 T 仓" in t["sell_trigger"]
    assert "买回" in t["buyback_trigger"]


def test_t_max_shares_derived_from_base_position():
    """1000 股 × (1 - 50%) = 500 股可动 T 仓"""
    ctx = _ctx(price=10.0)
    r = review_trade(ctx, _decision(t_plan=_t_plan(base="≥50%")), ProposedTrade("sell", 100, 10.0), _pos(shares=1000))
    assert r["t_assessment"]["max_t_shares"] == 500


def test_t_max_shares_with_bull_base_position():
    ctx = _ctx(price=10.0)
    r = review_trade(ctx, _decision(t_plan=_t_plan(base="≥70%")), ProposedTrade("sell", 100, 10.0), _pos(shares=1000))
    assert r["t_assessment"]["max_t_shares"] == 300


def test_t_sell_beyond_max_t_shares_is_flagged():
    ctx = _ctx(price=10.0)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 800, 10.0), _pos(shares=1000))
    assert "不是做 T" in r["t_assessment"]["note"]


def test_t_buy_near_low_marked_as_buyback_leg():
    ctx = _ctx(price=9.1)
    r = review_trade(ctx, _decision(), ProposedTrade("buy", 100, 9.1), _pos(shares=1000))
    assert "买回腿" in r["t_assessment"]["note"]


def test_t_sell_near_high_marked_as_sell_leg():
    ctx = _ctx(price=11.9)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 11.9), _pos(shares=1000))
    assert "卖出腿" in r["t_assessment"]["note"]


def test_t_price_in_range_flag():
    ctx = _ctx(price=10.0)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 10.0), _pos(shares=1000))
    assert r["t_assessment"]["your_price_in_range"] is True


def test_t_price_out_of_range_flag():
    ctx = _ctx(price=13.0)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 13.0), _pos(shares=1000))
    assert r["t_assessment"]["your_price_in_range"] is False


def test_sell_ignores_buy_side_do_not_rules():
    """「下跌通道中不要抄底」是买入侧规则 → 对卖出提议不构成反对理由"""
    ctx = _ctx(price=11.9)
    decision = _decision(
        actions=[_action("exit", "now", price=12.0, label="分批止盈", condition="涨到 12.00 元先减 1/3")],
        do_not=["下跌通道中不要抄底"],
    )
    r = review_trade(ctx, decision, ProposedTrade("sell", 100, 11.9), _pos(shares=1000))
    assert not any("不要抄底" in b for b in r["blockers"])
    assert r["verdict"] == "ok"


def test_sell_applies_universal_do_not_rules():
    """「K 线不足 / 指标不可靠」对买卖两个方向都成立 → 卖出也要算 blocker"""
    ctx = _ctx(price=11.9)
    decision = _decision(
        actions=[_action("exit", "now", price=12.0, label="分批止盈", condition="涨到 12.00 元先减 1/3")],
        do_not=["K 线不足 23 根,指标不可靠,先别动手"],
    )
    r = review_trade(ctx, decision, ProposedTrade("sell", 100, 11.9), _pos(shares=1000))
    assert any("K 线不足" in b for b in r["blockers"])
    assert r["verdict"] == "conditional"


def test_no_trigger_message_differs_by_side():
    ctx = _ctx(price=10.0)
    r_buy = review_trade(ctx, _decision(), ProposedTrade("buy", 100, 10.0), _pos())
    assert any("没有建仓触发条件" in b for b in r_buy["blockers"])
    r_sell = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 10.0), _pos())
    assert any("没有卖出触发条件" in b for b in r_sell["blockers"])


# ============================================================
# 交易后持仓 / 降级 / 纯函数性
# ============================================================

def test_position_after_uses_unquantized_avg_cost():
    """17021.46 / 1000 = 17.02146(不量化)→ 卖 100 @ 16.42 → 已实现 -60.15"""
    ctx = _ctx(price=16.42)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 16.42), _pos(shares=1000))
    assert r["position_after"]["shares"] == 900
    assert r["position_after"]["realized_pnl"] == "-60.15"


def test_position_after_total_cost_matches_chain():
    ctx = _ctx(price=16.42)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 16.42), _pos(shares=1000))
    # 剩余 900 股 × 17.02146 = 15319.314 → 2 位 = 15319.31
    assert r["position_after"]["total_cost"] == "15319.31"


def test_buy_position_after_average_cost():
    ctx = _ctx(price=16.0)
    r = review_trade(ctx, _decision(), ProposedTrade("buy", 100, 16.0), _pos(shares=1000))
    assert r["position_after"]["shares"] == 1100
    assert r["position_after"]["avg_cost"] == "16.929"


def test_degraded_collects_from_decision_and_local():
    ctx = _ctx(price=10.0)
    decision = _decision(degraded=["实时价不可用"], env_degraded=["市场环境不可用"])
    r = review_trade(ctx, decision, ProposedTrade("buy", 100, 10.0), _pos())
    assert "实时价不可用" in r["degraded"]
    assert "市场环境不可用" in r["degraded"]


def test_review_is_pure_same_input_same_output():
    ctx = _ctx(price=10.0)
    decision = _decision()
    proposed = ProposedTrade("sell", 100, 10.0)
    a = review_trade(ctx, decision, proposed, _pos(shares=1000))
    b = review_trade(ctx, decision, proposed, _pos(shares=1000))
    assert a == b


def test_review_does_not_mutate_decision():
    ctx = _ctx(price=10.0)
    decision = _decision(actions=[_action("exit", "now", price=12.0)])
    before = repr(decision)
    review_trade(ctx, decision, ProposedTrade("sell", 100, 10.0), _pos(shares=1000))
    assert repr(decision) == before


def test_sell_more_than_position_is_degraded_not_raised():
    """卖出超过持仓:纯函数不抛异常,降级标注"""
    ctx = _ctx(price=16.0)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 5000, 16.0), _pos(shares=1000))
    assert any("试算失败" in d for d in r["degraded"])


# ============================================================
# 做 T 方向判定(正T / 反T)
#
# 术语(判定层写死):
#   反T(reverse) = 先卖后买(高抛低吸),持股数不变
#   正T(forward) = 先买后卖(低吸高抛),要占用买入资金
# ============================================================

def _dirs(
    *,
    price: float = 10.0,
    p80: float = 12.0,
    t_plan: dict | None = None,
    action: str = "sell",
    shares: int = 100,
    tx_price: float = 10.0,
    pos_shares: int = 1000,
    cash: Decimal | None = None,
    t0: bool = False,
    code: str = "002185.SZ",
) -> dict:
    """跑一次判定,只取 t_directions"""
    ctx = _ctx(price=price, p80=p80, code=code, t0=t0)
    decision = _decision(t_plan=t_plan)
    r = review_trade(
        ctx,
        decision,
        ProposedTrade(action, shares, tx_price),
        _pos(shares=pos_shares),
        cash,
    )
    return r["t_directions"]


def test_t_directions_both_shown_even_when_not_applicable():
    """不适用的一方也要显示(灰显 + 说明原因),不能藏起来"""
    d = _dirs(t_plan=_t_plan(suitable=False, unsuitable="单边下跌,做 T 越做越低"))
    assert d["reverse"]["applicable"] is False
    assert d["forward"]["applicable"] is False
    assert "单边下跌" in d["reverse"]["status_text"]
    assert "单边下跌" in d["forward"]["status_text"]
    assert d["reverse"]["steps"] == []
    assert d["forward"]["steps"] == []


def test_reverse_max_shares_from_movable_base():
    """可动 T 仓 = floor(持股 × (1 - 底仓比例)),并向下取整到整手"""
    # 1000 股,底仓 ≥50% → 可动 500 股
    d = _dirs(pos_shares=1000, cash=Decimal("100000"))
    assert d["reverse"]["applicable"] is True
    assert d["reverse"]["max_shares"] == 500


def test_reverse_max_shares_rounds_down_to_lot():
    """零股无法下单 → 向下取整到 100 的倍数"""
    # 250 股,底仓 ≥50% → 可动 125 → 整手 100
    d = _dirs(pos_shares=250, cash=Decimal("100000"))
    assert d["reverse"]["max_shares"] == 100


def test_reverse_needs_no_cash():
    """反T 卖出所得即可覆盖买回 → 没填资金也适用"""
    d = _dirs(cash=None)
    assert d["reverse"]["applicable"] is True
    assert d["reverse"]["max_shares"] == 500


def test_forward_not_applicable_without_cash():
    """正T 必须占用买入资金 → 没填资金 → 不可用,且股数给 None(不猜)"""
    d = _dirs(cash=None)
    assert d["forward"]["applicable"] is False
    assert d["forward"]["max_shares"] is None
    assert "未填写账户可用资金" in d["forward"]["prerequisite"]


def test_forward_max_shares_limited_by_cash():
    """正T 股数 = min(可动 T 仓, 资金能买的股数)"""
    # 可动 500 股;资金 10000 元 / 买价 10 元 = 1000 股 → 取小者 500
    d = _dirs(cash=Decimal("10000"), action="buy", tx_price=10.0)
    assert d["forward"]["applicable"] is True
    assert d["forward"]["max_shares"] == 500

    # 资金只够 200 股 → 以资金为准
    d2 = _dirs(cash=Decimal("2000"), action="buy", tx_price=10.0)
    assert d2["forward"]["max_shares"] == 200


def test_forward_amount_is_cash_needed():
    """正T 的金额 = 股数 × 买价"""
    d = _dirs(cash=Decimal("5000"), action="buy", tx_price=10.0)
    assert d["forward"]["max_shares"] == 500
    assert d["forward"]["max_amount"] == "5000.00"


def test_forward_not_applicable_when_cash_below_one_lot():
    """资金不够买 1 手 → 正T 不可用"""
    d = _dirs(cash=Decimal("50"), action="buy", tx_price=10.0)
    assert d["forward"]["applicable"] is False
    assert "不足" in d["forward"]["prerequisite"] or "1 手" in d["forward"]["prerequisite"]


def test_forward_uses_t_low_when_user_is_selling():
    """用户拟卖时,正T 的买入参考价取 T 区间下沿(计划低吸位)"""
    d = _dirs(cash=Decimal("100000"), action="sell", tx_price=10.0)
    # t_low = 9.0 → 100000 / 9 = 11111 股 → 取可动 500
    assert d["forward"]["max_shares"] == 500
    assert "9.00" in d["forward"]["steps"][0]["text"]


def test_recommend_reverse_when_price_above_p80():
    """现价高于 P80 → 强制反T"""
    d = _dirs(price=13.0, p80=12.0, cash=Decimal("100000"))
    assert d["recommended"] == "reverse"
    assert "P80" in d["recommend_reason"]


def test_recommend_reverse_when_price_above_t_high():
    d = _dirs(price=12.5, p80=13.0, cash=Decimal("100000"))
    assert d["recommended"] == "reverse"


def test_recommend_forward_when_price_below_t_low():
    """现价到区间下沿 → 先买后卖更占优"""
    d = _dirs(price=8.5, p80=12.0, cash=Decimal("100000"))
    assert d["recommended"] == "forward"


def test_recommend_by_position_ratio_in_range():
    """区间内:位置 ≥50% → 反T;<50% → 正T"""
    # t_low=9, t_high=12;10.5 → (10.5-9)/3 = 50% → 反T
    d = _dirs(price=10.5, p80=12.0, cash=Decimal("100000"))
    assert d["recommended"] == "reverse"

    # 9.8 → 26.7% → 正T
    d2 = _dirs(price=9.8, p80=12.0, cash=Decimal("100000"))
    assert d2["recommended"] == "forward"


def test_recommend_only_available_direction():
    """只有一方可用 → 推荐那一方"""
    # 没填资金 → 只有反T 可用
    d = _dirs(cash=None, price=9.8)
    assert d["recommended"] == "reverse"
    assert "正T 当前不可用" in d["recommend_reason"]


def test_no_recommendation_when_neither_applicable():
    d = _dirs(t_plan=_t_plan(suitable=False, unsuitable="当前不适合做 T"))
    assert d["recommended"] is None
    assert d["your_leg"] is None


def test_your_leg_sell_maps_to_reverse_sell():
    d = _dirs(action="sell", price=13.0, p80=12.0, cash=Decimal("100000"))
    assert d["recommended"] == "reverse"
    assert d["your_leg"] == "reverse.sell"


def test_your_leg_buy_maps_to_reverse_buyback():
    """用户拟买 + 推荐反T → 这笔是「买回腿」"""
    d = _dirs(action="buy", price=13.0, p80=12.0, cash=Decimal("100000"))
    assert d["recommended"] == "reverse"
    assert d["your_leg"] == "reverse.buyback"


def test_your_leg_buy_maps_to_forward_buy():
    """用户拟买 + 推荐正T → 这笔是「买入腿」"""
    d = _dirs(action="buy", price=8.5, p80=12.0, cash=Decimal("100000"))
    assert d["recommended"] == "forward"
    assert d["your_leg"] == "forward.buy"


def test_your_leg_sell_maps_to_forward_sell():
    """用户拟卖 + 推荐正T → 这笔是「卖出腿」"""
    d = _dirs(action="sell", price=8.5, p80=12.0, cash=Decimal("100000"))
    assert d["recommended"] == "forward"
    assert d["your_leg"] == "forward.sell"


def test_t_plus_1_note_present():
    d = _dirs(cash=Decimal("100000"))
    assert "T+1" in d["t_plus_one_note"]


def test_t_directions_present_in_unknown_verdict():
    """数据不足 → unknown,但两个方向仍照常显示(灰显)"""
    ctx = _ctx(price=10.0, p20=None)
    r = review_trade(ctx, _decision(), ProposedTrade("buy", 100, 10.0), _pos())
    assert r["verdict"] == "unknown"
    assert r["t_directions"]["reverse"]["applicable"] is False
    assert r["t_directions"]["forward"]["applicable"] is False


def test_t_directions_degraded_mentions_cash():
    """没填资金 → degraded 里如实说明"""
    ctx = _ctx(price=10.0)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 10.0), _pos(), None)
    assert any("可用资金" in d for d in r["degraded"])


def test_t_directions_is_pure_same_input_same_output():
    """纯函数:同样输入永远同样输出"""
    ctx = _ctx(price=10.5)
    decision = _decision()
    a = review_trade(ctx, decision, ProposedTrade("sell", 100, 10.0), _pos(), Decimal("50000"))
    b = review_trade(ctx, decision, ProposedTrade("sell", 100, 10.0), _pos(), Decimal("50000"))
    assert a["t_directions"] == b["t_directions"]


def test_no_position_makes_both_directions_unavailable():
    """空仓 → 两个方向都不可用(做 T 前需先建仓)"""
    d = _dirs(pos_shares=0, cash=Decimal("100000"))
    assert d["reverse"]["applicable"] is False
    assert d["forward"]["applicable"] is False
    assert "底仓" in d["reverse"]["prerequisite"]


def test_reason_code_distinguishes_missing_cash_from_not_applicable():
    """前端靠 reason_code 区分「缺资金(可补)」与「真不适用」"""
    d = _dirs(cash=None)
    assert d["forward"]["reason_code"] == "no_cash"
    assert d["reverse"]["reason_code"] == "ok"

    d2 = _dirs(t_plan=_t_plan(suitable=False, unsuitable="当前不适合做 T"))
    assert d2["forward"]["reason_code"] == "not_suitable"
    assert d2["reverse"]["reason_code"] == "not_suitable"


def test_reason_code_cash_too_little():
    d = _dirs(cash=Decimal("50"), action="buy", tx_price=10.0)
    assert d["forward"]["reason_code"] == "cash_too_little"


def test_reason_code_no_position():
    d = _dirs(pos_shares=0, cash=Decimal("100000"))
    assert d["reverse"]["reason_code"] == "no_position"


def test_movable_base_uses_decimal_no_float_error():
    """999 股 × 30% = 299.7 → 整手 200 股(浮点会算成 299 → 200,这里锁住边界)"""
    # 底仓 ≥70% → 可动 30%
    d = _dirs(pos_shares=999, cash=Decimal("100000"), t_plan=_t_plan(base="≥70%"))
    assert d["reverse"]["max_shares"] == 200


# ============================================================
# T+0 品种(跨境/黄金/商品 ETF):正T 不需要预留老底仓
#
# 差别只在正T 的卖腿来源:
#   T+1 → 卖腿只能用预留老底仓 → 上限 = min(可动T仓, 资金÷买价)
#   T+0 → 当天买入的份额当天就能卖 → 上限 = 资金÷买价(不受可动T仓约束)
# ============================================================


def test_t1_forward_upper_bound_is_min_of_base_and_cash():
    """T+1:正T 上限 = min(可动 T 仓, 资金÷买价) —— 1000 股 × 50% = 500"""
    d = _dirs(pos_shares=1000, cash=Decimal("20000"))  # 买价 9 → 资金能买 2200
    assert d["forward"]["max_shares"] == 500
    assert "老底仓" in d["forward"]["prerequisite"]


def test_t0_forward_upper_bound_is_cash_only():
    """T+0:正T 上限只受资金约束(2200 股),不再被可动 T 仓 500 股砍掉"""
    d = _dirs(pos_shares=1000, cash=Decimal("20000"), t0=True)
    assert d["forward"]["max_shares"] == 2200
    assert d["forward"]["applicable"] is True


def test_t0_forward_prerequisite_does_not_require_base_position():
    """T+0:前提不再要求「老底仓承接卖腿」"""
    d = _dirs(pos_shares=1000, cash=Decimal("20000"), t0=True)
    pre = d["forward"]["prerequisite"]
    assert "承接卖腿" not in pre
    assert "无需预留老底仓" in pre
    assert "T+0" in pre


def test_t0_forward_sell_leg_is_same_day_shares():
    """T+0:卖腿写「卖出当日买入的份额」,不是「卖出老底仓」"""
    d = _dirs(pos_shares=1000, cash=Decimal("20000"), t0=True)
    sell_text = " ".join(s["text"] for s in d["forward"]["steps"])
    assert "当日买入" in sell_text
    assert "老底仓" not in sell_text


def test_t0_note_replaces_t_plus_one_note():
    """T+0 品种的提示不能说「当天不能卖出」"""
    d = _dirs(pos_shares=1000, cash=Decimal("20000"), t0=True)
    note = d["t_plus_one_note"]
    assert "T+0" in note
    assert "当天不能卖出" not in note


def test_t1_note_still_says_a_share_t_plus_one():
    """T+1 品种(股票/境内股票ETF)提示不变"""
    d = _dirs(pos_shares=1000, cash=Decimal("20000"))
    assert "T+1" in d["t_plus_one_note"]
    assert "当天不能卖出" in d["t_plus_one_note"]


def test_t0_reverse_still_limited_by_movable_base():
    """T+0 反T 仍受可动 T 仓约束(不能把仓位卖光)"""
    d = _dirs(pos_shares=1000, cash=Decimal("20000"), t0=True)
    assert d["reverse"]["max_shares"] == 500


def test_t0_forward_survives_missing_base_ratio():
    """缺底仓比例时:T+1 正T 卡住(卖腿没底仓可用),T+0 正T 仍可算(只受资金)"""
    plan_no_base = _t_plan(base="")
    t1 = _dirs(pos_shares=1000, cash=Decimal("20000"), t_plan=plan_no_base)
    assert t1["forward"]["applicable"] is False
    assert t1["forward"]["reason_code"] == "no_base_ratio"

    t0 = _dirs(pos_shares=1000, cash=Decimal("20000"), t_plan=plan_no_base, t0=True)
    assert t0["forward"]["applicable"] is True
    assert t0["forward"]["max_shares"] == 2200


def test_t0_forward_without_cash_still_reports_no_cash():
    """T+0 也要钱:没填资金 → 仍然 no_cash(不给数字)"""
    d = _dirs(pos_shares=1000, cash=None, t0=True)
    assert d["forward"]["reason_code"] == "no_cash"
    assert d["forward"]["max_shares"] is None


def test_unknown_etf_is_degraded_not_silent():
    """表外 ETF → degraded 明说「未在品种表内」(不能假装已知)"""
    d = _dirs(pos_shares=1000, cash=Decimal("20000"), code="510999.SH")
    assert d["reverse"]["max_shares"] == 500  # 保守按 T+1


def test_unknown_etf_degraded_note_present():
    ctx = _ctx(price=10.0, code="510999.SH")
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 10.0), _pos(), Decimal("20000"))
    assert any("未在品种表内" in d for d in r["degraded"])


def test_known_etf_has_no_degraded_note():
    """表内 ETF 不写降级说明(品种信息是已知的)"""
    ctx = _ctx(price=10.0, code="513100.SH", t0=True)
    r = review_trade(ctx, _decision(), ProposedTrade("sell", 100, 10.0), _pos(), Decimal("20000"))
    assert not any("未在品种表内" in d for d in r["degraded"])
