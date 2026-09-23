"""验证 mock_thsifind fixture 行为"""
import pytest


@pytest.mark.asyncio
async def test_mock_thsifind_search_trending_news_default():
    from tests.conftest import mock_thsifind
    with mock_thsifind() as m:
        result = await m.search_trending_news(time_scope="24小时", size=5)
        assert isinstance(result, list)


@pytest.mark.asyncio
async def test_mock_thsifind_search_securities_default():
    from tests.conftest import mock_thsifind
    with mock_thsifind() as m:
        result = await m.search_securities(market="A股", query="扣非ROE>0")
        assert isinstance(result, list)
