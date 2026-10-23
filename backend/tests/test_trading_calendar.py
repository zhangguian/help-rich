"""真实交易日历测试(阶段 T1)

覆盖:真实交易日 / 周末 / 法定节假日 / 数据源故障回落(estimated=True) / 缓存。

**不打桩网络**:所有用例都通过 `load_trading_calendar(source)` 注入数据源回调,
不碰真实 K 线接口 —— 这也是 T1 要求的「可注入的测试入口」。
"""
from __future__ import annotations

from datetime import date

import pytest

from app.core import trading_calendar as tc

# 2026-10-19(一) ~ 2026-10-22(四) 连着四个交易日
TRADING_DAYS = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"]


@pytest.fixture(autouse=True)
def _clean_cache():
    tc.reset_trading_calendar()
    yield
    tc.reset_trading_calendar()


async def _ok_source():
    return list(TRADING_DAYS)


async def _boom_source():
    raise RuntimeError("数据源炸了")


async def _empty_source():
    return []


# ---------------- 真实交易日 / 周末 / 节假日 ----------------

async def test_real_trading_day_is_true():
    cal = await tc.load_trading_calendar(_ok_source)
    assert cal.source == tc.SOURCE_INDEX_KLINE
    assert cal.estimated is False
    assert tc.is_trading_day(date(2026, 10, 20)) is True
    assert tc.is_trading_day(date(2026, 10, 22)) is True


async def test_weekend_is_not_trading_day():
    """周末(2026-10-18 是周日)在真实覆盖范围内 → 没有 K 线 → 不是交易日"""
    await tc.load_trading_calendar(_ok_source)
    assert tc.is_trading_day(date(2026, 10, 18)) is False
    assert tc.is_trading_day(date(2026, 10, 17)) is False


async def test_holiday_inside_coverage_is_not_trading_day():
    """法定节假日:工作日、且落在真实数据覆盖范围内,但集合里没有它 → 不是交易日。

    这是「有 K 线的日期 = 真实交易日」的真源价值:国庆 / 春节那种长假,
    工作日推算会算错,真实日 K 不会。
    """
    await tc.load_trading_calendar(_ok_source)
    # 2026-10-16(周五)在覆盖范围内,集合里没有 → 节假日
    assert tc.is_trading_day(date(2026, 10, 16)) is False


async def test_date_beyond_coverage_falls_back_to_weekday():
    """真实数据还没覆盖到的日期(盘中当日)→ 回落工作日推算。"""
    await tc.load_trading_calendar(_ok_source)
    # 2026-10-23(周五)超出集合最大日期 → 工作日 → True
    assert tc.is_trading_day(date(2026, 10, 23)) is True
    # 2026-10-24(周六)→ False
    assert tc.is_trading_day(date(2026, 10, 24)) is False


# ---------------- 数据源故障回落 ----------------

async def test_source_failure_falls_back_to_weekday_with_estimated():
    cal = await tc.load_trading_calendar(_boom_source)
    assert cal.source == tc.SOURCE_WEEKDAY_FALLBACK
    assert cal.estimated is True
    assert cal.reason and "数据源" in cal.reason

    hint = tc.trading_days_hint()
    assert hint["source"] == tc.SOURCE_WEEKDAY_FALLBACK
    assert hint["estimated"] is True
    assert hint["trade_date"] == date.today().isoformat() or hint["trade_date"]

    # 回落口径 = 工作日推算
    assert tc.is_trading_day(date(2026, 10, 20)) is True
    assert tc.is_trading_day(date(2026, 10, 18)) is False


async def test_empty_source_falls_back_to_weekday_with_estimated():
    cal = await tc.load_trading_calendar(_empty_source)
    assert cal.source == tc.SOURCE_WEEKDAY_FALLBACK
    assert cal.estimated is True
    assert cal.reason and "空" in cal.reason


async def test_missing_source_falls_back_to_weekday_with_estimated():
    cal = await tc.load_trading_calendar(None)
    assert cal.source == tc.SOURCE_WEEKDAY_FALLBACK
    assert cal.estimated is True
    assert cal.reason and "未注册" in cal.reason


async def test_hint_shape_is_stable():
    await tc.load_trading_calendar(_ok_source)
    hint = tc.trading_days_hint()
    assert set(hint) == {"source", "estimated", "trade_date"}
    assert hint["source"] == tc.SOURCE_INDEX_KLINE
    # 最近一个已确认的交易日
    assert hint["trade_date"] == "2026-10-22"


# ---------------- 缓存 ----------------

async def test_cache_reuses_source_within_same_day():
    calls = {"n": 0}

    async def _counting_source():
        calls["n"] += 1
        return list(TRADING_DAYS)

    await tc.load_trading_calendar(_counting_source)
    await tc.load_trading_calendar(_counting_source)
    assert calls["n"] == 1

    await tc.load_trading_calendar(_counting_source, force=True)
    assert calls["n"] == 2


# ---------------- 下一个交易日 ----------------

async def test_next_trading_day_uses_real_set():
    await tc.load_trading_calendar(_ok_source)
    assert tc.next_trading_day(date(2026, 10, 19)) == date(2026, 10, 20)
    assert tc.next_trading_day(date(2026, 10, 20)) == date(2026, 10, 21)
    # 集合最后一天之后 → 工作日顺延(2026-10-23 周五)
    assert tc.next_trading_day(date(2026, 10, 22)) == date(2026, 10, 23)


async def test_next_trading_day_skips_weekend_in_fallback():
    await tc.load_trading_calendar(_boom_source)
    # 2026-10-16(周五)→ 下一个工作日是 10-19(周一)
    assert tc.next_trading_day(date(2026, 10, 16)) == date(2026, 10, 19)


# ---------------- 纯函数边界(显式集合,零 IO) ----------------

def test_pure_functions_take_prepared_set():
    days = {date(2026, 10, 20), date(2026, 10, 21)}
    assert tc.is_trading_day_in(days, date(2026, 10, 20)) is True
    assert tc.is_trading_day_in(days, date(2026, 10, 19)) is False
    assert tc.next_trading_day_in(days, date(2026, 10, 19)) == date(2026, 10, 20)
    # 空集合 → 工作日口径
    assert tc.is_trading_day_in(set(), date(2026, 10, 18)) is False
    assert tc.is_trading_day_in(set(), date(2026, 10, 19)) is True
