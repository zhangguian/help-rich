"""统一窗口过滤(behavior_signal_service)单测。

**为什么需要它**:找股路径与 K 线路径曾经各写各的过滤,
一个按「日历天 60」、一个按「K 线根数 120 根」—— 单位都不同,
导致 61% 的信号「找股页有、K 线上找不到」。
把过滤收敛到**一个纯函数**,一致性问题就从「靠人记住」变成「物理保证」。
"""
from __future__ import annotations

from datetime import date

from app.services.behavior_signal_service import (
    KIND_MAIN_FORCE_MOVE,
    BehaviorMarker,
    base_date_from_klines,
    filter_markers_by_window,
    marker_date,
)


def _mk(d: str) -> BehaviorMarker:
    return BehaviorMarker(
        kind=KIND_MAIN_FORCE_MOVE, date=d, date_index=0,
        text="⚡ 主力异动", position="aboveBar", color="#f59e0b",
        reason="依据", metrics={},
    )


class TestFilterByWindow:
    def test_keeps_markers_inside_window(self):
        base = date(2026, 10, 30)
        ms = [_mk("2026-10-30"), _mk("2026-10-20"), _mk("2026-07-01")]
        out = filter_markers_by_window(ms, base, 120)
        # 2026-10-30 与 2026-10-20 在窗口内;2026-07-01 距今 151 天 → 剔除
        assert [m.date for m in out] == ["2026-10-30", "2026-10-20"]

    def test_boundary_is_inclusive(self):
        """恰好 120 天 → 保留(边界含端点)。"""
        base = date(2026, 10, 30)
        boundary = date(2026, 7, 2)  # base - 120 天
        out = filter_markers_by_window([_mk(boundary.isoformat())], base, 120)
        assert len(out) == 1

    def test_uses_calendar_days_not_bar_count(self):
        """按日历天算,不按 K 线根数 —— 120 天 != 120 根。"""
        base = date(2026, 10, 30)
        just_outside = date(2026, 7, 1)  # 距今 121 天
        out = filter_markers_by_window([_mk(just_outside.isoformat())], base, 120)
        assert out == []

    def test_preserves_input_order(self):
        base = date(2026, 10, 30)
        ms = [_mk("2026-10-25"), _mk("2026-10-30"), _mk("2026-10-28")]
        out = filter_markers_by_window(ms, base, 120)
        assert [m.date for m in out] == ["2026-10-25", "2026-10-30", "2026-10-28"]

    def test_empty_input(self):
        assert filter_markers_by_window([], date(2026, 10, 30), 120) == []

    def test_non_positive_lookback_returns_all(self):
        base = date(2026, 10, 30)
        ms = [_mk("2020-01-01")]
        assert filter_markers_by_window(ms, base, 0) == ms


class TestMarkerDate:
    def test_parses_iso_date(self):
        assert marker_date(_mk("2026-10-30")) == date(2026, 10, 30)

    def test_returns_none_on_bad_format(self):
        """日期不可解析 → None(不编数字,不猜)。"""
        assert marker_date(_mk("不是日期")) is None


class TestBaseDateFromKlines:
    def test_takes_last_kline_date(self):
        items = [{"date": "2026-10-28"}, {"date": "2026-10-30"}]
        assert base_date_from_klines(items) == date(2026, 10, 30)

    def test_returns_none_when_empty(self):
        assert base_date_from_klines([]) is None

    def test_returns_none_on_bad_format(self):
        assert base_date_from_klines([{"date": "xx"}]) is None
