"""网格交易配置建议单测(judge_grid_plan,设计文档 §6.9)

网格是长期挂单式策略,与手动做 T 互为替代。这套判据必须逐条锁死:
方向 / 振幅 / 区间宽度 / 区间位置 / 底仓 / 费用 / 资金 / 集中度。

零编造不变量:不适用的网格,配置类字段一律 None(不给"半截配置")。
"""
from dataclasses import replace
from decimal import Decimal

import pytest

from app.core.cost_engine import TradeFees
from app.services.decision_service import (
    DecisionContext,
    GRID_LOT_SIZE,
    judge_grid_plan,
)

# 默认费率档(费用设置未启用时的估算口径)
BASE_FEES = TradeFees(enabled=True)
ETF_FEES = TradeFees.etf_variant(BASE_FEES)


def _zig_klines(n: int = 40, base: float = 25.0, amp: float = 0.05) -> list[dict]:
    """合成锯齿 K 线:相邻两根一高一低,单边日振幅 ≈ amp*2"""
    out = []
    for i in range(n):
        close = base if i % 2 == 0 else base * (1 + amp)
        out.append({
            "date": f"2026-01-{i + 1:02d}",
            "open": close,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": 100000,
        })
    return out


def _ind(channel: str = "sideways", p20: float = 23.0, p80: float = 27.0) -> dict:
    return {
        "channel": {"state": channel},
        "position": {
            "p20": p20,
            "p80": p80,
            "support_price": 23.5,
            "stop_loss_price": 22.8,
            "risk_band": "mid",
        },
        "ma": {"ma5": 25.0, "ma10": 25.1, "ma20": 25.2, "ma60": 25.3},
        "signal": {"score": 50, "confidence": "medium"},
        "data_quality": {"kline_count": 60},
    }


def _ctx(
    channel: str = "sideways",
    price: float = 25.0,
    shares: int = 1000,
    cash: float | None = 20000.0,
    fees: TradeFees | None = BASE_FEES,
    klines: list[dict] | None = None,
    p20: float | None = None,
    p80: float | None = None,
    share_pct: float | None = None,
    base: float = 25.0,
    amp: float = 0.05,
) -> DecisionContext:
    return DecisionContext(
        stock_code="000807.SZ",
        stock_name="云铝股份",
        indicators=_ind(
            channel,
            p20 if p20 is not None else base * 0.92,
            p80 if p80 is not None else base * 1.08,
        ),
        klines=klines if klines is not None else _zig_klines(base=base, amp=amp),
        current_price=price,
        prev_close=price,
        cost_basis=price,
        shares=shares,
        position_status="profit",
        fees=fees,
        cash_available=cash,
        position_share_pct=share_pct,
    )


# ---------------------------------------------------------------- 适用场景

def test_grid_suitable_in_oscillation_with_position():
    grid = judge_grid_plan(_ctx())
    assert grid["suitable"] is True
    assert grid["mode"] == "add"
    assert grid["grids"] and grid["grids"] >= 1
    assert grid["range_low"] < grid["range_high"]
    assert grid["unsuitable_signals"] == ""


def test_grid_money_and_profit_are_two_different_numbers():
    """一手金额 ≠ 每格利润(把两者混算会让资金需求与净收益同时算错)"""
    grid = judge_grid_plan(_ctx(price=25.0))
    assert grid["capital_per_grid"] == pytest.approx(2500.0)          # 100 股 × 25 元
    assert grid["net_profit_per_grid"] > 0
    # 毛收益 = 100 股 × 0.5 元价差 = 50 元;扣约 10 元佣金后仍为正
    assert grid["net_profit_per_grid"] < 50.0
    assert grid["cash_needed"] > grid["capital_per_grid"]


# ---------------------------------------------------------------- G0 前置数据

def test_grid_requires_enough_klines():
    grid = judge_grid_plan(_ctx(klines=_zig_klines(n=10)))
    assert grid["suitable"] is False
    assert "K 线不足" in grid["unsuitable_signals"]


