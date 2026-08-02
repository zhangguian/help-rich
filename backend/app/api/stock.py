"""个股分析 API(v0.4-roadmap 功能2/3/4/5)

- GET  /api/stock/{code}/analysis  指标 + AI 解读(LLM 失败 → ai=null 纯指标)
- POST /api/stock/{code}/chat      操作问答(自动携带持仓成本)
- POST /api/stock/{code}/chat/stream  操作问答流式版(SSE,打字机输出)
"""
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.kline_service import KLineSourceUnavailable, fetch_klines
from app.services.position_service import get_position
from app.services.stock_advice_service import (
    StockAdviceUnavailable,
    ask_stock_question,
    ask_stock_question_stream,
    check_llm_available,
    get_stock_analysis,
)

logger = logging.getLogger(__name__)

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


async def _position_cost(code: str) -> float | None:
    """持仓成本(chat / chat/stream 共用)"""
    position = await get_position(code)
    return float(position.avg_cost) if position is not None else None


async def _check_code(code: str) -> None:
    if not _is_valid_code(code):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_STOCK_CODE", "message": "代码格式应为 6 位数字 + .SH/.SZ"},
        )


def _check_question(question: str) -> str:
    q = question.strip()
    if not q:
        raise HTTPException(
            status_code=422,
            detail={"code": "EMPTY_QUESTION", "message": "问题不能为空"},
        )
    return q


@router.get("/{code}/analysis")
async def analysis(code: str) -> dict:
    """指标 + AI 解读;AI 不可用自动降级纯指标(200 返回,ai=null)"""
    await _check_code(code)
    klines = await _load_klines(code)
    return await get_stock_analysis(code, klines)


@router.post("/{code}/chat")
async def chat(code: str, payload: ChatRequest) -> dict:
    """操作问答:结合行情 + 指标 + 持仓成本"""
    await _check_code(code)
    question = _check_question(payload.question)

    klines = await _load_klines(code)
    cost = await _position_cost(code)

    try:
        answer = await ask_stock_question(code, question, klines, position_cost=cost)
    except StockAdviceUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail={"code": "LLM_UNAVAILABLE", "message": str(e)},
        ) from e
    return {"stock_code": code, "answer": answer}


@router.post("/{code}/chat/stream")
async def chat_stream(code: str, payload: ChatRequest) -> StreamingResponse:
    """操作问答流式版(SSE):data: {"text": ...} 增量,结束时 data: {"done": true}

    流中途失败发 data: {"error": "..."} 后断开;未配置 Key 直接 503。
    """
    await _check_code(code)
    question = _check_question(payload.question)

    # 前置校验:LLM 未配置在流开始前抛 503(流中途失败才走 SSE error 事件)
    try:
        await check_llm_available()
    except StockAdviceUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail={"code": "LLM_UNAVAILABLE", "message": str(e)},
        ) from e

    klines = await _load_klines(code)
    cost = await _position_cost(code)

    async def gen():
        try:
            async for piece in ask_stock_question_stream(
                code, question, klines, position_cost=cost
            ):
                yield f"data: {json.dumps({'text': piece}, ensure_ascii=False)}\n\n"
        except StockAdviceUnavailable as e:
            logger.warning("流式问答失败(%s): %s", code, e)
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            return
        yield 'data: {"done": true}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


__all__ = ["router"]
