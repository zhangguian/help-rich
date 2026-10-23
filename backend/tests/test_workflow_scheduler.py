"""workflow 调度器测试(阶段 T2.4)

覆盖:`intraday_pm` 窗口 = 14:00 / 非交易日不触发 / 同日同窗口只触发一次。
"""
from __future__ import annotations

from datetime import date, datetime

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

    async def _meta(target=None):
        return {
            "is_trading_day": trading,
            "trade_date_source": "weekday_fallback" if estimated else "index_kline",
            "trading_day_estimated": estimated,
            "trade_date": date.today().isoformat(),
        }

    monkeypatch.setattr(tcs, "ensure_trading_calendar", _ensure)
    monkeypatch.setattr(tcs, "trading_day_meta", _meta)
    monkeypatch.setattr(tc, "is_trading_day", lambda d: trading)
    monkeypatch.setattr(
        tc, "trading_days_hint",
        lambda: {
            "source": "weekday_fallback" if estimated else "index_kline",
            "estimated": estimated,
            "trade_date": date.today().isoformat(),
        },
    )


# ---------------- 时间窗定义 ----------------

def test_intraday_pm_window_moved_to_1400():
    assert ("intraday_pm", 14, 0, 29) in ws.TIME_WINDOWS
    assert ws.SLOT_LABEL["intraday_pm"] == "14:00"
    assert ws.SLOT_LABEL["intraday_am"] == "11:30"
    # 盘后窗口不动
    assert ("postmarket", 16, 0, 59) in ws.TIME_WINDOWS


def test_review_slot_mapping():
    assert ws.REVIEW_SLOT["intraday_am"] == "11:30"
    assert ws.REVIEW_SLOT["intraday_pm"] == "14:00"


# ---------------- 触发 ----------------

async def test_due_windows_triggers_at_1400(monkeypatch):
    _patch_calendar(monkeypatch, trading=True)
    assert await ws.due_windows(datetime(2026, 10, 22, 14, 5)) == ["intraday_pm"]


async def test_due_windows_triggers_at_last_minute_of_window(monkeypatch):
    _patch_calendar(monkeypatch, trading=True)
    assert await ws.due_windows(datetime(2026, 10, 22, 14, 29)) == ["intraday_pm"]


async def test_due_windows_triggers_at_1130(monkeypatch):
    _patch_calendar(monkeypatch, trading=True)
    assert await ws.due_windows(datetime(2026, 10, 22, 11, 30)) == ["intraday_am"]


async def test_due_windows_ignores_old_1450_window(monkeypatch):
    """旧的 14:50 窗口已经不存在了"""
    _patch_calendar(monkeypatch, trading=True)
    assert await ws.due_windows(datetime(2026, 10, 22, 14, 50)) == []


async def test_non_trading_day_does_not_trigger(monkeypatch):
    _patch_calendar(monkeypatch, trading=False)
    assert await ws.due_windows(datetime(2026, 10, 22, 11, 30)) == []
    assert await ws.due_windows(datetime(2026, 10, 22, 14, 5)) == []
    assert await ws.due_windows(datetime(2026, 10, 22, 8, 30)) == []


async def test_same_window_triggers_only_once_per_day(monkeypatch):
    _patch_calendar(monkeypatch, trading=True)
    assert await ws.due_windows(datetime(2026, 10, 22, 14, 5)) == ["intraday_pm"]
    assert await ws.due_windows(datetime(2026, 10, 22, 14, 10)) == []
    # 另一天同一窗口可以再触发
    assert await ws.due_windows(datetime(2026, 10, 23, 14, 5)) == ["intraday_pm"]


async def test_estimated_calendar_still_runs(monkeypatch):
    """数据源故障回落工作日时**仍然跑**(只是标注 estimated)"""
    _patch_calendar(monkeypatch, trading=True, estimated=True)
    assert await ws.due_windows(datetime(2026, 10, 22, 11, 30)) == ["intraday_am"]
