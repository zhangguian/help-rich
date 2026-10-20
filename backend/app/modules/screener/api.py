"""盘后选股 API(v2.6)

端点:
- GET  /api/screener/latest         取最新一批 Top 20(默认今日)
- GET  /api/screener/runs           历史 N 天批次
- POST /api/screener/latest/llm-pick  用户主动触发 LLM 评选
- POST /api/screener/trigger-now    手动立刻重跑(测试/调试)
- GET  /api/screener/pool           看候选池大小
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.modules.screener import repository as screener_repo
from app.modules.screener import service as screener_service
from app.modules.screener.llm_prompt import trigger_llm_pick

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/screener", tags=["screener"])


# ============================================================
# 阶段2:选股权重(把写死的常量变成用户可调)
# ============================================================


class WeightItem(BaseModel):
    key: str
    weight: float
    enabled: bool = True


class WeightsSave(BaseModel):
    factors: list[WeightItem]


@router.get("/weights")
async def get_weights() -> dict:
    """当前权重视图(每个因子的满分、范围、说明)"""
    from app.modules.screener.weight_service import get_weights_view

    return await get_weights_view()


@router.put("/weights")
async def put_weights(payload: WeightsSave) -> dict:
    """保存一组权重(数值自动夹取,全停用则 422)"""
    from app.modules.screener.weight_service import (
        WeightValidationError,
        save_weights,
    )

    try:
        return await save_weights([f.model_dump() for f in payload.factors])
    except WeightValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/weights/reset")
async def reset_weights() -> dict:
    """清空自定义权重,回落到 config 默认常量"""
    from app.modules.screener.weight_service import reset_weights as _reset

    return await _reset()


# ============================================================
# Helpers
# ============================================================


def _pick_to_dict(p, watched_set: set[str] | None = None) -> dict[str, Any]:
    """ScreenerPick → API dict

    watched_set: 观察池 stock_code 集合(可选)— 用于标 is_watched
    """
    rules_raw = p.triggered_rules
    try:
        rules = json.loads(rules_raw) if isinstance(rules_raw, str) else rules_raw
    except json.JSONDecodeError:
        rules = []
    return {
        "rank": p.rank,
        "stock_code": p.stock_code,
        "stock_name": p.stock_name,
        "score": p.score,
        "main_net_inflow_yi": p.main_net_inflow_yi,
        "volume_ratio": p.volume_ratio,
        "change_pct": p.change_pct,
        "turnover_proxy": p.turnover_proxy,
        "consecutive_up_days": p.consecutive_up_days,
        "sector": p.sector,
        "sector_inflow_rank": p.sector_inflow_rank,
"triggered_rules": rules,
        "is_watched": p.stock_code in (watched_set or set()),
        "reason": p.reason,
    }


def _run_to_dict(r) -> dict[str, Any]:
    return {
        "id": r.id,
        "run_date": r.run_date.isoformat(),
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "scoring_version": r.scoring_version,
        "pool_size": r.pool_size,
        "total_picks": r.total_picks,
        "elapsed_sec": r.elapsed_sec,
        "note": r.note,
    }


# ============================================================
# GET /screener/latest
# ============================================================


@router.get("/latest")
async def screener_latest() -> dict[str, Any]:
    """最新一批 Top 20(默认今日,无则返回上一交易日)"""
    run = await screener_repo.get_latest_run()
    if run is None:
        raise HTTPException(status_code=404, detail="尚无选股记录,请先运行 init_index_constituents 或等待 15:30 跑批")
    picks = await screener_repo.get_picks_by_run(run.id)
    watched_set = await screener_repo.list_watchlist_codes(status="active")
    return {
        "run": _run_to_dict(run),
        "picks": [_pick_to_dict(p, watched_set) for p in picks],
    }


# ============================================================
# GET /screener/runs
# ============================================================


@router.get("/runs")
async def screener_runs(days: int = Query(default=10, ge=1, le=90)) -> dict[str, Any]:
    """最近 N 天的批次(默认 10 天)"""
    async def _list() -> list[Any]:
        from app.db import async_session
        from app.models.orm import ScreenerRun
        from sqlalchemy import select

        async with async_session() as session:
            stmt = (
                select(ScreenerRun)
                .order_by(ScreenerRun.run_date.desc())
                .limit(days)
            )
            return list((await session.execute(stmt)).scalars().all())

    runs = await _list()
    return {"count": len(runs), "runs": [_run_to_dict(r) for r in runs]}


# ============================================================
# GET /screener/pool
# ============================================================


@router.get("/pool")
async def screener_pool() -> dict[str, Any]:
    """候选池大小 + 前 20 只预览"""
    pool = await screener_service.get_pool()
    return {
        "count": len(pool),
        "preview": pool[:20],
    }


# ============================================================
# POST /screener/latest/llm-pick
# ============================================================


@router.post("/latest/llm-pick")
async def screener_latest_llm_pick(force: bool = False) -> dict[str, Any]:
    """用户主动按按钮触发 LLM 评选

    force=True 时绕过幂等缓存,重新调 LLM
    """
    run = await screener_repo.get_latest_run()
    if run is None:
        raise HTTPException(status_code=404, detail="尚无选股批次,请先等跑批")
    result = await trigger_llm_pick(run.id, force=force)
    if result["status"] == "failed":
        # 错误码 502(Bad Gateway)— LLM 失败
        raise HTTPException(status_code=502, detail=result.get("error", "LLM 失败"))
    # 加载完整 picks 详情(含 LLM 评语)
    llm_row = await screener_repo.get_llm_pick_by_run(run.id)
    return {
        "run_id": run.id,
        "run_date": run.run_date.isoformat(),
        "status": result["status"],
        "cached": result.get("cached", False),
        "model": result.get("model"),
        "summary": result.get("summary"),
        "picks": result.get("picks", []),
        "requested_at": (
            llm_row.requested_at.isoformat() if llm_row else None
        ),
    }


# ============================================================
# POST /screener/trigger-now(测试/调试)
# ============================================================


@router.post("/trigger-now")
async def screener_trigger_now(target_date: date | None = None) -> dict[str, Any]:
    """立刻手动跑一次(默认今日)"""
    # 防止生产被滥用:仅在显式开启 SCREENER_ALLOW_TRIGGER 时允许
    import os as _os
    if not _os.environ.get("SCREENER_ALLOW_TRIGGER"):
        raise HTTPException(status_code=403, detail="禁用,需 SCREENER_ALLOW_TRIGGER=1 环境变量")
    run = await screener_service.run_daily_pick(target_date)
    if run is None:
        raise HTTPException(status_code=500, detail="跑批失败(候选池为空?)")
    picks = await screener_repo.get_picks_by_run(run.id)
    watched_set = await screener_repo.list_watchlist_codes(status="active")
    return {
        "run": _run_to_dict(run),
        "picks": [_pick_to_dict(p, watched_set) for p in picks],
    }
# ============================================================
# /watchlist(�۲��)
# ============================================================

from pydantic import BaseModel, Field


class WatchlistAddRequest(BaseModel):
    stock_code: str = Field(..., description="6位代码.SH/.SZ")
    stock_name: str = Field(..., description="股票名(冗余,标选时记录)")
    note: str | None = None


@router.post("/watchlist")
async def screener_watchlist_add(payload: WatchlistAddRequest) -> dict[str, Any]:
    """加入观察池(幂等:已存在则返 already_existed=True)"""
    result = await screener_service.add_to_watchlist(
        stock_code=payload.stock_code,
        stock_name=payload.stock_name,
        note=payload.note,
    )
    return result


@router.delete("/watchlist/{stock_code}")
async def screener_watchlist_remove(stock_code: str) -> dict[str, Any]:
    """取消标记"""
    return await screener_service.remove_from_watchlist(stock_code)


@router.get("/watchlist")
async def screener_watchlist_summary(refresh: bool = False) -> dict[str, Any]:
    """观察池周/月报表

    refresh=true 时先刷一遍 daily records(用于手动 / 立即刷新 按钮)
    """
    if refresh:
        await screener_service.refresh_all_watchlist_daily()
    return await screener_service.compute_watchlist_summary()


# ============================================================
# v2.6.1:历史 picks 的 reason 列补算(一次性)
# ============================================================


@router.post("/backfill-reasons")
async def screener_backfill_reasons() -> dict[str, Any]:
    """一次性补算所有历史 picks 的 reason 列(需 SCREENER_ALLOW_TRIGGER 守卫)

    仅处理 reason IS NULL 的 pick,基于已存的因子字段重算 build_reason。
    bd.triggered_rules 不会回填(板块聚集奖励会缺失),但主要因子拼接已够。
    """
    import os as _os
    if not _os.environ.get("SCREENER_ALLOW_TRIGGER"):
        raise HTTPException(status_code=403, detail="需 SCREENER_ALLOW_TRIGGER=1 环境变量")
    return await screener_repo.backfill_reasons()
