"""回测闸门的**口径不变量**（父代理评审补充，锁死 §10.1.1 最容易被悄悄改坏的三件事）

`test_decision_backtest.py` 钉死的是「引擎跑得对不对」；
本文件钉死的是**回测口径本身**——它们一旦被改坏，闸门会安静地给出漂亮但无意义的结论：

1. **无条件基准必须覆盖全部可回测日**（不是只有信号日）
   —— 若基准臂只统计信号日，「超额收益 / 改善」退化成「信号 vs 信号」，恒等于 0，闸门形同虚设。
2. **两臂同窗可比**：stop 的基准臂必须用 5 日窗，不是 10 日窗。
   —— 5 日窗的最低点天然 ≥ 10 日窗，「改善」会凭空为正，变成假通过。
3. **改善方向 = 基准 − 信号**（正 = 信号情形比常态更好）。
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services import decision_backtest as bt
from app.services.decision_backtest import _forward_return, run_backtest


def _klines(n: int, start: float = 10.0, step: float = 0.1) -> list[dict[str, Any]]:
    """合成升序日 K：open = 收盘前一档（故意与 close 不同，用来验证买入价取 open）"""
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


def _vshape_klines(n: int) -> list[dict[str, Any]]:
    """先跌后涨的 V 形序列 —— 10 日窗与 5 日窗吃到的低点不同，才能验证「同窗可比」"""
    out: list[dict[str, Any]] = []
    for i in range(n):
        close = 10.0 - 0.15 * i if i < n // 2 else 10.0 - 0.15 * (n - i)
        out.append({
            "date": f"2026-01-{i % 28 + 1:02d}",
            "open": close - 0.05,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": 1000000 + i,
        })
    return out


def _patch_klines(monkeypatch, ks: list[dict[str, Any]]) -> None:
    """把 kline_service.fetch_klines 换成固定序列"""
    from app.services import kline_service

    async def fake_fetch(code: str, period: str = "daily", count: int = 60):
        return [dict(k) for k in ks[:count]]

    monkeypatch.setattr(kline_service, "fetch_klines", fake_fetch)


@pytest.mark.asyncio
async def test_unconditional_baseline_covers_all_backtest_days(monkeypatch):
    """无条件基准 = 全部可回测日的均值（不是信号日的均值）"""
    n_bars = bt.MIN_POOL_DAYS + bt.MAX_HOLD_DAYS + bt.WARMUP_DAYS + 5
    _patch_klines(monkeypatch, _klines(n_bars))

    # 只在最后一个信号日发信号 → 若基准只统计信号日，unconditional.n 会是 1
    last_len = bt.WARMUP_DAYS + bt.MIN_POOL_DAYS - 1

    def fake_build(ctx):
        if len(ctx.klines) != last_len:
            return {"actions": []}
        kind = {"empty": "entry", "profit": "exit", "loss": "stop"}[ctx.position_status]
        return {"actions": [{"kind": kind, "status": "now", "label": kind, "price": 1.0,
                             "condition": "", "basis": []}]}

    monkeypatch.setattr(bt, "build_decision", fake_build)

    report = await run_backtest(["600519.SH"], days=bt.MIN_POOL_DAYS)

    # 基准臂条数 = 全部可回测日（120），与信号条数（3）无关
    assert report["unconditional"]["n"] == bt.MIN_POOL_DAYS
    assert report["samples"] == 1
    assert report["exit"]["n"] == 1
    assert report["stop"]["n"] == 1


@pytest.mark.asyncio
async def test_unconditional_baseline_values_match_manual_mean(monkeypatch):
    """基准臂的均值与手工按同一函数逐日计算的结果一致（口径可复现）"""
    n_bars = bt.MIN_POOL_DAYS + bt.MAX_HOLD_DAYS + bt.WARMUP_DAYS + 5
    ks = _klines(n_bars)
    _patch_klines(monkeypatch, ks)

    def fake_build(ctx):
        return {"actions": []}

    monkeypatch.setattr(bt, "build_decision", fake_build)

    report = await run_backtest(["600519.SH"], days=bt.MIN_POOL_DAYS)

    used = ks[: bt.MIN_POOL_DAYS + bt.MAX_HOLD_DAYS + bt.WARMUP_DAYS]  # 模块实际取 count 根
    lo = bt.WARMUP_DAYS - 1
    hi = len(used) - bt.MAX_HOLD_DAYS - 1
    rets, dd10s, dd5s, wins = [], [], [], []
    for i in range(lo, hi):
        w, r10, d10 = _forward_return(used, i, bt.HOLD_DAYS)
        _, _, d5 = _forward_return(used, i, bt.STOP_HOLD_DAYS)
        wins.append(w)
        rets.append(r10)
        dd10s.append(d10)
        dd5s.append(d5)

    u = report["unconditional"]
    assert u["avg_return_10"] == pytest.approx(round(sum(rets) / len(rets), 4))
    assert u["avg_drawdown_10"] == pytest.approx(round(sum(dd10s) / len(dd10s), 4))
    assert u["avg_drawdown_5"] == pytest.approx(round(sum(dd5s) / len(dd5s), 4))
    assert u["win_rate_10"] == pytest.approx(round(sum(wins) / len(wins), 4))


@pytest.mark.asyncio
async def test_stop_baseline_uses_5_day_window_not_10(monkeypatch):
    """stop 的基准臂必须用 5 日窗（与信号臂同窗），不是 10 日窗"""
    n_bars = bt.MIN_POOL_DAYS + bt.MAX_HOLD_DAYS + bt.WARMUP_DAYS + 5
    _patch_klines(monkeypatch, _vshape_klines(n_bars))

    def fake_build(ctx):
        kind = {"empty": "entry", "profit": "exit", "loss": "stop"}[ctx.position_status]
        return {"actions": [{"kind": kind, "status": "now", "label": kind, "price": 1.0,
                             "condition": "", "basis": []}]}

    monkeypatch.setattr(bt, "build_decision", fake_build)

    report = await run_backtest(["600519.SH"], days=bt.MIN_POOL_DAYS)

    u = report["unconditional"]
    # V 形序列：10 日窗吃到更深的低点 → 10 日基准回撤更差
    assert u["avg_drawdown_5"] > u["avg_drawdown_10"]
    # stop 的基准臂取的就是 5 日基准；exit 取 10 日基准（两臂同窗可比）
    assert report["stop"]["baseline_avg_drawdown"] == u["avg_drawdown_5"]
    assert report["exit"]["baseline_avg_drawdown"] == u["avg_drawdown_10"]


def test_improvement_sign_convention_is_baseline_minus_signal():
    """改善方向 = 基准 − 信号（正 = 信号情形比常态更好）"""
    report = {
        "samples": 5000, "codes": 40, "days": 120,
        "entry": {"win_rate": 0.56, "avg_return": 0.031, "baseline_avg_return": 0.011},
        "exit": {"avg_drawdown": -0.06, "baseline_avg_drawdown": -0.02},
        "stop": {"avg_drawdown": -0.04, "baseline_avg_drawdown": -0.01},
    }
    ok, gates = bt.evaluate_gates(report)
    assert ok is True
    exit_gate = next(g for g in gates if g["name"].startswith("exit"))
    stop_gate = next(g for g in gates if g["name"].startswith("stop"))
    assert exit_gate["actual"] == pytest.approx(0.04)   # -0.02 - (-0.06)
    assert stop_gate["actual"] == pytest.approx(0.03)    # -0.01 - (-0.04)

    # 反过来：信号情形比常态更差 → 改善为负 → 闸门不通过
    worse = dict(report)
    worse["exit"] = {"avg_drawdown": -0.01, "baseline_avg_drawdown": -0.02}
    worse["stop"] = {"avg_drawdown": -0.02, "baseline_avg_drawdown": -0.01}
    ok2, gates2 = bt.evaluate_gates(worse)
    assert ok2 is False
    assert next(g for g in gates2 if g["name"].startswith("exit"))["passed"] is False
    assert next(g for g in gates2 if g["name"].startswith("stop"))["passed"] is False
