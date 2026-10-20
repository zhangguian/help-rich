"""选股因子权重持久化(仓储层)。"""
from __future__ import annotations

from sqlalchemy import select

from app.db import async_session
from app.models.orm import ScreenerWeight


class ScreenerWeightRepo:
    async def list_rows(self) -> list[dict]:
        async with async_session() as s:
            stmt = select(ScreenerWeight)
            return [
                {"factor_name": r.factor_name, "weight": r.weight, "enabled": r.enabled}
                for r in (await s.execute(stmt)).scalars().all()
            ]

    async def upsert_many(self, items: list[dict]) -> None:
        """批量写入(upsert 语义)。items: [{factor_name, weight, enabled}]"""
        from datetime import datetime

        async with async_session() as s:
            for item in items:
                key = item["factor_name"]
                row = await s.get(ScreenerWeight, key)
                if row is None:
                    s.add(
                        ScreenerWeight(
                            factor_name=key,
                            weight=float(item["weight"]),
                            enabled=bool(item.get("enabled", True)),
                        )
                    )
                else:
                    row.weight = float(item["weight"])
                    row.enabled = bool(item.get("enabled", True))
                    row.updated_at = datetime.now()
            await s.commit()

    async def reset_to_default(self) -> None:
        """清空自定义权重,回落 config 常量。"""
        from sqlalchemy import delete

        async with async_session() as s:
            await s.execute(delete(ScreenerWeight))
            await s.commit()


screener_weight_repo = ScreenerWeightRepo()

__all__ = ["ScreenerWeightRepo", "screener_weight_repo"]
