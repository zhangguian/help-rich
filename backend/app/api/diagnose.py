"""诊断 API(backend-arch §5.3 / api-contract §1.5)

- POST /api/diagnose/{trade_id} → 立即返回,异步评分 + 评语(SSE 推送)
- GET  /api/diagnose/{trade_id} → 查询当前评分状态(降级轮询用)
"""
import json

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.models.schemas import DiagnoseOut
from app.repositories.trade_score_repo import trade_score_repo
from app.repositories.transaction_repo import transaction_repo
from app.services.diagnose_service import diagnose_service

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
