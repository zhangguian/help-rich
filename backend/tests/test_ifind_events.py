"""ifind_events 包装层测试"""
import pytest
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_fetch_trending_events_returns_normalized_dict():
    from app.data.ifind_events import fetch_trending_events
    from tests.conftest import mock_thsifind

    cn_tz = timezone(timedelta(hours=8))
    raw_events = [
        {"title": "AI 概念爆发", "stocks": ["600519.SH", "000001.SZ"], "tags": ["AI"]},
        {"title": "新能源补贴", "stocks": ["300750.SZ"], "tags": ["新能源"]},
    ]
    with mock_thsifind(trending_news=raw_events):
        result = await fetch_trending_events(size=20)

    assert isinstance(result, dict)
    assert "fetched_at" in result
    assert isinstance(result["event_keywords"], set)
    assert result["event_keywords"] == {"AI", "新能源"}
    assert isinstance(result["stock_codes"], set)
    assert result["stock_codes"] == {"600519.SH", "000001.SZ", "300750.SZ"}
    assert len(result["raw"]) == 2


@pytest.mark.asyncio
async def test_fetch_trending_events_empty():
    from app.data.ifind_events import fetch_trending_events
    from tests.conftest import mock_thsifind

    with mock_thsifind(trending_news=[]):
        result = await fetch_trending_events(size=20)

    assert result["event_keywords"] == set()
    assert result["stock_codes"] == set()
    assert result["raw"] == []


@pytest.mark.asyncio
async def test_fetch_trending_events_failure_raises():
    from app.data.ifind_events import fetch_trending_events, IfindUnavailable
    from tests.conftest import mock_thsifind

    with mock_thsifind(fail_on={"search_trending_news"}):
        with pytest.raises(IfindUnavailable):
            await fetch_trending_events(size=20)
