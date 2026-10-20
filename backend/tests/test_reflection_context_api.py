"""reflection_context API 端点测试 (改动 C)"""
import pytest
from datetime import date


@pytest.fixture(scope="session", autouse=True)
def _create_tables():
    """建表(test DB 用 create_all,开发 DB 用 alembic).
    与 test_reflection_context_service.py 同款 fixture,避免重复."""
    import asyncio
    from app.models import orm  # noqa: F401  # 注册 ReflectionContextCache 等到 Base.metadata
    from app.db import engine, Base

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    yield


@pytest.mark.asyncio
async def test_get_reflection_context_returns_summary():
    from app.services.reflection_context_service import build_reflection_context
    from tests.conftest import mock_thsifind

    today = date.today()
    raw_news = [{"title": "今日新闻", "date": "2026-09-22"}]
    with mock_thsifind(news=raw_news, notices=[]):
        await build_reflection_context(["600519.SH"], today)

    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/reflection-context?date={today.isoformat()}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["news_count"] == 1


@pytest.mark.asyncio
async def test_get_reflection_context_returns_503_on_ifind_failure():
    from decimal import Decimal
    from datetime import date, timedelta
    from tests.conftest import mock_thsifind

    # 使用未来日期避免 cache 冲突 (与其他 test 在同一 session-scoped DB 上跑)
    target_day = date.today() + timedelta(days=1)
    # seed 1 只持仓,使 _collect_relevant_codes 返回非空集,确保 build_reflection_context 真的调用 ifind
    from app.modules.portfolio.service import upsert_position
    await upsert_position(
        stock_code="600519.SH", shares=100, cost_price=Decimal("1000.00"), stock_name="贵州茅台",
    )

    with mock_thsifind(fail_on={"search_news"}):
        from httpx import AsyncClient, ASGITransport
        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/reflection-context?date={target_day.isoformat()}")

    assert resp.status_code == 503
    assert "ifind" in resp.json()["detail"].lower() or "ifind" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_reflection_context_returns_400_on_bad_date():
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/reflection-context?date=not-a-date")

    assert resp.status_code == 400