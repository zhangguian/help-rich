"""价格提醒持久化(仓储层)。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.orm import PriceAlert, PriceAlertTrigger


class PriceAlertRepo:
    """价格提醒仓储。所有方法自带 session,调用方不需要管事务。"""

    async def list_all(self, stock_code: str | None = None) -> list[PriceAlert]:
        async with async_session() as s:
            stmt = select(PriceAlert)
            if stock_code:
                stmt = stmt.where(PriceAlert.stock_code == stock_code)
            stmt = stmt.order_by(PriceAlert.id.desc())
            return list((await s.execute(stmt)).scalars().all())

    async def list_enabled_active(self) -> list[PriceAlert]:
        """调度器用:启用 + 未过期的规则。"""
        now = datetime.now()
        async with async_session() as s:
            stmt = select(PriceAlert).where(PriceAlert.enabled.is_(True))
            stmt = stmt.where(
                (PriceAlert.expires_at.is_(None)) | (PriceAlert.expires_at > now)
            )
            return list((await s.execute(stmt)).scalars().all())

    async def get(self, alert_id: int) -> PriceAlert | None:
        async with async_session() as s:
            return await s.get(PriceAlert, alert_id)

    async def create(self, **kwargs) -> int:
        async with async_session() as s:
            row = PriceAlert(**kwargs)
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return row.id

    async def update(self, alert_id: int, **kwargs) -> bool:
        async with async_session() as s:
            row = await s.get(PriceAlert, alert_id)
            if row is None:
                return False
            for k, v in kwargs.items():
                setattr(row, k, v)
            await s.commit()
            return True

    async def delete(self, alert_id: int) -> bool:
        async with async_session() as s:
            row = await s.get(PriceAlert, alert_id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True

    async def record_trigger(
        self,
        alert_id: int,
        status: str,
        snapshot: dict | None = None,
        results: list | None = None,
    ) -> None:
        import json

        async with async_session() as s:
            s.add(
                PriceAlertTrigger(
                    alert_id=alert_id,
                    triggered_at=datetime.now(),
                    status=status,
                    snapshot_json=json.dumps(snapshot, ensure_ascii=False) if snapshot else None,
                    results_json=json.dumps(results, ensure_ascii=False, default=str)
                    if results
                    else None,
                )
            )
            # 同步计数
            row = await s.get(PriceAlert, alert_id)
            if row is not None:
                row.triggered_count = (row.triggered_count or 0) + 1
                row.last_triggered_at = datetime.now()
            await s.commit()

    async def list_triggers(self, alert_id: int, limit: int = 20) -> list[PriceAlertTrigger]:
        async with async_session() as s:
            stmt = (
                select(PriceAlertTrigger)
                .where(PriceAlertTrigger.alert_id == alert_id)
                .order_by(PriceAlertTrigger.triggered_at.desc())
                .limit(limit)
            )
            return list((await s.execute(stmt)).scalars().all())


price_alert_repo = PriceAlertRepo()

__all__ = ["PriceAlertRepo", "price_alert_repo"]
