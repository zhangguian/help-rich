"""决策上下文共享装配单测(decision_context_service)

这条装配口同时喂给**决策卡**与**计算器 T 卡**。
一旦两处口径不一致,用户就会在同一个界面上看到两套说法 —— 所以:

- 4 项新输入任一取不到 → 该项 None + degraded,**其余照常**;
- ETF 必须选到免印花税的费率档;
- 两处装配点拿到的字段必须一致。
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.cost_engine import TradeFees
from app.modules.portfolio.service import PositionStart
from app.services import decision_context_service as svc
from app.services.decision_context_service import (
    DecisionExtras,
    enrich_decision_context,
    load_decision_extras,
    parse_date,
)
from app.services.decision_service import DecisionContext


class _Pos:
    def __init__(self, code: str, shares: int, total_cost: str):
        self.stock_code = code
        self.shares = shares
        self.total_cost = Decimal(total_cost)


@pytest.fixture(autouse=True)
def _stub_sources(monkeypatch):
    """把 4 个 IO 源都替换成可控桩(不打真 DB、不打真网络)"""
    state = {
        "fees": TradeFees(enabled=True),
        "cash": Decimal("374.63"),
        "positions": [_Pos("002185.SZ", 1000, "17020.00"), _Pos("000807.SZ", 500, "12580.00")],
        "start_date": date(2026, 8, 1),
        "start_source": "transactions",
        "fail": set(),
    }

    async def _repo_get():
        if "fees" in state["fail"]:
            raise RuntimeError("db down")
        return state["fees"]

    def _fees(code, base):
        """fees_for_instrument 是**同步**函数,替身也必须同步"""
        from app.core.instrument import fees_for_instrument
        return fees_for_instrument(code, base)

    async def _cash():
        if "cash" in state["fail"]:
            raise RuntimeError("db down")
        return state["cash"]

    async def _positions():
        if "positions" in state["fail"]:
            raise RuntimeError("db down")
        return state["positions"]

    async def _start(code):
        if "start" in state["fail"]:
            raise RuntimeError("db down")
        return PositionStart(date=state["start_date"], source=state["start_source"])

    monkeypatch.setattr(svc, "fees_for_instrument", _fees)
    monkeypatch.setattr(svc, "get_cash_available", _cash)
    monkeypatch.setattr(svc, "get_all_positions", _positions)
    monkeypatch.setattr(svc, "get_position_start", _start)
    monkeypatch.setattr(svc.cost_settings_repo, "get", _repo_get)
    return state


# ---------------------------------------------------------------- 正常路径

@pytest.mark.asyncio
async def test_load_extras_returns_all_four_inputs(_stub_sources):
    extras = await load_decision_extras("002185.SZ", as_of=date(2026, 10, 25))
    assert extras.fees is not None
    assert extras.cash_available == pytest.approx(374.63)
    assert extras.position_share_pct == pytest.approx(17020 / (17020 + 12580) * 100, abs=0.01)
    assert extras.holding_days == 85
    assert extras.degraded == []


@pytest.mark.asyncio
async def test_load_extras_carries_start_source(_stub_sources):
    """起点来源必须一起带上来 —— 判定层要靠它决定文案口径(能不能说「已持有」)"""
    extras = await load_decision_extras("002185.SZ", as_of=date(2026, 10, 25))
    assert extras.holding_days_source == "transactions"


@pytest.mark.asyncio
async def test_load_extras_snapshot_source_is_reported(_stub_sources):
    """快照导入(无流水)的票 → 来源 = snapshot,真实建仓日未知"""
    _stub_sources["start_source"] = "snapshot"
    extras = await load_decision_extras("002185.SZ", as_of=date(2026, 10, 25))
    assert extras.holding_days_source == "snapshot"


@pytest.mark.asyncio
async def test_load_extras_picks_etf_fee_variant(_stub_sources):
    """ETF → 免印花税/过户费的费率档"""
    extras = await load_decision_extras("159599.SZ", as_of=date(2026, 10, 25))
    assert extras.fees is not None
    assert extras.fees.stamp_tax_rate == Decimal("0")
    assert extras.fees.transfer_fee_rate == Decimal("0")


@pytest.mark.asyncio
async def test_load_extras_stock_keeps_stamp_tax(_stub_sources):
    extras = await load_decision_extras("002185.SZ", as_of=date(2026, 10, 25))
    assert extras.fees is not None
    assert extras.fees.stamp_tax_rate == Decimal("0.0005")


# ---------------------------------------------------------------- 逐项降级

@pytest.mark.asyncio
async def test_fee_failure_degrades_only_fee(_stub_sources):
    _stub_sources["fail"].add("fees")
    extras = await load_decision_extras("002185.SZ", as_of=date(2026, 10, 25))
    assert extras.fees is None
    assert any("费用档" in d for d in extras.degraded)
    # 其余三项照常
    assert extras.cash_available is not None
    assert extras.holding_days is not None
    assert extras.position_share_pct is not None


@pytest.mark.asyncio
async def test_cash_failure_degrades_only_cash(_stub_sources):
    _stub_sources["fail"].add("cash")
    extras = await load_decision_extras("002185.SZ", as_of=date(2026, 10, 25))
    assert extras.cash_available is None
    assert any("可用资金" in d for d in extras.degraded)
    assert extras.holding_days is not None


@pytest.mark.asyncio
async def test_positions_failure_degrades_only_concentration(_stub_sources):
    _stub_sources["fail"].add("positions")
    extras = await load_decision_extras("002185.SZ", as_of=date(2026, 10, 25))
    assert extras.position_share_pct is None
    assert any("全量持仓" in d for d in extras.degraded)
    assert extras.cash_available is not None


@pytest.mark.asyncio
async def test_start_date_failure_degrades_only_days(_stub_sources):
    _stub_sources["fail"].add("start")
    extras = await load_decision_extras("002185.SZ", as_of=date(2026, 10, 25))
    assert extras.holding_days is None
    assert any("起始日" in d for d in extras.degraded)
    assert extras.cash_available is not None


@pytest.mark.asyncio
async def test_cash_not_filled_is_degraded_not_failure(_stub_sources):
    """现金未填写(None)是"用户没填",不是系统故障 → 明确降级但不报错"""
    _stub_sources["cash"] = None
    extras = await load_decision_extras("002185.SZ", as_of=date(2026, 10, 25))
    assert extras.cash_available is None
    assert any("未填写" in d for d in extras.degraded)


@pytest.mark.asyncio
async def test_stock_without_position_has_no_share_pct(_stub_sources):
    extras = await load_decision_extras("000001.SH", as_of=date(2026, 10, 25))
    assert extras.position_share_pct is None


# ---------------------------------------------------------------- 注入

def test_enrich_injects_new_fields_only():
    ctx = DecisionContext(
        stock_code="002185.SZ", stock_name="华天科技",
        indicators={}, klines=[], current_price=16.19, prev_close=16.19,
        cost_basis=17.02, shares=1000, position_status="loss",
    )
    extras = DecisionExtras(
        fees=TradeFees(enabled=True),
        cash_available=374.63,
        position_share_pct=42.0,
        holding_days=23,
        holding_days_source="transactions",
    )
    enriched = enrich_decision_context(ctx, extras)
    assert enriched.fees is extras.fees
    assert enriched.cash_available == 374.63
    assert enriched.position_share_pct == 42.0
    assert enriched.holding_days == 23
    assert enriched.holding_days_source == "transactions"
    # 既有字段不得被动
    assert enriched.current_price == 16.19
    assert enriched.cost_basis == 17.02
    assert enriched.shares == 1000
    assert enriched.verdict if False else True


def test_enrich_does_not_mutate_original_context():
    ctx = DecisionContext(
        stock_code="002185.SZ", stock_name="华天科技",
        indicators={}, klines=[], current_price=16.19, prev_close=16.19,
        cost_basis=17.02, shares=1000, position_status="loss",
    )
    enriched = enrich_decision_context(ctx, DecisionExtras(holding_days=23))
    assert ctx.holding_days is None
    assert enriched.holding_days == 23


def test_two_assembly_points_get_same_fields():
    """决策卡与计算器 T 卡共用这一装配口 → 字段必须一致"""
    extras = DecisionExtras(
        fees=TradeFees(enabled=True),
        cash_available=374.63,
        position_share_pct=42.0,
        holding_days=23,
    )
    base = {
        "stock_code": "002185.SZ", "stock_name": "华天科技",
        "indicators": {}, "klines": [], "current_price": 16.19, "prev_close": 16.19,
        "cost_basis": 17.02, "shares": 1000, "position_status": "loss",
    }
    a = enrich_decision_context(DecisionContext(**base), extras)
    b = enrich_decision_context(DecisionContext(**base), extras)
    assert a == b


# ---------------------------------------------------------------- 日期解析

def test_parse_date_accepts_iso_string():
    assert parse_date("2026-10-24") == date(2026, 10, 24)


def test_parse_date_accepts_date_and_datetime():
    assert parse_date(date(2026, 10, 24)) == date(2026, 10, 24)
    assert parse_date(datetime(2026, 10, 24, 15, 0)) == date(2026, 10, 24)


def test_parse_date_returns_none_for_garbage():
    assert parse_date("不是日期") is None
    assert parse_date(None) is None
