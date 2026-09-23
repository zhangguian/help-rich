"""reflection_context_service 测试 (改动 C)"""
import pytest
from datetime import date
import json


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """建表(test DB 用 create_all,开发 DB 用 alembic).
    与 test_event_factor_service.py 同款 fixture,避免重复."""
    import asyncio
    from app.models import orm  # noqa: F401  # 注册 ReflectionContextCache 到 Base.metadata
    from app.db import engine, Base

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    yield


@pytest.mark.asyncio
async def test_build_reflection_context_aggregates_codes():
    from app.services.reflection_context_service import build_reflection_context
    from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo
    from tests.conftest import mock_thsifind

    today = date.today()
    # 给一只票各 mock 一条公告 + 一条新闻
    raw_news = [{"title": f"今日新闻 for 600519", "date": "2026-09-22"}]
    raw_notices = [{"title": f"今日公告 for 600519", "date": "2026-09-21"}]

    with mock_thsifind(news=raw_news, notices=raw_notices):
        row = await build_reflection_context(["600519.SH"], today)

    ctx = json.loads(row.context_json)
    assert ctx["announcements_count"] == 1
    assert ctx["news_count"] == 1
    assert "600519" in ctx["top_news_title"]


@pytest.mark.asyncio
async def test_build_failure_raises():
    from app.services.reflection_context_service import build_reflection_context
    from app.data.ifind_events import IfindUnavailable
    from tests.conftest import mock_thsifind
    from datetime import timedelta

    # 用未来日期避免被前一个测试写入的 today 缓存命中 (peer test_event_factor_service.py 同款 session-scoped DB)
    target_day = date.today() + timedelta(days=1)
    with mock_thsifind(fail_on={"search_news"}):
        with pytest.raises(IfindUnavailable):
            await build_reflection_context(["600519.SH"], target_day)


@pytest.mark.asyncio
async def test_get_summary_returns_none_when_missing():
    from app.services.reflection_context_service import get_reflection_context_summary
    from datetime import date, timedelta

    far_past = date.today() - timedelta(days=365)
    assert await get_reflection_context_summary(far_past) is None


@pytest.mark.asyncio
async def test_get_summary_returns_dict_when_cached():
    from app.services.reflection_context_service import build_reflection_context, get_reflection_context_summary
    from tests.conftest import mock_thsifind

    today = date.today()
    raw_news = [{"title": "今日新闻", "date": "2026-09-22"}]
    with mock_thsifind(news=raw_news, notices=[]):
        await build_reflection_context(["600519.SH"], today)

    summary = await get_reflection_context_summary(today)
    assert summary is not None
    assert summary["news_count"] == 1