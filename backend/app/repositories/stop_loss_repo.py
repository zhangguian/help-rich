"""止损仓储(P5.1 实施)"""
from datetime import date
from typing import Optional

from sqlalchemy import select

from app.db import async_session
from app.models.orm import StopLoss


class StopLossRepository:
    async def _get_by_code(self, session, stock_code: str) -> Optional[StopLoss]:
        stmt = select(StopLoss).where(StopLoss.stock_code == stock_code)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def upsert(
        self,
        *,
        stock_code: str,
        stop_loss_price: str,
        enabled: bool = True,
        notify_sound: bool = True,
        notify_desktop: bool = True,
        notify_vibrate: bool = True,
    ) -> StopLoss:
        """设置或更新止损(同 stock_code 覆盖)"""
        async with async_session() as session:
            existing = await self._get_by_code(session, stock_code)
            if existing:
                existing.stop_loss_price = stop_loss_price
                existing.enabled = enabled
                existing.notify_sound = notify_sound
                existing.notify_desktop = notify_desktop
                existing.notify_vibrate = notify_vibrate
            else:
                existing = StopLoss(
                    stock_code=stock_code,
                    stop_loss_price=stop_loss_price,
                    enabled=enabled,
                    notify_sound=notify_sound,
                    notify_desktop=notify_desktop,
                    notify_vibrate=notify_vibrate,
                )
                session.add(existing)
            await session.commit()
            await session.refresh(existing)
            return existing

    async def list_all(self) -> list[StopLoss]:
        async with async_session() as session:
            stmt = select(StopLoss).order_by(StopLoss.stock_code)
            return list((await session.execute(stmt)).scalars().all())

    async def list_enabled(self) -> list[StopLoss]:
        async with async_session() as session:
            stmt = select(StopLoss).where(StopLoss.enabled.is_(True))
            return list((await session.execute(stmt)).scalars().all())

    async def remove(self, stock_code: str) -> bool:
        async with async_session() as session:
            row = await self._get_by_code(session, stock_code)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def mark_triggered(self, stock_code: str) -> bool:
        """标记今日已触发(P5.2 幂等:同日内已存在 last_triggered_at 则不更新)

        Returns True 表示新触发(本次是当日首次),False 表示同日重复
        """
        today = date.today()
        async with async_session() as session:
            row = await self._get_by_code(session, stock_code)
            if row is None:
                return False
            if row.last_triggered_at == today:
                return False  # 幂等:同日已触发,跳过
            row.last_triggered_at = today
            await session.commit()
            return True


stop_loss_repo = StopLossRepository()