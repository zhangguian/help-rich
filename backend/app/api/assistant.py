"""全局 AI 助手 API(阶段 T4 · 后端)

- POST /api/assistant/chat/stream  SSE 流式对话
  - 增量: `data: {"text": "..."}`
  - 结束: `data: {"done": true}`
  - 失败: `data: {"error": "..."}`

**与个股问答端点(`/api/stock/{code}/chat/stream`)的差别**:
助手是**全局**的 —— 它把「当前选中的票 + 持仓 + ★关注 + 今日作战计划 +
今日盘中复盘 + 指数快照」拼成一份事实包,所以请求里只带一个可选的
`stock_code`(前端当前选中的那只),不绑定某一只票。

**LLM 未配置 → 流开始前 503**(与既有 chat/stream 行为一致):
流一旦开始就无法改状态码,只能在流里发 error 事件 —— 所以前置校验必须在开流前做完。
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.stock_code import normalize_code
from app.services.assistant_service import (
    AssistantUnavailable,
    check_assistant_available,
    stream_assistant_answer,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AssistantChatRequest(BaseModel):
    """助手对话请求

    - question: 用户问题(必填)
    - stock_code: 前端**当前选中的票**(可选)。带了就会自动进事实包 ——
      这是「全局助手 + 自动带入当前选中票」的落点。
    - history: 历史轮次 `[{"role": "user"|"ai", "text": "..."}]`
    """

    question: str = Field(min_length=1, max_length=1000)
    stock_code: str | None = None
    history: list[dict[str, str]] | None = None


@router.post("/chat/stream")
async def assistant_chat_stream(payload: AssistantChatRequest) -> StreamingResponse:
    """助手流式对话(SSE)。

    未配置 LLM → **开流前** 503(不能等流开了再改状态码)。
    流中途失败 → 发 `data: {"error": "..."}` 后断开。
    """
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="问题不能为空")

    # 代码规范化(前端可能传 "600519" 这种裸代码)
    stock_code = None
    if payload.stock_code:
        stock_code = normalize_code(payload.stock_code) or payload.stock_code

    # 前置校验:LLM 未配置在流开始前抛 503
    try:
        await check_assistant_available()
    except AssistantUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail={"code": "LLM_UNAVAILABLE", "message": str(e)},
        ) from e

    async def gen():
        try:
            async for piece in stream_assistant_answer(
                question,
                stock_code=stock_code,
                history=payload.history,
            ):
                yield f"data: {json.dumps({'text': piece}, ensure_ascii=False)}\n\n"
        except AssistantUnavailable as e:
            logger.warning("助手流式回答失败: %s", e)
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
            return
        yield 'data: {"done": true}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream")


__all__ = ["router"]
