"""event_factor_cache 仓储 (改动 A)

单表当日缓存; 写表条件: ifind 拉取成功.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import async_session
from app.models.orm import EventFactorCache


class EventFactorCacheRepo:
    @staticmethod
    async def get_today(trade_date: date) -> Optional[EventFactorCache]:
        async with async_session() as session:
            stmt = select(EventFactorCache).where(EventFactorCache.trade_date == trade_date)
            return (await session.execute(stmt)).scalars().first()

    @staticmethod
    async def upsert(
        trade_date: date,
        event_keywords_json: str,
        stock_codes_json: str,
        fetched_at: str,
        ifind_calls: int,
    ) -> EventFactorCache:
        async with async_session() as session:
            stmt = sqlite_insert(EventFactorCache).values(
                trade_date=trade_date,
                event_keywords_json=event_keywords_json,
                stock_codes_json=stock_codes_json,
                fetched_at=datetime.fromisoformat(fetched_at),
                ifind_calls=ifind_calls,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[EventFactorCache.trade_date],
                set_={
                    "event_keywords_json": stmt.excluded.event_keywords_json,
                    "stock_codes_json": stmt.excluded.stock_codes_json,
                    "fetched_at": stmt.excluded.fetched_at,
                    "ifind_calls": stmt.excluded.ifind_calls,
                    "updated_at": datetime.now(),
                },
            )
            await session.execute(stmt)
            await session.commit()
            row = (await session.execute(
                select(EventFactorCache).where(EventFactorCache.trade_date == trade_date)
            )).scalars().first()
            await session.refresh(row)
            return row


event_factor_cache_repo = EventFactorCacheRepo()

__all__ = ["event_factor_cache_repo", "EventFactorCacheRepo"]
