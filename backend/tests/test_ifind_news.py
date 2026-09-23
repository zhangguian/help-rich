"""ifind_news 包装层测试 (改动 C)"""
import pytest


@pytest.mark.asyncio
async def test_fetch_news_for_stock_returns_normalized():
    from app.data.ifind_news import fetch_news_for_stock
    from tests.conftest import mock_thsifind

    raw_news = [
        {"title": "公司发布新产品", "date": "2026-09-22"},
    ]
    raw_notices = [
        {"title": "2026 年第三季度业绩预告", "date": "2026-09-21"},
    ]
    with mock_thsifind(news=raw_news, notices=raw_notices):
        result = await fetch_news_for_stock(
            "600519.SH", start_date="2026-09-15", end_date="2026-09-22"
        )

    assert len(result["announcements"]) == 1
    assert len(result["news"]) == 1
    assert "fetched_at" in result


@pytest.mark.asyncio
async def test_fetch_news_for_stock_empty():
    from app.data.ifind_news import fetch_news_for_stock
    from tests.conftest import mock_thsifind

    with mock_thsifind(news=[], notices=[]):
        result = await fetch_news_for_stock("600519.SH", "2026-09-15", "2026-09-22")

    assert result["announcements"] == []
    assert result["news"] == []


@pytest.mark.asyncio
async def test_fetch_news_failure_raises():
    from app.data.ifind_news import fetch_news_for_stock, IfindUnavailable
    from tests.conftest import mock_thsifind

    with mock_thsifind(fail_on={"search_news"}):
        with pytest.raises(IfindUnavailable):
            await fetch_news_for_stock("600519.SH", "2026-09-15", "2026-09-22")


@pytest.mark.asyncio
async def test_fetch_notice_failure_raises():
    from app.data.ifind_news import fetch_news_for_stock, IfindUnavailable
    from tests.conftest import mock_thsifind

    with mock_thsifind(fail_on={"search_notice"}):
        with pytest.raises(IfindUnavailable):
            await fetch_news_for_stock("600519.SH", "2026-09-15", "2026-09-22")
