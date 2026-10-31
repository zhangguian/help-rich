"""盘中信号 API(ADR-0007)

- GET   /api/signals/config     → 当前配置 + 生效口径
- PATCH /api/signals/config     → 改阈值/开关/渠道(落库)
- GET   /api/signals            → 最近的信号流水
- GET   /api/signals/stream     → SSE:信号实时推送
- POST  /api/signals/test       → 真弹一条桌面通知(验通道是否通)

⚠️ **路由顺序**:字面量路径(`/config` `/stream` `/test`)必须注册在参数路径之前 ——
FastAPI 按注册顺序匹配(不是按字面量优先),否则会被后面的参数路由吃掉。
"""
from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.modules.signal.scheduler import scheduler
from app.modules.signal.service import EVENT_SIGNAL_FIRED, signal_service
from app.services.event_bus import event_bus

router = APIRouter(prefix="/signals", tags=["signals"])

# SSE 心跳间隔(秒)—— 与 event_bus 的 30s 心跳同频
SSE_HEARTBEAT_SEC = 30


class SignalConfigIn(BaseModel):
    """配置补丁(全部可选,只传要改的字段)。"""

    enabled: bool | None = None
    velocity_window_sec: int | None = Field(None, ge=5, le=3600)
    velocity_pct: float | None = Field(None, gt=0, le=20)
    breakout_up_pct: float | None = Field(None, gt=0, le=50)
    breakout_down_pct: float | None = Field(None, ge=-50, lt=0)
    enable_velocity: bool | None = None
    enable_breakout: bool | None = None
    enable_t_point: bool | None = None
    enable_buy_point: bool | None = None
    cooldown_sec: int | None = Field(None, ge=0, le=86400)
    daily_limit: int | None = Field(None, ge=1, le=100)
    channels: list[str] | None = None


@router.get("/config")
async def get_config() -> dict:
    """当前配置 + 当前生效的触发价快照(前端可见「今日该票不适合做T」)。"""
    cfg = await signal_service.get_config()
    return {"config": cfg.to_dict(), "runtime": scheduler.snapshot()}


@router.patch("/config")
async def patch_config(payload: SignalConfigIn) -> dict:
    """改配置(落库)。只传要改的字段。"""
    data = payload.model_dump(exclude_none=True)
    cfg = await signal_service.update_config(**data)
    return {"config": cfg.to_dict()}


@router.get("/stream")
async def signal_stream():
    """SSE:盘中信号实时推送。

    - **首帧**:`signal_snapshot`(当前触发价 + 不适合原因)
    - **后续帧**:命中信号时的 `signal_fired`
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)

    async def push(msg: dict) -> None:
        if msg.get("event") != EVENT_SIGNAL_FIRED:
            return
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(msg)  # 队列满 = 丢这一帧,别阻塞广播总线

    unsub = event_bus.subscribe_callback(push)

    async def event_stream():
        try:
            yield (
                "data: "
                + json.dumps(
                    {"event": "signal_snapshot", **scheduler.snapshot()}, ensure_ascii=False
                )
                + "\n\n"
            )
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SEC)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ":heartbeat\n\n"
        finally:
            await unsub()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/test")
async def test_signal() -> dict:
    """真弹一条桌面通知(验通道是否通)。"""
    return await signal_service.test_desktop_notification()


@router.get("")
async def list_signals(
    stock_code: str | None = Query(None, description="按代码过滤"),
    limit: int = Query(50, ge=1, le=500, description="最多返回多少条"),
) -> dict:
    """最近的信号流水(前端「信号流水」页)。"""
    items = await signal_service.list_triggers(stock_code=stock_code, limit=limit)
    return {"items": items}


__all__ = ["router"]