def test_grid_requires_price():
    ctx = _ctx()
    broken = DecisionContext(
        stock_code=ctx.stock_code, stock_name=ctx.stock_name,
        indicators=ctx.indicators, klines=ctx.klines,
        current_price=None, prev_close=None,
        cost_basis=None, shares=ctx.shares, position_status="empty",
    )
    grid = judge_grid_plan(broken)
    assert grid["suitable"] is False
    assert "K 线不足" in grid["unsuitable_signals"]


# ---------------------------------------------------------------- G1 方向

def test_grid_rejected_in_down_channel():
    grid = judge_grid_plan(_ctx(channel="down"))
    assert grid["suitable"] is False
    assert "下跌通道" in grid["unsuitable_signals"]
    assert "越买越套" in grid["unsuitable_signals"]


def test_grid_rejected_in_up_channel():
    grid = judge_grid_plan(_ctx(channel="up"))
    assert grid["suitable"] is False
    assert "上涨通道" in grid["unsuitable_signals"]
    assert "卖飞" in grid["unsuitable_signals"]


# ---------------------------------------------------------------- G2 振幅

def test_grid_rejected_when_amplitude_too_small():
    """平盘 K 线:日振幅趋近 0 → 抓不到差价"""
    flat = []
    for i in range(40):
        flat.append({
            "date": f"2026-01-{i + 1:02d}",
            "open": 25.0, "high": 25.05, "low": 24.95,
            "close": 25.0, "volume": 100000,
        })
    grid = judge_grid_plan(_ctx(klines=flat))
    assert grid["suitable"] is False
    assert "振幅" in grid["unsuitable_signals"]


# ---------------------------------------------------------------- G3 区间宽度

def test_grid_rejected_when_span_too_narrow():
    grid = judge_grid_plan(_ctx(p20=24.8, p80=25.2))
    assert grid["suitable"] is False
    assert "区间宽度" in grid["unsuitable_signals"]


# ---------------------------------------------------------------- G4 区间位置

def test_grid_rejected_when_price_below_range_low():
    grid = judge_grid_plan(_ctx(price=23.0))
    assert grid["suitable"] is False
    assert "跌破网格下沿" in grid["unsuitable_signals"]
    assert "接飞刀" in grid["unsuitable_signals"]


def test_grid_rejected_when_price_above_range_high():
    grid = judge_grid_plan(_ctx(price=28.0))
    assert grid["suitable"] is False
    assert "突破网格上沿" in grid["unsuitable_signals"]


# ---------------------------------------------------------------- G5 底仓

def test_grid_rejected_without_base_position():
    grid = judge_grid_plan(_ctx(shares=0))
    assert grid["suitable"] is False
    assert "底仓" in grid["unsuitable_signals"]


def test_grid_rejected_when_position_below_one_lot():
    grid = judge_grid_plan(_ctx(shares=GRID_LOT_SIZE - 1))
    assert grid["suitable"] is False
    assert "底仓" in grid["unsuitable_signals"]


# ---------------------------------------------------------------- G6 费用

def test_grid_rejected_when_min_commission_eats_profit():
    """低价股:每格毛收益 4.48 元 < 手续费 10 元 → 网格不划算"""
    grid = judge_grid_plan(_ctx(base=2.24, amp=0.08, price=2.24, shares=300))
    assert grid["suitable"] is False
    assert "毛收益" in grid["unsuitable_signals"]
    assert "手续费" in grid["unsuitable_signals"]


def test_grid_fee_basis_default_estimate_when_fees_disabled():
    """费用设置未启用 → 按费率档估算,并标注 fee_basis"""
    disabled = TradeFees(enabled=False)
    grid = judge_grid_plan(_ctx(fees=disabled))
    assert grid["suitable"] is True
    assert grid["fee_basis"] == "default_estimate"
    assert grid["roundtrip_fee_pct"] == pytest.approx(0.102, abs=0.001)


def test_grid_fee_basis_configured_when_enabled():
    grid = judge_grid_plan(_ctx(fees=BASE_FEES))
    assert grid["fee_basis"] == "configured"


