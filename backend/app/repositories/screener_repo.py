"""盘后选股仓储(v2.6)

轻量封装:4 张表的 CRUD。无业务逻辑,纯 IO。
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.models.orm import (
    IndexConstituent,
    ScreenerLlmPick,
    ScreenerPick,
    ScreenerRun,
    ScreenerWatchlist,
    ScreenerWatchlistDaily,
)

logger = logging.getLogger(__name__)


# ============================================================
# IndexConstituent
# ============================================================


async def get_constituents(index_codes: tuple[str, ...] | None = None) -> list[IndexConstituent]:
    """拉所有(或指定指数)成分股 — 业务层需去重"""
    async with async_session() as session:
        stmt = select(IndexConstituent)
        if index_codes:
            stmt = stmt.where(IndexConstituent.index_code.in_(index_codes))
        return list((await session.execute(stmt)).scalars().all())


# ============================================================
# ScreenerRun
# ============================================================


async def get_run_by_date(run_date: date) -> ScreenerRun | None:
    """取指定日期的批次(若存在)— 重跑前判断用"""
    async with async_session() as session:
        stmt = select(ScreenerRun).where(ScreenerRun.run_date == run_date)
        return (await session.execute(stmt)).scalar_one_or_none()


async def get_latest_run() -> ScreenerRun | None:
    """取最新一批次(默认今日,若今日无则上一交易日)"""
    async with async_session() as session:
        stmt = select(ScreenerRun).order_by(ScreenerRun.run_date.desc()).limit(1)
        return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_run(
    run_date: date,
    scoring_version: str,
    pool_size: int,
    total_picks: int,
    elapsed_sec: float | None,
    note: str | None = None,
) -> ScreenerRun:
    """UPSERT 批次(同一天重跑覆盖)"""
    async with async_session() as session:
        stmt = select(ScreenerRun).where(ScreenerRun.run_date == run_date)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.scoring_version = scoring_version
            existing.pool_size = pool_size
            existing.total_picks = total_picks
            existing.elapsed_sec = elapsed_sec
            existing.generated_at = datetime.now()
            existing.note = note
            await session.commit()
            await session.refresh(existing)
            return existing
        run = ScreenerRun(
            run_date=run_date,
            scoring_version=scoring_version,
            pool_size=pool_size,
            total_picks=total_picks,
            elapsed_sec=elapsed_sec,
            generated_at=datetime.now(),
            note=note,
        )
        session.add(run)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return await upsert_run(
                run_date=run_date,
                scoring_version=scoring_version,
                pool_size=pool_size,
                total_picks=total_picks,
                elapsed_sec=elapsed_sec,
                note=note,
            )
        await session.refresh(run)
        return run


# ============================================================
# ScreenerPick
# ============================================================


async def get_picks_by_run(run_id: int) -> list[ScreenerPick]:
    """取某批次的所有候选(按 rank 升序)"""
    async with async_session() as session:
        stmt = (
            select(ScreenerPick)
            .where(ScreenerPick.run_id == run_id)
            .order_by(ScreenerPick.rank.asc())
        )
        return list((await session.execute(stmt)).scalars().all())


async def replace_picks(run_id: int, picks: list[dict[str, Any]]) -> None:
    """删除该 run_id 旧 picks,重新插入(覆盖式重跑)"""
    async with async_session() as session:
        # 一次性 delete + insert 在同一 session
        await session.execute(
            delete(ScreenerPick).where(ScreenerPick.run_id == run_id)
        )
        await session.flush()  # 让 delete 立即执行
        for p in picks:
            session.add(ScreenerPick(
                run_id=run_id,
                rank=p["rank"],
                stock_code=p["stock_code"],
                stock_name=p["stock_name"],
                score=float(p["score"]),
                main_net_inflow_yi=p.get("main_net_inflow_yi"),
                volume_ratio=p.get("volume_ratio"),
                change_pct=p.get("change_pct"),
                turnover_proxy=p.get("turnover_proxy"),
                consecutive_up_days=int(p.get("consecutive_up_days", 0)),
                sector=p.get("sector"),
                sector_inflow_rank=p.get("sector_inflow_rank"),
                triggered_rules=json.dumps(p.get("triggered_rules", []), ensure_ascii=False),
                reason=p.get("reason"),
                fundamental_filter_status=p.get("fundamental_filter_status"),
            ))
        await session.commit()


# ============================================================
# ScreenerLlmPick(每 run_id 唯一)
# ============================================================


async def get_llm_pick_by_run(run_id: int) -> ScreenerLlmPick | None:
    async with async_session() as session:
        stmt = select(ScreenerLlmPick).where(ScreenerLlmPick.run_id == run_id)
        return (await session.execute(stmt)).scalar_one_or_none()


async def save_llm_pick(
    run_id: int,
    model: str,
    picks_json: list[dict[str, Any]],
    summary: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost_estimate: float | None,
    error: str | None,
    status: str,
) -> ScreenerLlmPick:
    """保存 LLM 评选结果(同 run_id 唯一,已存在则覆盖)"""
    async with async_session() as session:
        stmt = select(ScreenerLlmPick).where(ScreenerLlmPick.run_id == run_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            existing.model = model
            existing.picks_json = json.dumps(picks_json, ensure_ascii=False)
            existing.summary = summary
            existing.prompt_tokens = prompt_tokens
            existing.completion_tokens = completion_tokens
            existing.cost_estimate = cost_estimate
            existing.error = error
            existing.status = status
            existing.requested_at = datetime.now()
            await session.commit()
            await session.refresh(existing)
            return existing
        row = ScreenerLlmPick(
            run_id=run_id,
            model=model,
            picks_json=json.dumps(picks_json, ensure_ascii=False),
            summary=summary,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_estimate=cost_estimate,
            error=error,
            status=status,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


# ============================================================
# ScreenerWatchlist(观察池)
# ============================================================


async def get_watchlist_by_code(stock_code: str) -> ScreenerWatchlist | None:
    """查某只股的观察池记录"""
    async with async_session() as session:
        stmt = select(ScreenerWatchlist).where(
            ScreenerWatchlist.stock_code == stock_code
        )
        return (await session.execute(stmt)).scalar_one_or_none()


async def list_watchlist_codes(status: str = "active") -> set[str]:
    """返回所有 active 观察池的 stock_code 集合(供 ScreenerPick.is_watched 标注)"""
    async with async_session() as session:
        stmt = select(ScreenerWatchlist.stock_code).where(
            ScreenerWatchlist.status == status
        )
        return {row[0] for row in (await session.execute(stmt)).all()}


async def list_watchlist(status: str = "active") -> list[ScreenerWatchlist]:
    """列出观察池(按标记日期倒序)"""
    async with async_session() as session:
        stmt = (
            select(ScreenerWatchlist)
            .where(ScreenerWatchlist.status == status)
            .order_by(ScreenerWatchlist.marked_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())


async def add_watchlist(
    stock_code: str,
    stock_name: str,
    marked_at,
    marked_close: str | None = None,
    marked_change_pct: str | None = None,
    note: str | None = None,
) -> ScreenerWatchlist:
    """UPSERT 标记(同 stock_code 已存在则跳过,不覆盖)"""
    async with async_session() as session:
        existing = (
            await session.execute(
                select(ScreenerWatchlist).where(
                    ScreenerWatchlist.stock_code == stock_code
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        row = ScreenerWatchlist(
            stock_code=stock_code,
            stock_name=stock_name,
            marked_at=marked_at,
            marked_close=marked_close,
            marked_change_pct=marked_change_pct,
            note=note,
            status="active",
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return await get_watchlist_by_code(stock_code)
        await session.refresh(row)
        return row


async def remove_watchlist(stock_code: str) -> bool:
    """取消标记(物理删除)— 返回是否真删了"""
    async with async_session() as session:
        existing = (
            await session.execute(
                select(ScreenerWatchlist).where(
                    ScreenerWatchlist.stock_code == stock_code
                )
            )
        ).scalar_one_or_none()
        if not existing:
            return False
        await session.delete(existing)
        await session.commit()
        return True


# ============================================================
# ScreenerWatchlistDaily(逐日记录)
# ============================================================


async def list_daily_records(watchlist_id: int) -> list[ScreenerWatchlistDaily]:
    """取某观察池的全部逐日记录(按日期升序)"""
    async with async_session() as session:
        stmt = (
            select(ScreenerWatchlistDaily)
            .where(ScreenerWatchlistDaily.watchlist_id == watchlist_id)
            .order_by(ScreenerWatchlistDaily.trade_date.asc())
        )
        return list((await session.execute(stmt)).scalars().all())


async def list_latest_records(watchlist_ids: list[int]) -> dict[int, ScreenerWatchlistDaily | None]:
    """批量取每只观察池的最新一条逐日记录(用于渲染表格"最新表现"列)"""
    if not watchlist_ids:
        return {}
    # 用子查询:每组 watchlist_id 取 max(trade_date)
    from sqlalchemy import func
    async with async_session() as session:
        sub = (
            select(
                ScreenerWatchlistDaily.watchlist_id.label("wid"),
                func.max(ScreenerWatchlistDaily.trade_date).label("maxd"),
            )
            .where(ScreenerWatchlistDaily.watchlist_id.in_(watchlist_ids))
            .group_by(ScreenerWatchlistDaily.watchlist_id)
            .subquery()
        )
        stmt = (
            select(ScreenerWatchlistDaily)
            .join(
                sub,
                (ScreenerWatchlistDaily.watchlist_id == sub.c.wid)
                & (ScreenerWatchlistDaily.trade_date == sub.c.maxd),
            )
        )
        rows = list((await session.execute(stmt)).scalars().all())
        by_id = {r.watchlist_id: r for r in rows}
        # watchlist_ids 里没记录也要返 None
        return {wid: by_id.get(wid) for wid in watchlist_ids}


async def list_two_latest_records(
    watchlist_ids: list[int],
) -> dict[int, list[ScreenerWatchlistDaily]]:
    """每只观察池返最近 2 条 daily record(用于计算今日单日涨跌)

    Returns: {watchlist_id: [latest, prev]} — 按日期降序;不足 2 条返短列表
    """
    if not watchlist_ids:
        return {}
    from sqlalchemy import func as _f
    async with async_session() as session:
        # 子查询:row_number 按 watchlist_id 分区取最近 2 条
        from sqlalchemy import over, select as _sel
        rn = over(
            _f.row_number(),
            partition_by=ScreenerWatchlistDaily.watchlist_id,
            order_by=ScreenerWatchlistDaily.trade_date.desc(),
        )
        sub = (
            _sel(
                ScreenerWatchlistDaily.watchlist_id.label("wid"),
                ScreenerWatchlistDaily.trade_date.label("td"),
                ScreenerWatchlistDaily.pct_from_marked.label("pct"),
                rn.label("rn"),
            )
            .where(ScreenerWatchlistDaily.watchlist_id.in_(watchlist_ids))
            .subquery()
        )
        rows = list(
            (
                await session.execute(
                    _sel(sub.c.wid, sub.c.td, sub.c.pct)
                    .where(sub.c.rn <= 2)
                    .order_by(sub.c.wid, sub.c.rn)
                )
            ).all()
        )
    out: dict[int, list[dict]] = {wid: [] for wid in watchlist_ids}
    for wid, td, pct in rows:
        out.setdefault(wid, []).append({
            "watchlist_id": wid,
            "trade_date": td,
            "pct_from_marked": pct,
        })
    return out


async def upsert_daily_records(watchlist_id: int, records: list[dict]) -> int:
    """批量 upsert 逐日记录

    records: [{trade_date, open_price, high_price, low_price, close_price, volume, pct_from_marked}, ...]
    Returns: 新写入行数
    """
    if not records:
        return 0
    added = 0
    async with async_session() as session:
        for r in records:
            td = r["trade_date"]
            # 单条 session.add + commit + 处理 IntegrityError(已存在则 update)
            try:
                session.add(ScreenerWatchlistDaily(
                    watchlist_id=watchlist_id,
                    trade_date=td,
                    open_price=r["open_price"],
                    high_price=r["high_price"],
                    low_price=r["low_price"],
                    close_price=r["close_price"],
                    volume=int(r.get("volume", 0)),
                    pct_from_marked=r.get("pct_from_marked"),
                ))
                await session.commit()
                added += 1
            except IntegrityError:
                await session.rollback()
                # 已存在 → update(可能 pct_from_marked 重算)
                existing = (
                    await session.execute(
                        select(ScreenerWatchlistDaily).where(
                            ScreenerWatchlistDaily.watchlist_id == watchlist_id,
                            ScreenerWatchlistDaily.trade_date == td,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.close_price = r["close_price"]
                    existing.pct_from_marked = r.get("pct_from_marked")
                    await session.commit()
    return added


# ============================================================
# v2.6.1:reason 列补算(一次性历史数据修复)
# ============================================================


async def backfill_reasons() -> dict:
    """遍历所有 screener_picks,把 reason 为空的用已存的因子数据重算。

    算法:从 ORM row 重建 StockFeatures → 调 build_reason(无 bd,
    仅用因子数据拼接 — bd.triggered_rules 暂未重算,板块聚集奖励不会补回)。
    """
    from app.services.scoring import StockFeatures, build_reason

    async with async_session() as session:
        from sqlalchemy import select
        stmt = select(ScreenerPick).where(ScreenerPick.reason.is_(None))
        rows = list((await session.execute(stmt)).scalars().all())

    updated = 0
    skipped = 0
    for r in rows:
        feat = StockFeatures(
            stock_code=r.stock_code,
            stock_name=r.stock_name,
            main_net_inflow_yi=r.main_net_inflow_yi or 0.0,
            volume_ratio=r.volume_ratio or 0.0,
            change_pct=r.change_pct or 0.0,
            turnover_yi=r.turnover_proxy or 0.0,
            consecutive_up_days=r.consecutive_up_days,
            sector=r.sector,
            sector_inflow_rank=r.sector_inflow_rank,
        )
        new_reason = build_reason(feat)
        if not new_reason:
            skipped += 1
            continue
        async with async_session() as session:
            from sqlalchemy import select as _sel
            stmt = _sel(ScreenerPick).where(ScreenerPick.id == r.id)
            row = (await session.execute(stmt)).scalar_one()
            row.reason = new_reason
            await session.commit()
        updated += 1
    return {"total_missing": len(rows), "updated": updated, "skipped": skipped}