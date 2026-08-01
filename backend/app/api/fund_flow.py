"""资金流 API(E)

- GET /api/fund-flow/{stock_code}    历史最近 30 条
- GET /api/fund-flow/{stock_code}/events  SSE 实时推送(订阅)
- POST /api/fund-flow/{stock_code}/generate 手动触发 1 条(mock)
"""
import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.db_lock import safe_write
from app.services.event_bus import event_bus
from app.services.fund_flow_service import FundFlow, generate_one, list_recent

router = APIRouter(prefix="/fund-flow", tags=["fund-flow"])


@router.get("/{stock_code}")
async def get_recent(stock_code: str, limit: int = 30) -> dict:
    """获取最近 N 条资金流(初始列表用)"""
    rows = await list_recent(stock_code, limit=limit)
    return {
        "stock_code": stock_code,
        "items": [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "direction": r.direction,
                "amount": r.amount,
                "category": r.category,
                "source": r.source,
            }
            for r in rows
        ],
    }


@router.post("/{stock_code}/generate")
async def manual_generate(stock_code: str) -> dict:
    """手动触发:从新浪资金流排行查该股并落库(guide §7,完全真实数据)"""
    try:
        flow = await generate_one(stock_code)
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e
    return {"ok": True, "id": flow["id"]}


@router.get("/{stock_code}/events")
async def stream_events(stock_code: str):
    """SSE:订阅指定股票的资金流推送"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    async def push(msg: dict):
        # 过滤:只取匹配 stock_code 的 fund_flow 事件
        if msg.get("event") == "fund_flow" and msg.get("stock_code") == stock_code:
            await queue.put(msg)

    unsub = event_bus.subscribe_callback(
        push, filter_fn=lambda m: m.get("event") == "fund_flow"
    )

    async def event_stream():
        # 初始连接通知
        yield f"data: {json.dumps({'event': 'subscribed', 'stock_code': stock_code}, ensure_ascii=False)}\n\n"
        # 拉最近 5 条作为回放
        rows = await list_recent(stock_code, limit=5)
        for r in reversed(rows):
            payload = {
                "event": "fund_flow",
                "stock_code": stock_code,
                "direction": r.direction,
                "amount": r.amount,
                "category": r.category,
                "timestamp": r.timestamp.isoformat(),
                "replay": True,
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ":heartbeat\n\n"
        finally:
            await unsub()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]