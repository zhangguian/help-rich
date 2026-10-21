"""作战计划持久化(日报 + 逐票预案)"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select, update

from app.db import async_session
from app.models.orm import BattlePlan, BattlePlanItem


def _dumps(v: Any) -> str | None:
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _row_to_item(r: BattlePlanItem) -> dict[str, Any]:
    return {
        "id": r.id,
        "plan_id": r.plan_id,
        "plan_date": r.plan_date,
        "stock_code": r.stock_code,
        "stock_name": r.stock_name,
        "item_kind": r.item_kind,
        "direction": r.direction,
        "label": r.label,
        "trigger_price": r.trigger_price,
        "trigger_condition": r.trigger_condition,
        "basis": _loads(r.basis_json) or [],
        "invalid_if": r.invalid_if or "",
        "status_now": r.status_now,
        "source": r.source or "",
        "fulfillment": r.fulfillment or "pending",
        "fulfillment_note": r.fulfillment_note or "",
    }


class BattlePlanRepo:
    """日报仓储。所有方法都是幂等的。"""

    async def upsert_plan(
        self, plan_date: str, outlook_json: str | None,
        review_json: str | None, meta_json: str | None,
    ) -> int:
        async with async_session() as session:
            row = (await session.execute(
                select(BattlePlan).where(BattlePlan.plan_date == plan_date)
            )).scalar_one_or_none()
            if row is None:
                row = BattlePlan(plan_date=plan_date)
                session.add(row)
            row.outlook_json = outlook_json
            row.review_json = review_json
            row.meta_json = meta_json
            await session.commit()
            return row.id

    async def get_plan(self, plan_date: str) -> dict[str, Any] | None:
        async with async_session() as session:
            row = (await session.execute(
                select(BattlePlan).where(BattlePlan.plan_date == plan_date)
            )).scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "plan_date": row.plan_date,
                "outlook": _loads(row.outlook_json),
                "review": _loads(row.review_json),
                "meta": _loads(row.meta_json),
            }

    async def replace_items(
        self, plan_id: int, plan_date: str, items: list[dict[str, Any]]
    ) -> list[int]:
        """整体替换某日报的预案项(先删后插)"""
        async with async_session() as session:
            await session.execute(
                delete(BattlePlanItem).where(BattlePlanItem.plan_id == plan_id)
            )
            ids: list[int] = []
            for it in items or []:
                row = BattlePlanItem(
                    plan_id=plan_id,
                    plan_date=plan_date,
                    stock_code=str(it.get("stock_code") or ""),
                    stock_name=it.get("stock_name"),
                    item_kind=str(it.get("item_kind") or "watch"),
                    direction=str(it.get("direction") or "none"),
                    label=str(it.get("label") or ""),
                    trigger_price=it.get("trigger_price"),
                    trigger_condition=str(it.get("trigger_condition") or ""),
                    basis_json=_dumps(it.get("basis") or []),
                    invalid_if=it.get("invalid_if") or "",
                    status_now=str(it.get("status_now") or "armed"),
                    source=it.get("source") or None,
                    fulfillment=str(it.get("fulfillment") or "pending"),
                    fulfillment_note=it.get("fulfillment_note") or "",
                )
                session.add(row)
                await session.flush()
                ids.append(row.id)
            await session.commit()
            return ids

    async def get_items(self, plan_id: int) -> list[dict[str, Any]]:
        async with async_session() as session:
            rows = (await session.execute(
                select(BattlePlanItem)
                .where(BattlePlanItem.plan_id == plan_id)
                .order_by(BattlePlanItem.id)
            )).scalars().all()
            return [_row_to_item(r) for r in rows]

    async def update_item_fulfillment(
        self, item_id: int, fulfillment: str, note: str = ""
    ) -> None:
        async with async_session() as session:
            await session.execute(
                update(BattlePlanItem)
                .where(BattlePlanItem.id == item_id)
                .values(fulfillment=fulfillment, fulfillment_note=note)
            )
            await session.commit()

    async def list_plan_dates(self, limit: int = 30) -> list[str]:
        async with async_session() as session:
            rows = (await session.execute(
                select(BattlePlan.plan_date)
                .order_by(BattlePlan.plan_date.desc())
                .limit(limit)
            )).scalars().all()
            return list(rows)


battle_plan_repo = BattlePlanRepo()

__all__ = ["battle_plan_repo", "BattlePlanRepo"]
