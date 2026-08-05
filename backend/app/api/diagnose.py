"""诊断 API(backend-arch §5.3 / api-contract §1.5)

- POST /api/diagnose/{trade_id} → 立即返回,异步评分 + 评语(SSE 推送)
- GET  /api/diagnose/{trade_id} → 查询当前评分状态(降级轮询用)
- PUT  /api/diagnose/{trade_id}/feedback → 评语价值反馈(P4.9:useful/useless/null)

一键复盘(v2.3):
- POST /api/diagnose/stock/{stock_code}/summary?window=X → 强制 LLM 重算 + 写库
- GET  /api/diagnose/stock/{stock_code}/summary?window=X → 读 DB(秒回,无 LLM)
- GET  /api/diagnose/stock/{stock_code}/summaries → 一次拿齐 6 窗口(初始化用)

每日 AI 分析持久化(v2.4):
- GET  /api/diagnose/stock/{stock_code}/daily-analyses?days=N → 列最近 N 天分析
"""
import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.core.db_lock import safe_write
from app.core.stock_code import normalize_code
from app.models.schemas import DiagnoseOut, FeedbackUpdate, ReplaySummaryOut
from app.repositories.trade_score_repo import trade_score_repo
from app.repositories.transaction_repo import transaction_repo
from app.services.daily_analysis_service import (
    compute_view_winrate,
    list_history,
)
from app.services.diagnose_service import diagnose_service
from app.services.replay_service import (
    WINDOWS,
    force_replay,
    get_latest,
    list_all_for_stock,
)

router = APIRouter(prefix="/diagnose", tags=["diagnose"])


@router.post("/{trade_id}")
async def trigger_diagnose(trade_id: int, background_tasks: BackgroundTasks) -> dict:
    """触发诊断:立即返回,评分异步推送(SSE)"""
    trade = await transaction_repo.get_by_id(trade_id)
    if trade is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "TX_NOT_FOUND",
                "message": f"交易 #{trade_id} 不存在",
            },
        )
    background_tasks.add_task(diagnose_service.score_and_notify, trade_id)
    return {"trade_id": trade_id, "status": "pending"}


@router.get("/{trade_id}", response_model=DiagnoseOut)
async def get_diagnose(trade_id: int) -> DiagnoseOut:
    """查询评分状态(SSE 降级轮询兜底)"""
    score = await trade_score_repo.get_by_trade_id(trade_id)
    if score is None:
        return DiagnoseOut(
            trade_id=trade_id,
            status="pending",
            score=None,
            breakdown=None,
            ai_comment=None,
        )
    return DiagnoseOut(
        trade_id=trade_id,
        status="success" if score.ai_status == "success" else score.ai_status,
        score=score.score,
        breakdown=json.loads(score.score_breakdown),
        ai_comment=score.ai_comment,
    )


@router.put("/{trade_id}/feedback")
async def update_feedback(trade_id: int, payload: FeedbackUpdate) -> dict:
    """P4.9 评语价值反馈(useful / useless / null=撤销)"""
    if await transaction_repo.get_by_id(trade_id) is None:
        raise HTTPException(status_code=404, detail={"code": "TX_NOT_FOUND", "message": "交易不存在"})

    async def _do():
        await trade_score_repo.update_feedback(trade_id, payload.feedback)

    await safe_write(_do)
    return {"trade_id": trade_id, "feedback": payload.feedback}


# ============================================================
# === 一键复盘(v2.3) ===
# ============================================================


def _record_to_out(rec) -> ReplaySummaryOut:
    return ReplaySummaryOut(
        stock_code=rec.stock_code,
        window=rec.window,
        score_avg=rec.score_avg,
        dimension_avg=json.loads(rec.dimension_avg),
        top_issues=json.loads(rec.top_issues),
        ai_comment=rec.ai_comment,
        ai_status=rec.ai_status,
        ai_provider=rec.ai_provider,
        ai_model=rec.ai_model,
        ai_latency_ms=rec.ai_latency_ms,
        summary_snapshot=json.loads(rec.summary_snapshot),
        latest_tx_id=rec.latest_tx_id,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


@router.get("/stock/{stock_code}/summaries")
async def get_stock_summaries(stock_code: str) -> dict:
    """一次拿齐 6 窗口的最新记录(初始化用)"""
    norm = normalize_code(stock_code) or stock_code
    rows = await list_all_for_stock(norm)
    by_window = {r.window: _record_to_out(r).model_dump() for r in rows}
    for w in WINDOWS:
        by_window.setdefault(w, None)
    return {"stock_code": norm, "windows": by_window}


@router.get("/stock/{stock_code}/summary", response_model=ReplaySummaryOut)
async def get_stock_summary(
    stock_code: str, window: str = Query(..., description="1d/3d/5d/10d/20d/60d")
) -> ReplaySummaryOut:
    """只读 DB(切换窗口秒回,无 LLM)"""
    if window not in WINDOWS:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_WINDOW", "message": f"window 必须为 {list(WINDOWS.keys())}"},
        )
    norm = normalize_code(stock_code) or stock_code
    rec = await get_latest(norm, window)
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "REPLAY_NOT_FOUND", "message": "该窗口暂无复盘记录,请先点「一键复盘」"},
        )
    return _record_to_out(rec)


@router.post("/stock/{stock_code}/summary", response_model=ReplaySummaryOut)
async def trigger_stock_summary(
    stock_code: str, window: str = Query(..., description="1d/3d/5d/10d/20d/60d")
) -> ReplaySummaryOut:
    """强制 LLM 重算 + UPSERT 写库(同窗口多次复盘 → 覆盖最新)"""
    if window not in WINDOWS:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_WINDOW", "message": f"window 必须为 {list(WINDOWS.keys())}"},
        )
    norm = normalize_code(stock_code) or stock_code
    rec = await force_replay(norm, window)
    return _record_to_out(rec)


# ============================================================
# === 每日 AI 分析持久化(v2.4) ===
# ============================================================


@router.get("/stock/{stock_code}/daily-analyses")
async def list_daily_analyses(
    stock_code: str,
    days: int = Query(default=30, ge=1, le=365),
    horizon: int = Query(default=20, ge=1, le=120, description="N 天后实际涨跌判定窗口"),
) -> dict:
    """列出某只股票最近 N 天的 AI 分析记录(用于历史查看 / 胜率分析)

    按日期倒序(最新在前);同一日期多次生成时只返回最新一条(由 UNIQUE 约束保证)。
    每条带 actual_change_pct(N 天后相对 analysis_date 的涨跌幅)。
    """
    norm = normalize_code(stock_code) or stock_code
    items = await list_history(norm, days=days, horizon_days=horizon)
    return {
        "stock_code": norm,
        "days": days,
        "horizon_days": horizon,
        "items": items,
        "total": len(items),
    }


@router.get("/stock/{stock_code}/daily-analyses/winrate")
async def get_stock_winrate(
    stock_code: str,
    days: int = Query(default=60, ge=1, le=365),
    horizon: int = Query(default=20, ge=1, le=120, description="N 天后判定 horizon_days"),
) -> dict:
    """方向胜率:AI 给的 bullish/bearish vs N 天后真实涨跌

    - bullish → N 天后涨 → 命中
    - bearish → N 天后跌 → 命中
    - neutral → 跳过(不计入分母)
    - 数据不足时返回 insufficient=true
    """
    norm = normalize_code(stock_code) or stock_code
    return await compute_view_winrate(norm, days=days, horizon_days=horizon)