def test_etf_grid_has_lower_roundtrip_fee():
    """ETF 免印花税 → 往返费率更低 → 单格净收益更高"""
    stock_grid = judge_grid_plan(_ctx(fees=BASE_FEES))
    etf_ctx = replace(_ctx(fees=ETF_FEES), instrument_kind="etf")
    etf_grid = judge_grid_plan(etf_ctx)
    assert stock_grid["roundtrip_fee_pct"] == pytest.approx(0.102, abs=0.001)
    assert etf_grid["roundtrip_fee_pct"] == pytest.approx(0.05, abs=0.001)
    assert etf_grid["net_profit_per_grid"] > stock_grid["net_profit_per_grid"]


def test_grid_fee_fields_none_when_fees_unavailable():
    grid = judge_grid_plan(_ctx(fees=None))
    # 费用不可得 → 不编数字,但结构仍可给
    assert grid["roundtrip_fee_pct"] is None
    assert grid["net_profit_per_grid"] is None
    assert grid["fee_basis"] is None


# ---------------------------------------------------------------- G7 资金

def test_grid_downgrades_to_base_mode_when_cash_insufficient():
    grid = judge_grid_plan(_ctx(cash=374.63))
    assert grid["suitable"] is True
    assert grid["mode"] == "base"
    assert "现金不足" in grid["reason"]
    assert "底仓高抛低吸" in grid["reason"]


def test_grid_cash_unknown_falls_back_to_base_mode():
    grid = judge_grid_plan(_ctx(cash=None))
    assert grid["suitable"] is True
    assert grid["mode"] == "base"
    assert "未填写" in grid["reason"]


# ---------------------------------------------------------------- G8 集中度

def test_grid_forbids_add_mode_when_concentration_too_high():
    grid = judge_grid_plan(_ctx(cash=20000.0, share_pct=55.0))
    assert grid["suitable"] is True
    assert grid["mode"] == "base"
    assert "单一暴露" in grid["reason"]


def test_grid_allows_add_mode_when_concentration_low():
    grid = judge_grid_plan(_ctx(cash=20000.0, share_pct=10.0))
    assert grid["mode"] == "add"


# ---------------------------------------------------------------- 互斥与风险

def test_grid_replace_t_plan_flag_and_reason():
    t_plan = {"suitable": True}
    grid = judge_grid_plan(_ctx(), t_plan)
    assert grid["replace_t_plan"] is True
    assert "互斥" in grid["reason"]

    grid2 = judge_grid_plan(_ctx(), {"suitable": False})
    assert grid2["replace_t_plan"] is False
    assert "手动做 T 条件不满足" in grid2["reason"]


def test_grid_risk_states_failure_conditions():
    grid = judge_grid_plan(_ctx())
    assert "跌破" in grid["risk"]
    assert "资金耗尽" in grid["risk"]


def test_grid_never_promises_return():
    """网格建议不得出现收益承诺用语(设计文档 §10.4 口径)"""
    grid = judge_grid_plan(_ctx())
    text = f"{grid['reason']}{grid['risk']}"
    for word in ("预计赚", "收益率", "稳赚", "必赚"):
        assert word not in text


# ---------------------------------------------------------------- 零编造不变量

def test_unsuitable_grid_has_no_partial_configuration():
    grid = judge_grid_plan(_ctx(channel="down"))
    assert grid["suitable"] is False
    for key in (
        "grids", "step_pct", "step_price", "shares_per_grid",
        "capital_per_grid", "cash_needed", "net_profit_per_grid",
        "net_step_pct", "range_low", "range_high", "span_pct",
    ):
        assert grid[key] is None, f"{key} 不该出现在不适用的网格里"


def test_grid_amounts_are_numbers_not_strings():
    grid = judge_grid_plan(_ctx())
    assert isinstance(grid["capital_per_grid"], float)
    assert isinstance(grid["net_profit_per_grid"], float)
    assert isinstance(grid["grids"], int)


def test_trade_fees_variant_is_etf_without_stamp_tax():
    """ETF 变体:印花税与过户费为 0"""
    etf = TradeFees.etf_variant(BASE_FEES)
    assert etf.stamp_tax_rate == Decimal("0")
    assert etf.transfer_fee_rate == Decimal("0")
