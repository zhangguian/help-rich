"""event_factor_cache 仓储层测试"""
import pytest
from datetime import date, timedelta


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """conftest 把 DATABASE_URL 指向临时空文件,test repo 需要建表。
    用 Base.metadata.create_all 同步建表(开发 DB 用 alembic,test DB 用 create_all 避免启动子进程)。
    必须先 import orm 才能注册 model metadata。
    """
    import asyncio
    from app.models import orm  # noqa: F401  # 注册 EventFactorCache 到 Base.metadata
    from app.db import engine, Base

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    yield


@pytest.mark.asyncio
async def test_upsert_and_get_today():
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo

    today = date.today()
    row = await event_factor_cache_repo.upsert(
        trade_date=today,
        event_keywords_json='["AI", "新能源"]',
        stock_codes_json='["600519.SH", "300750.SZ"]',
        fetched_at="2026-09-22T22:00:00+08:00",
        ifind_calls=1,
    )
    assert row.id is not None

    got = await event_factor_cache_repo.get_today(today)
    assert got is not None
    assert got.trade_date == today
    assert got.ifind_calls == 1


@pytest.mark.asyncio
async def test_get_today_missing_returns_none():
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo

    far_past = date.today() - timedelta(days=365)
    got = await event_factor_cache_repo.get_today(far_past)
    assert got is None
