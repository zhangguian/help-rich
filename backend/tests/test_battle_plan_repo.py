"""作战计划持久化层测试"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models.orm import BattlePlan, BattlePlanItem
from app.repositories.battle_plan_repo import battle_plan_repo


def _item(code="001896.SZ", kind="entry", price=9.62, direction="buy"):
    return {
        "stock_code": code, "stock_name": "豫能控股", "item_kind": kind,
        "direction": direction, "label": "建仓", "trigger_price": price,
        "trigger_condition": "回踩不破", "basis": ["依据 9.62"],
        "invalid_if": "跌破 9.33 作废", "status_now": "armed",
        "fulfillment": "pending", "fulfillment_note": "",
    }


@pytest.mark.asyncio
async def test_upsert_plan_creates_then_updates():
    pid1 = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-21", outlook_json='{"a":1}', review_json=None, meta_json=None)
    pid2 = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-21", outlook_json='{"a":2}', review_json=None, meta_json=None)
    assert pid1 == pid2
    async with async_session() as s:
        rows = (await s.execute(
            select(BattlePlan).where(BattlePlan.plan_date == "2026-10-21")
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].outlook_json == '{"a":2}'


@pytest.mark.asyncio
async def test_replace_items_is_idempotent():
    pid = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-22", outlook_json=None, review_json=None, meta_json=None)
    await battle_plan_repo.replace_items(pid, "2026-10-22", [_item(), _item(code="000807.SZ")])
    await battle_plan_repo.replace_items(pid, "2026-10-22", [_item()])
    items = await battle_plan_repo.get_items(pid)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_get_items_returns_fulfillment_fields():
    pid = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-23", outlook_json=None, review_json=None, meta_json=None)
    await battle_plan_repo.replace_items(pid, "2026-10-23", [_item()])
    items = await battle_plan_repo.get_items(pid)
    assert items[0]["fulfillment"] == "pending"
    assert items[0]["trigger_price"] == 9.62
    assert items[0]["basis"] == ["依据 9.62"]


@pytest.mark.asyncio
async def test_update_item_fulfillment():
    pid = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-24", outlook_json=None, review_json=None, meta_json=None)
    await battle_plan_repo.replace_items(pid, "2026-10-24", [_item()])
    items = await battle_plan_repo.get_items(pid)
    await battle_plan_repo.update_item_fulfillment(
        items[0]["id"], "touched", "价格已触及")
    again = await battle_plan_repo.get_items(pid)
    assert again[0]["fulfillment"] == "touched"
    assert again[0]["fulfillment_note"] == "价格已触及"


@pytest.mark.asyncio
async def test_get_plan_returns_none_for_missing_date():
    assert await battle_plan_repo.get_plan("1999-01-01") is None
