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
- GET  /api/diagnose/stock/{stock_code}/analysis-latest → 取最新一条完整 snapshot
  (v2.5.2;供换浏览器/换设备时回显使用;不影响正常 /stock/{code}/analysis 流程)
"""
import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.api.stock import (
    _kline_fallback_price,
    _resolve_position_status,
    _sanitize_current_price,
)
from app.core.db_lock import safe_write
from app.core.stock_code import normalize_code
from app.models.schemas import DiagnoseOut, FeedbackUpdate, ReplaySummaryOut
from app.repositories.trade_score_repo import trade_score_repo
from app.modules.portfolio.repository import transaction_repo
from app.services.daily_analysis_service import (
    compute_view_winrate,
    get_latest_as_analysis_result,
    list_history,
)
from app.services.diagnose_service import diagnose_service
from app.services.kline_service import KLineSourceUnavailable, fetch_klines
from app.modules.portfolio.service import get_position
from app.services.quote_service import QuoteService
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


@router.get("/stock/{stock_code}/analysis-latest")
async def get_latest_analysis(stock_code: str) -> dict:
    """取该股票最新一条 daily_analysis 完整 snapshot,重组为 AnalysisResult 兼容 dict

    用于换浏览器/换设备时回显 AI 解读存档。
    - 有存档 → 返回 200 + AnalysisResult 形状
    - 无存档 → 返回 200 + 空 AnalysisResult(ai=null, indicators=null)— 前端按空数据处理
    - 不返回 404(避免前端需要处理 not found)

    实时计算当前用户持仓角色(position_status / cost_basis_pct),与 stock.py 缓存
    命中分支语义一致:统一 ai.positionStatus / ai.adviceRole / tStrategy,防止
    "DB 里是空仓时代的 ai,用户已加仓"的角色漂移。

    防御:#3 双校验 — 返回 dict 的 stockCode 必须等于 URL 上的 stock_code
    """
    norm = normalize_code(stock_code) or stock_code
    # 实时计算当前持仓角色(与 stock.py /analysis 端点同语义)
    try:
        klines = await fetch_klines(norm, period="daily", count=300)
    except KLineSourceUnavailable:
        klines = []
    latest_kline_date = klines[-1]["date"] if klines else None
    try:
        qs = await QuoteService().get_quotes([norm])
        quote = qs[0] if qs else None
    except Exception:
        quote = None
    current_price, _ = _sanitize_current_price(quote, klines)
    position = await get_position(norm)
    position_status, cost_basis_pct = _resolve_position_status(
        position, current_price, _kline_fallback_price(klines)
    )

    payload = await get_latest_as_analysis_result(
        norm,
        override_position_status=position_status,
        override_cost_basis_pct=cost_basis_pct,
    )
    if payload is None:
        payload = {
            "stockCode": norm,
            "stock_code": norm,
            "indicators": None,
            "ai": None,
            "signal_winrate": None,
            "signalWinrate": None,
            "latest_kline_date": latest_kline_date,
            "latestKlineDate": latest_kline_date,
            "current_price": None,
            "currentPrice": None,
            "quote_change_pct": None,
            "quoteChangePct": None,
            "position_status": None,
            "positionStatus": None,
            "cost_basis_pct": None,
            "costBasisPct": None,
            "ai_error": None,
            "aiError": None,
        }
    # 双校验:确保返回值归属正确股票
    if payload.get("stockCode") != norm or payload.get("stock_code") != norm:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "STOCK_CODE_MISMATCH",
                "message": (
                    f"[isolation] endpoint stock_code mismatch: "
                    f"payload.stockCode={payload.get('stockCode')} != requested={norm}"
                ),
            },
        )
    # 追平当前 K 线日期:回显展示的是"最新 K 线所处交易日",而非存档写入日
    payload["latest_kline_date"] = latest_kline_date
    payload["latestKlineDate"] = latest_kline_date
    return payload


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
