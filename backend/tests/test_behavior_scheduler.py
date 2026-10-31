"""行为标注调度器(闸 4 稳定闸)单测。

**为什么跳过条件不能照抄选股**:选股的跳过条件是「今天有 run 就跳过」;
行为标注的盘中手动跑批带 `is_intraday=true` —— 若被当成「今天已跑」,
盘后调度器就会跳过 → **盘中那份会一直留着当最新批次**。
"""
from __future__ import annotations

from datetime import date, datetime

from app.modules.behavior_screener.service import (
    resolve_batch_time_marks,
    should_run_behavior_batch,
)


class _Run:
    def __init__(self, run_date: date, is_intraday: bool | None):
        self.run_date = run_date
        self.is_intraday = is_intraday


class TestResolveBatchTimeMarks:
    def test_after_close_is_not_intraday(self):
        """工作日 15:30 → 已收盘,is_intraday=False,data_as_of=当天。"""
        now = datetime(2026, 10, 30, 15, 30)
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is False
        assert data_as_of == date(2026, 10, 30)

    def test_intraday_marks_yesterday_as_of(self):
        """工作日 10:00 → 盘中,data_as_of 是上一个交易日,is_intraday=True。"""
        now = datetime(2026, 10, 30, 10, 0)
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is True
        assert data_as_of == date(2026, 10, 29)

    def test_intraday_before_open_uses_previous_day(self):
        """工作日 08:00(盘前)→ 当日尚未开盘,同样按盘中口径。"""
        now = datetime(2026, 10, 30, 8, 0)
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is True
        assert data_as_of == date(2026, 10, 29)

    def test_weekend_is_not_intraday(self):
        """周六 → 非盘中,data_as_of=上周五。"""
        now = datetime(2026, 10, 31, 10, 0)  # 周六
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is False
        assert data_as_of == date(2026, 10, 30)  # 周五

    def test_monday_before_open_skips_weekend(self):
        """周一盘前 → data_as_of 是上周五(跳过周末)。"""
        now = datetime(2026, 11, 2, 8, 0)  # 周一
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is True
        assert data_as_of == date(2026, 10, 30)  # 周五


class TestShouldRun:
    def test_runs_when_no_batch_today(self):
        now = datetime(2026, 10, 30, 15, 30)
        assert should_run_behavior_batch(None, now) is True

    def test_skips_when_today_has_non_intraday_batch(self):
        """今天已有盘后批次 → 跳过。"""
        now = datetime(2026, 10, 30, 15, 30)
        run = _Run(date(2026, 10, 30), is_intraday=False)
        assert should_run_behavior_batch(run, now) is False

    def test_runs_when_today_batch_was_intraday(self):
        """今天只有盘中批次 → **要跑**(盘后必须覆盖)。"""
        now = datetime(2026, 10, 30, 15, 30)
        run = _Run(date(2026, 10, 30), is_intraday=True)
        assert should_run_behavior_batch(run, now) is True

    def test_runs_when_batch_is_from_another_day(self):
        """昨天有批次 → 今天照跑。"""
        now = datetime(2026, 10, 30, 15, 30)
        run = _Run(date(2026, 10, 29), is_intraday=False)
        assert should_run_behavior_batch(run, now) is True

    def test_runs_when_today_batch_is_intraday_unknown(self):
        """今天的批次 `is_intraday` 是 **None(未知)** → **要跑**。

        ⚠️ 见 R1:未知 ≠ 「确定不是盘中」。若把 None 当成 False 跳过,
        一个占位/未知批次就能把当天的盘后跑批挡掉。
        """
        now = datetime(2026, 10, 30, 15, 30)
        run = _Run(date(2026, 10, 30), is_intraday=None)
        assert should_run_behavior_batch(run, now) is True

    def test_does_not_run_before_1530(self):
        """15:29 → 不跑(未到时间窗)。"""
        now = datetime(2026, 10, 30, 15, 29)
        assert should_run_behavior_batch(None, now) is False

    def test_does_not_run_on_weekend(self):
        now = datetime(2026, 10, 31, 16, 0)  # 周六
        assert should_run_behavior_batch(None, now) is False
