"""SSE 事件端点(backend-arch §8 / api-contract §1.7)

GET /api/events/sse → text/event-stream
事件格式:
  data: {"event": "trade.scored", "trade_id": 123, ...}
  data: {"event": "ping", "ts": ...}
"""
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.event_bus import event_bus

router = APIRouter(tags=["events"])


@router.get("/events/sse")
async def sse_endpoint(request: Request) -> StreamingResponse:
    client_id = f"client-{time.time_ns()}"

    async def event_generator():
        queue = event_bus.subscribe(client_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            event_bus.unsubscribe(client_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
