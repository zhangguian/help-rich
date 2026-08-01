"""个股分析 API(v0.4-roadmap 功能2/3/4/5)

- GET  /api/stock/{code}/analysis  指标 + AI 解读(LLM 失败 → ai=null 纯指标)
- POST /api/stock/{code}/chat      操作问答(自动携带持仓成本)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.kline_service import KLineSourceUnavailable, fetch_klines
from app.services.position_service import get_position
from app.services.stock_advice_service import (
    StockAdviceUnavailable,
    ask_stock_question,
    get_stock_analysis,
)

router = APIRouter(prefix="/stock", tags=["stock"])


class ChatRequest(BaseModel):
    question: str


def _is_valid_code(code: str) -> bool:
    """600519.SH / 000001.SZ / 830799.BJ"""
    parts = code.split(".")
    if len(parts) != 2:
        return False
    num, market = parts
    return len(num) == 6 and num.isdigit() and market in {"SH", "SZ", "BJ"}


async def _load_klines(code: str) -> list[dict]:
    try:
        return await fetch_klines(code, period="daily", count=120)
    except KLineSourceUnavailable as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e


@router.get("/{code}/analysis")
async def analysis(code: str) -> dict:
    """指标 + AI 解读;AI 不可用自动降级纯指标(200 返回,ai=null)"""
    if not _is_valid_code(code):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_STOCK_CODE", "message": "代码格式应为 6 位数字 + .SH/.SZ"},
        )
    klines = await _load_klines(code)
    return await get_stock_analysis(code, klines)


@router.post("/{code}/chat")
async def chat(code: str, payload: ChatRequest) -> dict:
    """操作问答:结合行情 + 指标 + 持仓成本"""
    if not _is_valid_code(code):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_STOCK_CODE", "message": "代码格式应为 6 位数字 + .SH/.SZ"},
        )
    question = payload.question.strip()
    if not question:
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_QUESTION", "message": "问题不能为空"},
        )

    klines = await _load_klines(code)

    position = await get_position(code)
    cost = float(position.avg_cost) if position is not None else None

    try:
        answer = await ask_stock_question(code, question, klines, position_cost=cost)
    except StockAdviceUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail={"code": "LLM_UNAVAILABLE", "message": str(e)},
        ) from e
    return {"stock_code": code, "answer": answer}


__all__ = ["router"]
