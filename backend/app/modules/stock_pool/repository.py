"""滚动池持久化(作战计划 v2)

一行 = 一只进过全市场滚动池的股票。

**幂等**:所有写操作按 `stock_code` upsert —— 同一天重复生成日报不会
产生第二行,也不会把已判定过的 `miss_streak` 清零。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db import async_session
from app.models.orm import BattlePlanPool


def _row_to_member(r: BattlePlanPool) -> dict[str, Any]:
    return {
        "stock_code": r.stock_code,
        "stock_name": r.stock_name,
        "active": bool(r.active),
        "joined_on": r.joined_on,
        "miss_streak": int(r.miss_streak or 0),
        "last_evaluated_on": r.last_evaluated_on,
        "last_status": r.last_status,
        "last_score": r.last_score,
        "last_reason": r.last_reason,
    }


class StockPoolRepo:
    """滚动池仓储。所有写操作幂等。"""

    async def list_members(self, active_only: bool = True) -> list[dict[str, Any]]:
        """池成员列表

        `active_only=True` 只返回在池的;`False` 返回全部(含已剔除的历史行)。
        """
        async with async_session() as session:
            stmt = select(BattlePlanPool).order_by(BattlePlanPool.id)
            if active_only:
                stmt = stmt.where(BattlePlanPool.active.is_(True))
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_member(r) for r in rows]

    async def upsert_members(self, rows: list[dict[str, Any]]) -> None:
        """按 stock_code upsert 池成员状态(不存在的插入,已存在的更新)

        ⚠️ **不动 `joined_on`**(除新建行)—— 它记的是「这只票什么时候进池」,
        重新生成同一天的日报不应该把它改掉(否则「连续关注天数」之类的
        衍生信息会随重跑漂移)。
        """
        if not rows:
            return
        async with async_session() as session:
            codes = [str(r.get("stock_code") or "") for r in rows]
            existing = (
                (
                    await session.execute(
                        select(BattlePlanPool).where(BattlePlanPool.stock_code.in_(codes))
                    )
                )
                .scalars()
                .all()
            )
            by_code = {r.stock_code: r for r in existing}
            for item in rows:
                code = str(item.get("stock_code") or "")
                if not code:
                    continue
                row = by_code.get(code)
                if row is None:
                    row = BattlePlanPool(
                        stock_code=code,
                        joined_on=str(item.get("joined_on") or ""),
                    )
                    session.add(row)
                    by_code[code] = row
                row.stock_name = item.get("stock_name") or row.stock_name
                row.active = bool(item.get("active", True))
                row.miss_streak = int(item.get("miss_streak") or 0)
                row.last_evaluated_on = item.get("last_evaluated_on")
                row.last_status = item.get("last_status")
                row.last_score = item.get("last_score")
                row.last_reason = item.get("last_reason")
            await session.commit()


stock_pool_repo = StockPoolRepo()

__all__ = ["stock_pool_repo", "StockPoolRepo"]
