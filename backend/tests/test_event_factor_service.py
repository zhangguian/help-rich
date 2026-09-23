"""event_factor_service 业务编排测试"""
import pytest
from datetime import date


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """建表(test DB 用 create_all,开发 DB 用 alembic).
    与 test_event_factor_cache_repo.py 同款 fixture,避免重复."""
    import asyncio
    from app.models import orm  # noqa: F401  # 注册 EventFactorCache 到 Base.metadata
    from app.db import engine, Base

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    yield


@pytest.mark.asyncio
async def test_build_event_factor_cache_writes_to_repo():
    from app.services.event_factor_service import build_event_factor_cache
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo
    from tests.conftest import mock_thsifind

    today = date.today()
    raw = [
        {"title": "AI", "stocks": ["600519.SH"], "tags": ["AI"]},
    ]
    with mock_thsifind(trending_news=raw):
        row = await build_event_factor_cache(today)

    assert row.id is not None
    fetched = await event_factor_cache_repo.get_today(today)
    assert fetched is not None
    assert "600519.SH" in fetched.stock_codes_json


@pytest.mark.asyncio
async def test_build_event_factor_cache_skips_when_already_cached():
    """同日已有缓存 → 直接返, 不调 ifind"""
    from app.services.event_factor_service import build_event_factor_cache
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo
    from tests.conftest import mock_thsifind

    today = date.today()
    # 预填一条缓存
    await event_factor_cache_repo.upsert(
        trade_date=today,
        event_keywords_json='["预填"]',
        stock_codes_json='["000001.SZ"]',
        fetched_at="2026-09-22T00:00:00+08:00",
        ifind_calls=0,
    )

    # fail_on 触发 ifind, 但应该走缓存跳过
    with mock_thsifind(fail_on={"search_trending_news"}):
        row = await build_event_factor_cache(today)

    assert "预填" in row.event_keywords_json


@pytest.mark.asyncio
async def test_get_event_factor_codes_returns_set():
    from app.services.event_factor_service import get_event_factor_codes
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo

    today = date.today()
    await event_factor_cache_repo.upsert(
        trade_date=today,
        event_keywords_json='["AI"]',
        stock_codes_json='["600519.SH", "300750.SZ"]',
        fetched_at="2026-09-22T00:00:00+08:00",
        ifind_calls=1,
    )

    codes = await get_event_factor_codes(today)
    assert codes == {"600519.SH", "300750.SZ"}
