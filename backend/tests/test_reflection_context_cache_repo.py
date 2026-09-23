"""reflection_context_cache 仓储测试 (改动 C)"""
import pytest
from datetime import date


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """conftest 把 DATABASE_URL 指向临时空文件,test repo 需要建表。

    用 Base.metadata.create_all 同步建表(开发 DB 用 alembic,test DB 用 create_all 避免启动子进程)。
    必须先 import orm 才能注册 model metadata。
    """
    import asyncio
    from app.models import orm  # noqa: F401  # 注册 ReflectionContextCache 到 Base.metadata
    from app.db import engine, Base

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    yield


@pytest.mark.asyncio
async def test_upsert_and_get_today():
    from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo

    today = date.today()
    row = await reflection_context_cache_repo.upsert(
        fetch_date=today,
        context_json='{"announcements_count": 1, "news_count": 2, "top_news_title": "test"}',
        fetched_at="2026-09-22T22:00:00+08:00",
        ifind_calls=2,
    )
    assert row.id is not None

    got = await reflection_context_cache_repo.get_today(today)
    assert got is not None
    assert got.fetch_date == today
    assert got.ifind_calls == 2


@pytest.mark.asyncio
async def test_get_today_missing_returns_none():
    from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo
    from datetime import date, timedelta

    far_past = date.today() - timedelta(days=365)
    assert await reflection_context_cache_repo.get_today(far_past) is None