"""回测闸门脚本自身正确性(小样本 sanity)

覆盖:
- evaluate_gates 的 7 条闸门判定(样本池 3 条 + 效果 4 条)
- _forward_return 的口径:买入价 = **次日开盘价**、持有期、胜的定义、数据不足返回 None
- run_backtest 的三种持仓上下文分派 + **无前视偏差**(信号日只喂 klines[: i+1])
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services import decision_backtest as bt
from app.services.decision_backtest import _forward_return, evaluate_gates, run_backtest


# ---------------------------------------------------------------- 闸门判定

def test_evaluate_gates_fails_when_samples_insufficient():
    """样本池不足 → 闸门不通过(样本池 3 条:股票数 / 窗口 / 有效信号数)"""
    report = {
        "samples": 3, "codes": 1, "days": 10,
        "entry": {"win_rate": 0.9, "avg_return": 0.2, "baseline_avg_return": 0.01},
        "exit": {"avg_drawdown": -0.06, "baseline_avg_drawdown": -0.02},
        "stop": {"avg_drawdown": -0.04, "baseline_avg_drawdown": -0.01},
    }
    ok, gates = evaluate_gates(report)
    assert ok is False
    failed = {g["name"] for g in gates if not g["passed"]}
    assert "样本池股票数" in failed
    assert "样本池回测窗口" in failed
    assert "有效 entry 信号数" in failed
    # 效果类闸门在效果达标时不应误判为不通过
    assert "entry 后 10 日胜率" not in failed
    assert "entry 超额收益" not in failed
    assert "exit 后 10 日回撤改善" not in failed
    assert "stop 后 5 日回撤改善" not in failed


def test_evaluate_gates_passes_when_all_gates_met():
    """7 条闸门全部达标 → 通过"""
    report = {
        "samples": 5000, "codes": 40, "days": 120,
        "entry": {"win_rate": 0.56, "avg_return": 0.031, "baseline_avg_return": 0.011},
        "exit": {"avg_drawdown": -0.06, "baseline_avg_drawdown": -0.02},
        "stop": {"avg_drawdown": -0.04, "baseline_avg_drawdown": -0.01},
    }
    ok, gates = evaluate_gates(report)
    assert ok is True
    assert all(g["passed"] for g in gates)
    assert len(gates) == 7


def test_evaluate_gates_missing_data_is_not_passed():
    """缺数据(全 None)→ 不得判为通过(零编造:不拿 0 顶替)"""
    report = {
        "samples": 0, "codes": 0, "days": 0,
        "entry": {"win_rate": None, "avg_return": None, "baseline_avg_return": None},
        "exit": {"avg_drawdown": None, "baseline_avg_drawdown": None},
        "stop": {"avg_drawdown": None, "baseline_avg_drawdown": None},
    }
    ok, gates = evaluate_gates(report)
    assert ok is False
    assert all(g["actual"] is None for g in gates
               if g["name"] in ("entry 后 10 日胜率", "exit 后 10 日回撤改善"))


def test_evaluate_gates_does_not_mutate_report():
    """纯函数:不改入参"""
    report = {
        "samples": 3, "codes": 1, "days": 10,
        "entry": {"win_rate": 0.9, "avg_return": 0.2, "baseline_avg_return": 0.01},
        "exit": {"avg_drawdown": -0.06, "baseline_avg_drawdown": -0.02},
        "stop": {"avg_drawdown": -0.04, "baseline_avg_drawdown": -0.01},
    }
    snapshot = {
        "samples": report["samples"], "codes": report["codes"], "days": report["days"],
        "entry": dict(report["entry"]), "exit": dict(report["exit"]), "stop": dict(report["stop"]),
    }
    evaluate_gates(report)
    assert report["samples"] == snapshot["samples"]
    assert report["codes"] == snapshot["codes"]
    assert report["days"] == snapshot["days"]
    assert report["entry"] == snapshot["entry"]
    assert report["exit"] == snapshot["exit"]
    assert report["stop"] == snapshot["stop"]


def test_gate_thresholds_match_design_doc():
    """闸门数字与设计文档 §10.2 一致(先定不得下调)"""
    assert bt.MIN_POOL_CODES == 30
    assert bt.MIN_POOL_DAYS == 120
    assert bt.MIN_ENTRY_SAMPLES == 100
    assert bt.MIN_WIN_RATE == 0.53
    assert bt.MIN_EXCESS_RETURN == 0.01
    assert bt.MIN_EXIT_DD_IMPROVE == 0.01
    assert bt.MIN_STOP_DD_IMPROVE == 0.015
    assert bt.HOLD_DAYS == 10
    assert bt.STOP_HOLD_DAYS == 5


# ---------------------------------------------------------------- 口径

def _klines(n: int, start: float = 10.0, step: float = 0.1) -> list[dict[str, Any]]:
    """合成升序日 K:open=收盘前一档(故意与 close 不同,用来验证买入价取 open)"""
    out: list[dict[str, Any]] = []
    for i in range(n):
        close = start + step * i
        out.append({
            "date": f"2026-01-{i % 28 + 1:02d}",
            "open": close - 0.05,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": 1000000 + i,
        })
    return out


def test_forward_return_uses_next_day_open_not_close():
    """买入价 = 信号日**次日开盘价**(不是当日收盘,也不是次日收盘)"""
    ks = _klines(20)
    idx = 5
    win, ret, dd = _forward_return(ks, idx, 10)
    entry = ks[idx + 1]["open"]
    last_close = ks[idx + 10]["close"]
    assert ret == pytest.approx(last_close / entry - 1)
    assert dd == pytest.approx(min(k["close"] for k in ks[idx + 1: idx + 11]) / entry - 1)
    # 若误用次日收盘价,收益会不同
    assert ret != pytest.approx(last_close / ks[idx + 1]["close"] - 1)


def test_forward_return_window_lengths_differ():
    """持有期可切换:stop 用 5 日窗、entry/exit 用 10 日窗"""
    ks = _klines(30, start=10.0, step=0.5)
    _, ret10, dd10 = _forward_return(ks, 3, 10)
    _, ret5, dd5 = _forward_return(ks, 3, 5)
    assert ret10 != pytest.approx(ret5)
    assert dd5 >= dd10  # 更短窗口的最低点不会更低 → 回撤不会更深


def test_forward_return_win_definition():
    """胜 = 持有期内最高收盘价 > 买入价 × 1.02"""
    ks = _klines(20, start=10.0, step=0.0)  # 横盘
    win, _, _ = _forward_return(ks, 0, 10)
    assert win == 0.0
    ks2 = _klines(20, start=10.0, step=0.5)
    win2, _, _ = _forward_return(ks2, 0, 10)
    assert win2 == 1.0


def test_forward_return_insufficient_data_returns_none():
    """数据不足 → (None, None, None),不编造 0"""
    assert _forward_return(_klines(5), 0, 10) == (None, None, None)
    assert _forward_return(_klines(30), 29, 10) == (None, None, None)
    assert _forward_return([], 0, 10) == (None, None, None)


# ---------------------------------------------------------------- 回测主流程

@pytest.mark.asyncio
async def test_run_backtest_collects_three_kinds_without_lookahead(monkeypatch):
    """三种持仓上下文都能产出信号,且信号日只喂 klines[: i+1](无前视)"""
    from app.services import kline_service

    n_bars = bt.MIN_POOL_DAYS + bt.MAX_HOLD_DAYS + bt.WARMUP_DAYS + 5
    ks = _klines(n_bars)

    async def fake_fetch(code: str, period: str = "daily", count: int = 60):
        return [dict(k) for k in ks[:count]]

    monkeypatch.setattr(kline_service, "fetch_klines", fake_fetch)

    seen: list[Any] = []

    def fake_build(ctx):
        seen.append(ctx)
        kind = {"empty": "entry", "profit": "exit", "loss": "stop"}[ctx.position_status]
        return {"actions": [{"kind": kind, "status": "now", "label": kind, "price": 1.0,
                             "condition": "", "basis": []}]}

    monkeypatch.setattr(bt, "build_decision", fake_build)

    report = await run_backtest(["600519.SH"], days=bt.MIN_POOL_DAYS)

    assert report["codes"] == 1
    assert report["days"] == bt.MIN_POOL_DAYS
    assert report["samples"] > 0
    assert report["exit"]["n"] > 0
    assert report["stop"]["n"] > 0
    # 无前视:每次判定拿到的 klines 长度严格递增,且等于「信号日 + 1」
    lengths = sorted({len(ctx.klines) for ctx in seen})
    assert lengths == sorted(set(range(bt.WARMUP_DAYS, bt.WARMUP_DAYS + bt.MIN_POOL_DAYS)))
    for ctx in seen:
        # 判定器看到的最后一根就是「信号日当天」,不含任何未来数据
        assert ctx.klines[-1] == ks[len(ctx.klines) - 1]
        assert len(ctx.klines) < n_bars


@pytest.mark.asyncio
async def test_run_backtest_reports_pool_rates_and_gate_detail(monkeypatch):
    """报告字段:触发率披露 + 逐条闸门 target/actual/passed"""
    from app.services import kline_service

    n_bars = bt.MIN_POOL_DAYS + bt.MAX_HOLD_DAYS + bt.WARMUP_DAYS + 5
    ks = _klines(n_bars)

    async def fake_fetch(code: str, period: str = "daily", count: int = 60):
        return [dict(k) for k in ks[:count]]

    monkeypatch.setattr(kline_service, "fetch_klines", fake_fetch)

    def fake_build(ctx):
        kind = {"empty": "entry", "profit": "exit", "loss": "stop"}[ctx.position_status]
        return {"actions": [{"kind": kind, "status": "now", "label": kind, "price": 1.0,
                             "condition": "", "basis": []}]}

    monkeypatch.setattr(bt, "build_decision", fake_build)

    report = await run_backtest(["600519.SH"], days=bt.MIN_POOL_DAYS)

    rate = report["signal_rate"]
    assert set(rate) == {"entry", "exit", "stop", "total_signal_days"}
    assert rate["total_signal_days"] == bt.MIN_POOL_DAYS
    assert 0.0 <= rate["entry"] <= 1.0
    # 无条件基准存在(否则「改善」无从谈起)
    assert report["unconditional"]["n"] > 0
    assert report["unconditional"]["avg_drawdown_10"] is not None
    assert report["unconditional"]["avg_drawdown_5"] is not None
    # 7 条闸门逐条给出 target / actual / passed
    assert len(report["gates"]) == 7
    for g in report["gates"]:
        assert set(g) == {"name", "target", "actual", "passed"}
    assert isinstance(report["passed"], bool)
    assert report["stocks"][0]["code"] == "600519.SH"
    assert report["stocks"][0]["industry"] == "白酒"


@pytest.mark.asyncio
async def test_run_backtest_skips_stock_that_cannot_fill_window(monkeypatch):
    """K 线不足 → 跳过并记录,不拿别的票凑数"""
    from app.services import kline_service

    short = _klines(80)

    async def fake_fetch(code: str, period: str = "daily", count: int = 60):
        return [dict(k) for k in short]

    monkeypatch.setattr(kline_service, "fetch_klines", fake_fetch)

    report = await run_backtest(["000001.SZ"], days=bt.MIN_POOL_DAYS)
    assert report["codes"] == 0
    assert report["days"] == 0
    assert report["skipped"]
    assert report["skipped"][0]["code"] == "000001.SZ"


# ---------------------------------------------------------------- §10.3 规则参数旋钮

def test_entry_rule_ok_rejects_missing_or_low_volume_ratio():
    """放量确认:量比缺失 或 < 阈值 → 不放行(缺数据不编造)"""
    rule = bt.EntryRule(min_volume_ratio=1.5)
    assert bt._entry_rule_ok({"volume": {"ratio": 1.2}}, [], rule) is False
    assert bt._entry_rule_ok({"volume": {"ratio": None}}, [], rule) is False
    assert bt._entry_rule_ok({}, [], rule) is False
    assert bt._entry_rule_ok({"volume": {"ratio": 1.5}}, [], rule) is True
    assert bt._entry_rule_ok({"volume": {"ratio": 2.0}}, [], rule) is True


def test_entry_rule_ok_chg5_positive():
    """动能确认:5 日涨幅必须 > 0,数据不足不放行"""
    rule = bt.EntryRule(require_chg5_positive=True)
    up = _klines(10, start=10.0, step=0.5)
    down = _klines(10, start=20.0, step=-0.5)
    assert bt._entry_rule_ok({}, up, rule) is True
    assert bt._entry_rule_ok({}, down, rule) is False
    assert bt._entry_rule_ok({}, up[:5], rule) is False


@pytest.mark.asyncio
async def test_run_backtest_entry_rule_filters_signals(monkeypatch):
    """收紧规则 → entry 样本变少、被过滤条数被披露(闸门样本数随之下降)"""
    from app.services import kline_service

    n_bars = bt.MIN_POOL_DAYS + bt.MAX_HOLD_DAYS + bt.WARMUP_DAYS + 5
    ks = _klines(n_bars)

    async def fake_fetch(code: str, period: str = "daily", count: int = 60):
        return [dict(k) for k in ks[:count]]

    monkeypatch.setattr(kline_service, "fetch_klines", fake_fetch)

    def fake_build(ctx):
        kind = {"empty": "entry", "profit": "exit", "loss": "stop"}[ctx.position_status]
        return {"actions": [{"kind": kind, "status": "now", "label": kind, "price": 1.0,
                             "condition": "", "basis": []}]}

    monkeypatch.setattr(bt, "build_decision", fake_build)

    # 量比恒为 0.1 → 全部被放量确认过滤掉
    def fake_indicators(window):
        return {"volume": {"ratio": 0.1}}

    monkeypatch.setattr(bt, "compute_indicators", fake_indicators)

    loose = await run_backtest(["600519.SH"], days=bt.MIN_POOL_DAYS)
    assert loose["entry_rule"] == {"min_volume_ratio": None, "require_chg5_positive": False}
    assert loose["entry_filtered"] == 0
    assert loose["samples"] > 0

    tight = await run_backtest(
        ["600519.SH"], days=bt.MIN_POOL_DAYS, entry_rule=bt.EntryRule(min_volume_ratio=1.5)
    )
    assert tight["entry_rule"]["min_volume_ratio"] == 1.5
    assert tight["entry_filtered"] > 0
    assert tight["samples"] == 0
    assert tight["gates"][2]["passed"] is False  # 有效 entry 信号数闸门


# ---------------------------------------------------------------- 样本池

def test_pool_expansion_is_disclosed_and_unique():
    """扩池:基池 30 只 + 扩池 30 只 = 60 只,代码不重复、行业齐全"""
    assert len(bt.POOL_BASE) == 30
    assert len(bt.POOL_EXTRA) == 30
    assert len(bt.POOL) == 60
    codes = [c for c, _ in bt.POOL]
    assert len(set(codes)) == len(codes)
    assert set(bt.BASE_CODES).issubset(set(bt.DEFAULT_CODES))
    assert all(ind for _, ind in bt.POOL)
    assert all(bt.INDUSTRY.get(c) for c in bt.DEFAULT_CODES)
    # 扩池不得让闸门数字跟着变
    assert bt.MIN_POOL_CODES == 30
