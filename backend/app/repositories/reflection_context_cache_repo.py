"""reflection_context_cache 仓储 (改动 C)

单表当日缓存; 写表条件: ifind 拉取成功.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import async_session
from app.models.orm import ReflectionContextCache


class ReflectionContextCacheRepo:
    @staticmethod
    async def get_today(fetch_date: date) -> Optional[ReflectionContextCache]:
        async with async_session() as session:
            stmt = select(ReflectionContextCache).where(ReflectionContextCache.fetch_date == fetch_date)
            return (await session.execute(stmt)).scalars().first()

    @staticmethod
    async def upsert(
        fetch_date: date,
        context_json: str,
        fetched_at: str,
        ifind_calls: int,
    ) -> ReflectionContextCache:
        async with async_session() as session:
            stmt = sqlite_insert(ReflectionContextCache).values(
                fetch_date=fetch_date,
                context_json=context_json,
                fetched_at=datetime.fromisoformat(fetched_at),
                ifind_calls=ifind_calls,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[ReflectionContextCache.fetch_date],
                set_={
                    "context_json": stmt.excluded.context_json,
                    "fetched_at": stmt.excluded.fetched_at,
                    "ifind_calls": stmt.excluded.ifind_calls,
                    "updated_at": datetime.now(),
                },
            )
            await session.execute(stmt)
            await session.commit()
            row = (await session.execute(
                select(ReflectionContextCache).where(ReflectionContextCache.fetch_date == fetch_date)
            )).scalars().first()
            await session.refresh(row)
            return row


reflection_context_cache_repo = ReflectionContextCacheRepo()

__all__ = ["reflection_context_cache_repo", "ReflectionContextCacheRepo"]