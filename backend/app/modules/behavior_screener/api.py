"""找股 API(behavior_screener)

端点:
- GET  /api/behavior-screener/latest         最新一批结果(按信号类型分组 + 综合排序)
- GET  /api/behavior-screener/runs           历史 N 天批次
- GET  /api/behavior-screener/pool           候选池口径统计
- POST /api/behavior-screener/trigger-now    手动重跑(需 SCREENER_ALLOW_TRIGGER)

⚠️ 与 `/api/screener`(选股)的口径不同:那个按**因子打分**排 Top 20,
这个按 **K 线行为信号命中**分组。两者都在 NavRail「决策」组,前端须写清区别。
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.modules.behavior_screener import repository as repo
from app.modules.behavior_screener import service as behavior_service
from app.modules.behavior_screener.logic import group_hits, sort_hits
from app.services.behavior_signal_service import KIND_META

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/behavior-screener", tags=["behavior-screener"])


@router.get("/latest")
async def behavior_latest() -> dict[str, Any]:
    """最新一批结果(默认今日,无则上一交易日)。

    - 尚无批次 → 404(前端据此区分「还没跑」与「跑了但没命中」)
    """
    run = await repo.get_latest_run()
    if run is None:
        raise HTTPException(
            status_code=404,
            detail="尚无找股记录,请先运行 trigger-now 或等待盘后跑批",
        )
    picks = await repo.get_picks_by_run(run.id)
    hit_dicts = [behavior_service.pick_to_dict(p) for p in picks]
    return {
        "run": behavior_service.run_to_dict(run),
        "groups": _group_dicts(hit_dicts),
        "all": hit_dicts,
        "kinds": [
            {"kind": k, "label": KIND_META.get(k, {}).get("label", k)}
            for k in KIND_META
        ],
    }


def _group_dicts(hit_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 kind 分组(组内按分数降序)——复用 logic 的分组口径。"""
    from app.modules.behavior_screener.logic import SignalHit

    hits = [
        SignalHit(
            stock_code=h["stock_code"],
            stock_name=h.get("stock_name"),
            kind=h["kind"],
            signal_date=h.get("signal_date") or "",
            days_ago=int(h.get("days_ago") or 0),
            reason=h.get("reason") or "",
            metrics=h.get("metrics") or {},
            score=float(h.get("score") or 0.0),
            change_pct=h.get("change_pct"),
        )
        for h in hit_dicts
    ]
    return group_hits(hits)


@router.get("/runs")
async def behavior_runs(days: int = Query(default=10, ge=1, le=90)) -> dict[str, Any]:
    """最近 N 天的批次。"""
    runs = await repo.list_runs(days=days)
    return {
        "count": len(runs),
        "runs": [behavior_service.run_to_dict(r) for r in runs],
    }


@router.get("/pool")
async def behavior_pool() -> dict[str, Any]:
    """候选池口径统计(快照 → 主板 → 非 ST → 成交额闸门 → 候选)。

    用最新批次的统计值;还没跑过则返回空口径(不编数字)。
    """
    run = await repo.get_latest_run()
    if run is None:
        return {
            "universe": None,
            "candidates_considered": 0,
            "note": "尚无批次,未统计",
        }
    return {
        "universe": {
            "total": run.pool_size,
            "main_board": run.main_board_count,
            "non_st": run.non_st_count,
            "after_filters": run.after_filters_count,
        },
        "candidates_considered": run.candidates_considered,
        "note": run.note,
    }


@router.post("/trigger-now")
async def behavior_trigger_now(target_date: date | None = None) -> dict[str, Any]:
    """手动重跑(默认今日)。

    生产禁用:需 `SCREENER_ALLOW_TRIGGER=1` 环境变量(与 screener 一致)。
    """
    import os as _os

    if not _os.environ.get("SCREENER_ALLOW_TRIGGER"):
        raise HTTPException(
            status_code=403, detail="禁用,需 SCREENER_ALLOW_TRIGGER=1 环境变量"
        )

    result = await behavior_service.run_daily_scan(target_date)
    if result is None:
        raise HTTPException(status_code=502, detail="扫描失败(全市场快照不可用)")

    run, top = result
    hit_dicts = [
        {
            "stock_code": h.stock_code,
            "stock_name": h.stock_name,
            "kind": h.kind,
            "kind_label": KIND_META.get(h.kind, {}).get("label", h.kind),
            "signal_date": h.signal_date,
            "days_ago": h.days_ago,
            "reason": h.reason,
            "metrics": h.metrics,
            "score": round(h.score, 2),
            "change_pct": h.change_pct,
        }
        for h in top
    ]
    return {
        "run": behavior_service.run_to_dict(run),
        "groups": _group_dicts(hit_dicts),
        "all": hit_dicts,
    }


__all__ = ["router", "sort_hits"]
