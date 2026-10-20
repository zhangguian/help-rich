"""数据保留与裁剪(2026-10 新增,2026-10-17 修正)。

背景:`fund_flow` 调度器每 60s 拉 3 个市场 × Top50 ≈ 150 条/分钟
(≈21.6 万条/天),而前端只通过 `list_recent(stock_code, limit=30)` 读取
"每只股票最近 30 条"(约 30 分钟)。没有保留策略时,本地 SQLite 会无限
膨胀 —— 实测单表曾达 234 万行 / 整库 348MB,而 99.9% 的行是死数据。

策略:按"每只股票最近 N 条"截断 fund_flow(N 由 settings 配置,默认 500),
`daily_analyses` 按 created_at、`screener_runs` 按 run_date 保留 N 天;
裁剪后按需 VACUUM 回收空间。

为什么"按需"而不是"删了才"VACUUM:SQLite 删除行只把页还给 freelist,
文件本身不会变小。2026-10-17 实测本地库 411MB / 105305 页,其中 freelist
105148 页(**99.8% 是空页**),真实数据不到 1MB —— 而启动时打开一个大库 +
大 WAL 会让应用启动从 6s 变成 85s。所以只要空闲页超过阈值就必须 VACUUM,
不能等"本次真的删了行"。

本模块被 main.py 启动钩子调用(失败不阻断启动),也可手动触发:
    python -m app.services.retention --vacuum
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta

from sqlalchemy import create_engine, delete, func, select, text

from app.core.config import settings
from app.core.logging import logger
from app.db import async_session
from app.models.orm import DailyAnalysis, FundFlow, ScreenerRun

# 按 created_at 保留的低频业务表(天数,超期删除)
_DAILY_ANALYSIS_KEEP_DAYS = 365

# 选股批次:按 screener_runs.run_date 保留天数。
# 注意 screener_picks **没有** 时间戳列(日期在父表 run 上),所以早先版本
# 里 `model.created_at` 对它会直接 AttributeError —— 见 _prune_screener_runs。
_SCREENER_KEEP_DAYS = 180

# 空闲页超过这个数量(且占比超 20%)就 VACUUM。4096B/页时 2000 页 ≈ 8MB。
_FREE_PAGE_TRIGGER = 2000
_PAGE_SIZE_ASSUMPTION = 4096


async def _prune_fund_flow(keep_per_stock: int) -> tuple[int, int]:
    """每只股票仅保留最近 keep_per_stock 条,返回 (删除数, 裁剪前总数)。"""
    async with async_session() as session:
        total_before = (
            await session.execute(select(func.count(FundFlow.id)))
        ).scalar_one()

        codes = (
            await session.execute(select(FundFlow.stock_code).distinct())
        ).scalars().all()

        deleted = 0
        for code in codes:
            # 保留窗口:该股票按时间倒序的前 keep_per_stock 行。
            # 必须为每只股票单独绑定 code 构造子查询 —— 早期版本把这个子查询
            # 提到循环外、条件又写成 `stock_code == stock_code`(恒真),语义
            # 变成"全库只留最近 N 条",而不是"每只股票各留 N 条"。
            keep_window = (
                select(FundFlow.id)
                .where(FundFlow.stock_code == code)
                .order_by(FundFlow.timestamp.desc(), FundFlow.id.desc())
                .limit(keep_per_stock)
                .scalar_subquery()
            )
            result = await session.execute(
                delete(FundFlow).where(
                    FundFlow.stock_code == code,
                    FundFlow.id.notin_(keep_window),
                )
            )
            deleted += result.rowcount or 0

        await session.commit()

    return deleted, total_before


async def _prune_daily_analyses(keep_days: int = _DAILY_ANALYSIS_KEEP_DAYS) -> int:
    """按天数裁剪 daily_analyses(该表有 created_at)。"""
    cutoff = datetime.now() - timedelta(days=keep_days)
    async with async_session() as session:
        result = await session.execute(
            delete(DailyAnalysis).where(DailyAnalysis.created_at < cutoff)
        )
        deleted = result.rowcount or 0
        await session.commit()
    return deleted


async def _prune_screener_runs(keep_days: int = _SCREENER_KEEP_DAYS) -> int:
    """按 run_date 裁剪选股批次。

    screener_picks 没有自己的时间列,日期挂在父表 screener_runs.run_date 上;
    picks 的外键带 ON DELETE CASCADE,且连接层已 PRAGMA foreign_keys=ON
    (见 app/db.py),所以删 run 会连带删掉明细,不需要单独删 picks。
    """
    cutoff = (datetime.now() - timedelta(days=keep_days)).date()
    async with async_session() as session:
        result = await session.execute(
            delete(ScreenerRun).where(ScreenerRun.run_date < cutoff)
        )
        deleted = result.rowcount or 0
        await session.commit()
    return deleted


def _sync_engine():
    """VACUUM / PRAGMA 用的同步引擎(VACUUM 不能在事务里跑)。"""
    url = settings.database_url.replace("+aiosqlite", "")
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _page_stats_sync() -> tuple[int, int]:
    """返回 (空闲页数, 总页数)。"""
    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            free = conn.execute(text("PRAGMA freelist_count")).scalar_one()
            total = conn.execute(text("PRAGMA page_count")).scalar_one()
        return int(free), int(total)
    finally:
        engine.dispose()


def _vacuum_sync() -> None:
    """回收空间,并把 WAL 截断(否则旧的 WAL 文件仍占着几百 MB)。"""
    engine = _sync_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("VACUUM"))
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
    finally:
        engine.dispose()


def _needs_vacuum(free_pages: int, total_pages: int) -> bool:
    """空闲页够多且占比够高才值得 VACUUM(小库 VACUUM 一次也就几十毫秒)。"""
    if free_pages < _FREE_PAGE_TRIGGER:
        return False
    return total_pages <= 0 or free_pages * 5 >= total_pages


async def run_retention(vacuum: bool | None = None) -> dict[str, int]:
    """执行一次裁剪。返回统计 {deleted, remaining, vacuumed}。"""
    do_vacuum = settings.retention_vacuum if vacuum is None else vacuum

    deleted = 0
    remaining = 0

    # 每张表单独 try:某张表结构变更(例如模型加了新列、或时间列挂在父表上)
    # 不能让整轮裁剪崩掉 —— 早先版本因为一个 AttributeError 让全库永远不被清理。
    try:
        flow_deleted, remaining = await _prune_fund_flow(
            settings.fund_flow_keep_per_stock
        )
        deleted += flow_deleted
    except Exception as e:  # noqa: BLE001 — 单表失败不影响其它表
        logger.warning(f"[retention] 裁剪 fund_flow 失败(跳过): {e}")

    try:
        deleted += await _prune_daily_analyses()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[retention] 裁剪 daily_analyses 失败(跳过): {e}")

    try:
        deleted += await _prune_screener_runs()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[retention] 裁剪 screener_runs 失败(跳过): {e}")

    vacuumed = False
    if do_vacuum:
        try:
            free_pages, total_pages = await asyncio.to_thread(_page_stats_sync)
            if _needs_vacuum(free_pages, total_pages):
                await asyncio.to_thread(_vacuum_sync)
                vacuumed = True
                logger.info(
                    "[retention] VACUUM 完成:回收约 "
                    f"{free_pages * _PAGE_SIZE_ASSUMPTION / 1024 / 1024:.1f}MB 空闲页"
                )
        except Exception as e:  # noqa: BLE001 — 回收失败不影响主流程
            logger.warning(f"VACUUM 失败(已忽略): {e}")

    return {"deleted": deleted, "remaining": remaining, "vacuumed": int(vacuumed)}


async def _amain(vacuum: bool) -> None:
    stats = await run_retention(vacuum=vacuum)
    print(
        f"[retention] 删除 {stats['deleted']} 条, fund_flow 剩余 {stats['remaining']} 条, "
        f"VACUUM={'是' if stats['vacuumed'] else '否'}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据保留裁剪")
    parser.add_argument(
        "--vacuum", action="store_true", help="裁剪后执行 VACUUM 回收空间"
    )
    parser.add_argument(
        "--no-vacuum", action="store_true", help="只裁剪不回收空间"
    )
    args = parser.parse_args()
    _vacuum = True if args.vacuum else (False if args.no_vacuum else None)
    asyncio.run(_amain(vacuum=_vacuum))
