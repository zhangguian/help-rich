"""找股模块仓储(behavior_screener)

轻量封装:`behavior_signal_run` / `behavior_signal_pick` 两张表的 CRUD。
无业务逻辑,纯 IO。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select

from app.db import async_session
from app.models.orm import BehaviorSignalPick, BehaviorSignalRun

logger = logging.getLogger(__name__)


async def get_run_by_date(run_date: date) -> BehaviorSignalRun | None:
    """取指定日期的批次(若存在)。"""
    async with async_session() as session:
        stmt = select(BehaviorSignalRun).where(BehaviorSignalRun.run_date == run_date)
        return (await session.execute(stmt)).scalar_one_or_none()


async def get_latest_run() -> BehaviorSignalRun | None:
    """取最新一批次。"""
    async with async_session() as session:
        stmt = select(BehaviorSignalRun).order_by(BehaviorSignalRun.run_date.desc()).limit(1)
        return (await session.execute(stmt)).scalar_one_or_none()


async def list_runs(days: int = 10) -> list[BehaviorSignalRun]:
    """最近 N 天的批次(倒序)。"""
    async with async_session() as session:
        stmt = (
            select(BehaviorSignalRun)
            .order_by(BehaviorSignalRun.run_date.desc())
            .limit(days)
        )
        return list((await session.execute(stmt)).scalars().all())


async def upsert_run(
    run_date: date,
    *,
    pool_size: int,
    main_board_count: int,
    non_st_count: int,
    after_filters_count: int,
    candidates_considered: int,
    total_picks: int,
    elapsed_sec: float | None,
    note: str | None = None,
    hit_counts_json: str | None = None,
    data_as_of: date | None = None,
    is_intraday: bool = False,
) -> BehaviorSignalRun:
    """UPSERT 批次(同一天重跑覆盖)。"""
    async with async_session() as session:
        stmt = select(BehaviorSignalRun).where(BehaviorSignalRun.run_date == run_date)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.generated_at = datetime.now()
            existing.pool_size = pool_size
            existing.main_board_count = main_board_count
            existing.non_st_count = non_st_count
            existing.after_filters_count = after_filters_count
            existing.candidates_considered = candidates_considered
            existing.total_picks = total_picks
            existing.elapsed_sec = elapsed_sec
            existing.note = note
            existing.hit_counts_json = hit_counts_json
            existing.data_as_of = data_as_of
            existing.is_intraday = is_intraday
            await session.commit()
            await session.refresh(existing)
            return existing

        run = BehaviorSignalRun(
            run_date=run_date,
            generated_at=datetime.now(),
            pool_size=pool_size,
            main_board_count=main_board_count,
            non_st_count=non_st_count,
            after_filters_count=after_filters_count,
            candidates_considered=candidates_considered,
            total_picks=total_picks,
            elapsed_sec=elapsed_sec,
            note=note,
            hit_counts_json=hit_counts_json,
            data_as_of=data_as_of,
            is_intraday=is_intraday,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


async def replace_picks(run_id: int, picks: list[dict[str, Any]]) -> None:
    """覆盖某批次的全部命中记录(先删后插)。"""
    async with async_session() as session:
        await session.execute(
            delete(BehaviorSignalPick).where(BehaviorSignalPick.run_id == run_id)
        )
        for p in picks:
            signal_date = p.get("signal_date")
            if isinstance(signal_date, str):
                try:
                    signal_date = datetime.strptime(signal_date, "%Y-%m-%d").date()
                except ValueError:
                    continue
            if not isinstance(signal_date, date):
                continue
            metrics = p.get("metrics") or {}
            session.add(
                BehaviorSignalPick(
                    run_id=run_id,
                    run_date=p.get("run_date"),
                    stock_code=str(p.get("stock_code") or ""),
                    stock_name=p.get("stock_name"),
                    kind=str(p.get("kind") or ""),
                    signal_date=signal_date,
                    days_ago=int(p.get("days_ago") or 0),
                    score=float(p.get("score") or 0.0),
                    reason=str(p.get("reason") or ""),
                    metrics_json=json.dumps(metrics, ensure_ascii=False),
                    change_pct=p.get("change_pct"),
                )
            )
        await session.commit()


async def get_picks_by_run(run_id: int) -> list[BehaviorSignalPick]:
    """某批次的全部命中记录(按分数降序)。"""
    async with async_session() as session:
        stmt = (
            select(BehaviorSignalPick)
            .where(BehaviorSignalPick.run_id == run_id)
            .order_by(BehaviorSignalPick.score.desc())
        )
        return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "get_latest_run",
    "get_picks_by_run",
    "get_run_by_date",
    "list_runs",
    "replace_picks",
    "upsert_run",
]
