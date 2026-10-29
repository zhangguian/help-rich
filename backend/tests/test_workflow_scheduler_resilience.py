"""调度器容错测试(2026-10-27 事故回归)

**事故**:11:30 档因「今日作战计划还没生成」抛 `IntradayReviewError` →
异常直接冲出 `start_workflow_scheduler` 的 `while` 循环 →
**调度器当场死亡**(日志:`Task exception was never retrieved`) →
当天后续所有窗口(含 14:00 那档)再也没人跑 → 当天两档复盘全空 →
前端面板只能显示「下一次盘中复盘 11:30」,用户完全看不到复盘内容。

**这次改了三件事**,本文件逐条钉死:

1. 单窗口失败**不杀调度器** —— 异常被吃掉,循环继续。
2. **只有成功**才写 `_fired` —— 失败的那档在补跑有效期内还能再试。
3. **推送失败不重试** —— 产出已落库,重推=重复打扰用户;只有产出失败才重试。

**不打桩真实网络**:交易日历、复盘编排、推送全部在边界处替换。
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

import pytest

from app.core import trading_calendar as tc
from app.modules.analysis import workflow_scheduler as ws


@pytest.fixture(autouse=True)
def _clean():
    ws.reset_fired()
    yield
    ws.reset_fired()


def _patch_calendar(monkeypatch, *, trading: bool, estimated: bool = False):
    """把交易日历换掉(不打桩真实网络)"""
    from app.services import trading_calendar_service as tcs

    async def _ensure(force: bool = False):
        return tc.current_calendar()

    monkeypatch.setattr(tcs, "ensure_trading_calendar", _ensure)
    monkeypatch.setattr(tc, "is_trading_day", lambda d: trading)
    monkeypatch.setattr(
        tc,
        "trading_days_hint",
        lambda: {
            "source": "weekday_fallback" if estimated else "index_kline",
            "estimated": estimated,
            "trade_date": date.today().isoformat(),
        },
    )


def _patch_review(monkeypatch, *, produce, dispatch, has_review=None):
    """替换盘中复盘的编排与推送(不打桩真实网络)"""
    from app.modules.analysis import intraday_review as ir
    from app.services import trading_calendar_service as tcs

    async def _meta(target=None):
        return {
            "is_trading_day": True,
            "trade_date_source": "index_kline",
            "trading_day_estimated": False,
            "trade_date": date.today().isoformat(),
        }

    async def _produce(slot, trading_day=None):
        return await produce(slot)

    async def _dispatch(payload):
        return await dispatch(payload)

    async def _has(trade_date, slot):
        if has_review is None:
            return False
        return await has_review(trade_date, slot)

    monkeypatch.setattr(ir, "run_intraday_review", _produce)
    monkeypatch.setattr(ir, "dispatch_intraday_review", _dispatch)
    monkeypatch.setattr(ir, "has_review", _has)
    monkeypatch.setattr(tcs, "trading_day_meta", _meta)


# ---------------- 契约:due_windows 不再标记「已跑」 ----------------

async def test_due_windows_does_not_mark_itself(monkeypatch):
    """⚠️ 旧契约:`due_windows` 跑一次就等于「今天这档跑过了」——
    所以失败一次 = 当天放弃。新契约:标记只发生在**产出成功之后**。"""
    _patch_calendar(monkeypatch, trading=True)
    now = datetime(2026, 10, 22, 11, 30)
    assert await ws.due_windows(now) == ["intraday_am"]
    # 再问一次 → 仍然 due(因为还没成功产出过)
    assert await ws.due_windows(now) == ["intraday_am"]
    assert ws._fired == set()


# ---------------- 失败可补跑 / 成功不重跑 ----------------

async def test_failed_window_can_be_retried(monkeypatch):
    """产出失败 → 不写 `_fired` → 过了重试间隔还能再试"""
    _patch_calendar(monkeypatch, trading=True)
    t0 = datetime(2026, 10, 22, 11, 30)
    ws.mark_attempt("intraday_am", t0, ok=False)

    assert "intraday_am" in await ws.due_windows(t0 + timedelta(minutes=6))


async def test_successful_window_is_not_run_again(monkeypatch):
    """产出成功 → 写 `_fired` → 同一天不再跑(幂等)"""
    _patch_calendar(monkeypatch, trading=True)
    t0 = datetime(2026, 10, 22, 11, 30)
    ws.mark_attempt("intraday_am", t0, ok=True)

    assert "intraday_am" not in await ws.due_windows(t0 + timedelta(minutes=6))


async def test_retry_respects_min_interval(monkeypatch):
    """离上次失败不到 5 分钟 → 不再试(否则每分钟炸一次日志)"""
    _patch_calendar(monkeypatch, trading=True)
    t0 = datetime(2026, 10, 22, 11, 30)
    ws.mark_attempt("intraday_am", t0, ok=False)

    assert "intraday_am" not in await ws.due_windows(t0 + timedelta(minutes=2))
    assert "intraday_am" in await ws.due_windows(t0 + timedelta(minutes=6))


# ---------------- 补跑截止时刻 ----------------

async def test_am_slot_still_retryable_at_1429(monkeypatch):
    """11:30 档的补跑截止是 14:29(下一档触发之前)"""
    _patch_calendar(monkeypatch, trading=True)
    assert "intraday_am" in await ws.due_windows(datetime(2026, 10, 22, 14, 29))


async def test_am_slot_gives_up_after_1429(monkeypatch):
    """过了 14:29 → 下午三点补一份上午的复盘没意义"""
    _patch_calendar(monkeypatch, trading=True)
    assert "intraday_am" not in await ws.due_windows(datetime(2026, 10, 22, 14, 30))


async def test_pm_slot_still_retryable_at_1559(monkeypatch):
    """14:00 档的补跑截止是 15:59(收盘之后)"""
    _patch_calendar(monkeypatch, trading=True)
    due = await ws.due_windows(datetime(2026, 10, 22, 15, 59))
    assert "intraday_pm" in due


async def test_pm_slot_gives_up_after_1559(monkeypatch):
    _patch_calendar(monkeypatch, trading=True)
    due = await ws.due_windows(datetime(2026, 10, 22, 16, 0))
    assert "intraday_pm" not in due


# ---------------- 跨窗口补早档 ----------------

async def test_1400_window_backfills_1130_in_time_order(monkeypatch):
    """14:00 触发时,先把没成功的 11:30 补掉,再跑 14:00(按时间序)"""
    _patch_calendar(monkeypatch, trading=True)
    due = await ws.due_windows(datetime(2026, 10, 22, 14, 0))
    assert due == ["intraday_am", "intraday_pm"]


async def test_1400_window_does_not_backfill_a_succeeded_1130(monkeypatch):
    """11:30 已经成功产出过 → 14:00 时只跑自己那一档"""
    _patch_calendar(monkeypatch, trading=True)
    t0 = datetime(2026, 10, 22, 11, 30)
    ws.mark_attempt("intraday_am", t0, ok=True)

    due = await ws.due_windows(datetime(2026, 10, 22, 14, 0))
    assert due == ["intraday_pm"]


# ---------------- 状态不无限增长 ----------------

async def test_old_days_are_pruned(monkeypatch):
    """常驻进程跑久了不能攒一堆过期键(判定只看今天,旧键是纯垃圾)"""
    _patch_calendar(monkeypatch, trading=True)
    old = datetime(2026, 10, 20, 14, 5)
    today = datetime(2026, 10, 22, 14, 5)

    ws.mark_attempt("intraday_pm", old, ok=True)
    ws.mark_attempt("intraday_am", old, ok=False)
    assert ws._fired  # 昨天确实记过

    ws.mark_attempt("intraday_pm", today, ok=True)

    assert all(k.startswith("2026-10-22:") for k in ws._fired)
    assert all(k.startswith("2026-10-22:") for k in ws._last_attempt)
    assert len(ws._fired) == 1


# ---------------- 已经产出过 → 不重跑、不重推 ----------------

async def test_already_produced_slot_is_skipped(monkeypatch):
    """⚠️ 调度器的「已跑」标记只在内存里,后端一重启就忘了。

    不查库的话,重启会把还在补跑窗口内的档**再产出一次、再推一次** ——
    而推送不可撤回,重复推就是重复打扰用户。
    """
    produced = {"n": 0}
    dispatched = {"n": 0}

    async def _produce(slot):
        produced["n"] += 1
        return {"slot": slot, "actions": []}

    async def _dispatch(payload):
        dispatched["n"] += 1
        return []

    async def _already(trade_date, slot):
        return True

    _patch_review(monkeypatch, produce=_produce, dispatch=_dispatch, has_review=_already)

    assert await ws._run_window("intraday_am") is True
    assert produced["n"] == 0
    assert dispatched["n"] == 0


async def test_not_produced_slot_runs_normally(monkeypatch):
    """库里没有这一档 → 正常产出 + 推送"""
    produced = {"n": 0}
    dispatched = {"n": 0}

    async def _produce(slot):
        produced["n"] += 1
        return {"slot": slot, "actions": []}

    async def _dispatch(payload):
        dispatched["n"] += 1
        return []

    async def _not_yet(trade_date, slot):
        return False

    _patch_review(monkeypatch, produce=_produce, dispatch=_dispatch, has_review=_not_yet)

    assert await ws._run_window("intraday_am") is True
    assert produced["n"] == 1
    assert dispatched["n"] == 1


# ---------------- _run_window 的成败语义 ----------------

async def test_run_window_returns_false_when_production_fails(monkeypatch):
    """产出失败 → 返回 False(可重试)。异常**不能**抛出去。"""
    async def _boom(slot):
        raise ValueError("今日作战计划还没生成(2026-10-27),请先生成作战计划再跑盘中复盘")

    async def _dispatch(payload):
        return []

    _patch_review(monkeypatch, produce=_boom, dispatch=_dispatch)
    assert await ws._run_window("intraday_am") is False


async def test_run_window_returns_true_when_push_fails(monkeypatch):
    """推送失败 → 返回 True(**不重试**)。产出已经落库,重推=重复打扰用户。"""
    async def _produce(slot):
        return {"slot": slot, "actions": [1, 2, 3]}

    async def _dispatch(payload):
        raise RuntimeError("推送通道全挂了")

    _patch_review(monkeypatch, produce=_produce, dispatch=_dispatch)
    assert await ws._run_window("intraday_am") is True


async def test_run_window_returns_true_on_success(monkeypatch):
    async def _produce(slot):
        return {"slot": slot, "actions": [1]}

    async def _dispatch(payload):
        return []

    _patch_review(monkeypatch, produce=_produce, dispatch=_dispatch)
    assert await ws._run_window("intraday_am") is True


async def test_run_window_swallows_premarket_failure(monkeypatch):
    """盘前窗口失败也不能抛(事故那次的同款路径)"""
    from app.modules.analysis import workflow as wf

    async def _boom():
        raise RuntimeError("持仓取不到")

    monkeypatch.setattr(wf.workflow_agent_service, "run_premarket", _boom)
    assert await ws._run_window("premarket") is False


async def test_run_window_premarket_push_failure_is_not_retried(monkeypatch):
    from app.modules.analysis import workflow as wf

    async def _ok():
        return "brief"

    async def _dispatch(result):
        raise RuntimeError("推送失败")

    monkeypatch.setattr(wf.workflow_agent_service, "run_premarket", _ok)
    monkeypatch.setattr(wf.workflow_agent_service, "dispatch", _dispatch)
    assert await ws._run_window("premarket") is True


# ---------------- 调度器主循环:单窗口失败不死 ----------------

async def test_scheduler_loop_survives_window_exception(monkeypatch):
    """**回归事故**:单窗口抛异常 → 调度器必须继续跑下一轮。"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    rounds: list[str] = []

    async def _boom(kind):
        rounds.append(kind)
        raise RuntimeError("今日作战计划还没生成")

    async def _due(now):
        return ["intraday_am"]

    monkeypatch.setattr(ws, "_run_window", _boom)
    monkeypatch.setattr(ws, "due_windows", _due)

    sleeps: list[int] = []

    async def _fake_sleep(_sec):
        sleeps.append(1)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await ws.start_workflow_scheduler(interval_sec=1)

    # 三轮都跑到了 → 异常没有把循环带走
    assert len(rounds) == 3
    assert len(sleeps) == 3


async def test_scheduler_loop_marks_only_successful_windows(monkeypatch):
    """成功才写 `_fired`;失败的档下一轮还能再 due。"""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    async def _due(now):
        return ["intraday_am"]

    async def _run(kind):
        _run.calls.append(kind)
        return len(_run.calls) > 1

    _run.calls = []

    monkeypatch.setattr(ws, "due_windows", _due)
    monkeypatch.setattr(ws, "_run_window", _run)

    sleeps: list[int] = []

    async def _fake_sleep(_sec):
        sleeps.append(1)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await ws.start_workflow_scheduler(interval_sec=1)

    # 前两轮失败 → 都没写 _fired;第三轮成功 → 写了
    assert ws._fired == {f"{date.today().isoformat()}:intraday_am"}
