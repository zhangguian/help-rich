"""自选股仓储(P2.1 实施)"""
from typing import Optional

from sqlalchemy import select

from app.db import async_session
from app.models.orm import Watchlist


class WatchlistRepository:
    async def _get_by_code(self, session, stock_code: str) -> Optional[Watchlist]:
        stmt = select(Watchlist).where(Watchlist.stock_code == stock_code)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def add(
        self,
        stock_code: str,
        stock_name: str | None = None,
        source: str = "manual",
        note: str | None = None,
    ) -> Watchlist:
        async with async_session() as session:
            existing = await self._get_by_code(session, stock_code)
            if existing:
                # 已在,更新 name + note
                if stock_name:
                    existing.stock_name = stock_name
                if note:
                    existing.note = note
                await session.commit()
                await session.refresh(existing)
                return existing
            row = Watchlist(
                stock_code=stock_code,
                stock_name=stock_name,
                source=source,
                note=note,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def list_all(self) -> list[Watchlist]:
        async with async_session() as session:
            stmt = select(Watchlist).order_by(Watchlist.added_at.desc())
            return list((await session.execute(stmt)).scalars().all())

    async def remove(self, stock_code: str) -> bool:
        async with async_session() as session:
            row = await self._get_by_code(session, stock_code)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def set_favorite(self, stock_code: str, is_favorite: bool) -> bool:
        """切换特别关注标记(v0.5)。返回是否实际修改"""
        async with async_session() as session:
            row = await self._get_by_code(session, stock_code)
            if row is None:
                return False
            if row.is_favorite == is_favorite:
                return True
            row.is_favorite = is_favorite
            await session.commit()
            return True

    async def contains(self, stock_code: str) -> bool:
        async with async_session() as session:
            return (await self._get_by_code(session, stock_code)) is not None


watchlist_repo = WatchlistRepository()
