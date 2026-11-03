"""价格提醒 API(阶段1)

- GET    /api/price-alerts                → 规则列表(可按股票过滤)
- POST   /api/price-alerts                → 创建规则(条件树非法 → 422)
- PATCH  /api/price-alerts/{id}           → 更新
- DELETE /api/price-alerts/{id}           → 删除
- GET    /api/price-alerts/{id}/triggers  → 触发流水
- POST   /api/price-alerts/{id}/test      → 立即评估一次(不落库,便于调试)
- GET    /api/price-alerts/meta/metrics   → 支持的指标与比较符(前端渲染表单用)
- GET    /api/price-alerts/stream         → SSE:提醒真的响了时实时推给前端

⚠️ **路由顺序**:字面量路径(`/meta/metrics` `/stream`)必须注册在参数路径之前 ——
FastAPI 按注册顺序匹配(不是按字面量优先),否则会被后面的参数路由吃掉。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.modules.alert.engine import (
    SUPPORTED_METRICS,
    SUPPORTED_OPS,
    AlertConditionError,
    AlertContext,
    describe,
    notification_meta,
)
from app.modules.alert.repository import price_alert_repo
from app.modules.alert.service import (
    EVENT_PRICE_ALERT_FIRED,
    build_fired_payload,
    price_alert_service,
)
from app.services.event_bus import event_bus

router = APIRouter(prefix="/price-alerts", tags=["price-alert"])

# SSE 心跳间隔(秒)—— 与 event_bus 的 30s 心跳同频
SSE_HEARTBEAT_SEC = 30
# 建连时补发最近多少分钟内「真的响了」的提醒
SNAPSHOT_WINDOW_MIN = 10
SNAPSHOT_LIMIT = 20


class PriceAlertCreate(BaseModel):
    stock_code: str
    conditions: dict = Field(..., description="条件树,如 {op:and, conditions:[{metric:price,op:'<=',value:12.5}]}")
    name: str = ""
    cooldown_sec: int = Field(default=1800, ge=0, le=86400)
    daily_limit: int = Field(default=5, ge=1, le=100)
    channels: list[str] | None = None


class PriceAlertUpdate(BaseModel):
    conditions: dict | None = None
    name: str | None = None
    enabled: bool | None = None
    cooldown_sec: int | None = Field(default=None, ge=0, le=86400)
    daily_limit: int | None = Field(default=None, ge=1, le=100)
    channels: list[str] | None = None


class PriceAlertTest(BaseModel):
    price: float
    change_pct: float | None = None
    volume_ratio: float | None = None
    turnover: float | None = None


@router.get("/meta/metrics")
async def metrics_meta() -> dict:
    """前端构建条件编辑器所需的元数据"""
    labels = {
        "price": "价格",
        "change_pct": "涨跌幅(%)",
        "volume_ratio": "量比",
        "turnover": "换手率(%)",
    }
    return {
        "metrics": [
            {"value": m, "label": labels.get(m, m)} for m in SUPPORTED_METRICS
        ],
        "ops": list(SUPPORTED_OPS),
        "group_ops": ["and", "or"],
    }


@router.get("")
async def list_alerts(stock_code: str | None = None) -> dict:
    items = await price_alert_service.list_alerts(stock_code)
    return {"items": items, "count": len(items)}


@router.post("")
async def create_alert(payload: PriceAlertCreate) -> dict:
    try:
        alert_id = await price_alert_service.create(
            stock_code=payload.stock_code,
            conditions=payload.conditions,
            name=payload.name,
            cooldown_sec=payload.cooldown_sec,
            daily_limit=payload.daily_limit,
            channels=payload.channels,
        )
    except AlertConditionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"id": alert_id}


@router.get("/recent-fired")
async def recent_fired(minutes: int = 10, limit: int = 20) -> dict:
    """最近**真的响了**(status=matched)的提醒。

    给前端的**降级轮询**用:SSE 连不上时靠它兜底,别让用户漏掉提醒。
    """
    rows = await price_alert_repo.list_recent_fired(
        since=datetime.now() - timedelta(minutes=max(1, min(minutes, 120))),
        limit=max(1, min(limit, 100)),
    )
    items = await _snapshot_items(rows)
    return {"items": items, "count": len(items)}


class PriceAlertTestPopup(BaseModel):
    """自检参数 —— 全部有默认值,直接 POST 空 body 也能试。"""

    stock_code: str = "001896.SZ"
    name: str = "测试标的"
    conditions_text: str = "价格 <= 8.771"
    price: float | None = 8.83
    # 提醒种类:`pre_alert` = 预警(到价之前的「准备」信号);留空 = 到价提醒
    kind: str | None = None


@router.post("/test-popup")
async def test_popup(payload: PriceAlertTestPopup) -> dict:
    """**弹窗通路自检**:广播一条合成的「提醒响了」事件。

    为什么要有它:到价提醒的真实触发要等**盘中且价格触到阈值**,
    而「提醒到底弹不弹得出来」这件事必须**当场**能验证 ——
    否则用户只能干等,分不清是「没到价」还是「弹窗坏了」。

    ⚠️ **零副作用**:不碰任何规则、不记流水、不消耗冷却/日限流额度。
    走的是与真实触发**完全相同**的广播路径(SSE → 前端弹窗)。

    `kind` 传 `pre_alert` 可以自检**预警**弹窗的样子(琥珀色「准备」徽章)。
    """
    fake_alert = SimpleNamespace(
        id=0, stock_code=payload.stock_code, name=payload.name
    )
    await event_bus.publish(
        build_fired_payload(
            fake_alert,
            trig=None,
            price=payload.price,
            conditions_text=payload.conditions_text,
            kind=payload.kind,
        )
    )
    return {"ok": True, "stock_code": payload.stock_code, "price": payload.price}


@router.get("/stream")
async def price_alert_stream():
    """SSE:提醒真的响了 → 实时推给前端弹应用内提示。

    - **首帧**:`price_alert_snapshot`(最近 10 分钟内真的响了的几条,补断线期间漏掉的)
    - **后续帧**:命中且通过冷却时的 `price_alert_fired`

    **为什么要有这个流**:Windows 托盘气泡在部分 Win11 上根本不渲染
    (实测 `ShowBalloonTip` 返回成功但屏幕上什么都没有),所以「提醒弹窗」
    必须有一条**不依赖系统通知**的兜底 —— 网页里弹,只要页面开着就一定看得见。
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)

    async def push(msg: dict) -> None:
        if msg.get("event") != EVENT_PRICE_ALERT_FIRED:
            return
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(msg)  # 队列满 = 丢这一帧,别阻塞广播总线

    unsub = event_bus.subscribe_callback(push)

    async def event_stream():
        try:
            yield (
                "data: "
                + json.dumps(
                    {"event": "price_alert_snapshot", "items": await _snapshot_items()},
                    ensure_ascii=False,
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


async def _snapshot_items(rows=None) -> list[dict]:
    """最近真的响了(SSE 断线重连期间漏掉的)的提醒,补发一次。"""
    if rows is None:
        try:
            rows = await price_alert_repo.list_recent_fired(
                since=datetime.now() - timedelta(minutes=SNAPSHOT_WINDOW_MIN),
                limit=SNAPSHOT_LIMIT,
            )
        except Exception:  # noqa: BLE001 — 补发失败不能挡住 SSE 主流程
            return []
    items: list[dict] = []
    for trig, alert in rows:
        price: float | None = None
        try:
            snap = json.loads(trig.snapshot_json) if trig.snapshot_json else {}
            price = snap.get("price")
        except (json.JSONDecodeError, TypeError, AttributeError):
            price = None
        try:
            conditions = json.loads(alert.conditions_json)
        except (json.JSONDecodeError, TypeError):
            conditions = {}
        items.append(
            build_fired_payload(
                alert,
                trig=trig,
                price=price,
                conditions_text=describe(conditions),
                kind=notification_meta(conditions).get("kind"),
            )
        )
    return items


@router.patch("/{alert_id}")
async def update_alert(alert_id: int, payload: PriceAlertUpdate) -> dict:
    try:
        ok = await price_alert_service.update(
            alert_id, **payload.model_dump(exclude_none=True)
        )
    except AlertConditionError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True}


@router.delete("/{alert_id}")
async def delete_alert(alert_id: int) -> dict:
    if not await price_alert_service.delete(alert_id):
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True}


@router.get("/{alert_id}/triggers")
async def list_triggers(alert_id: int, limit: int = 20) -> dict:
    import json

    rows = await price_alert_service.list_triggers(alert_id, limit)
    items = []
    for r in rows:
        items.append(
            {
                "id": r.id,
                "triggered_at": r.triggered_at.isoformat(),
                "status": r.status,
                "snapshot": json.loads(r.snapshot_json) if r.snapshot_json else None,
                "results": json.loads(r.results_json) if r.results_json else None,
            }
        )
    return {"items": items}


@router.post("/{alert_id}/test")
async def test_alert(alert_id: int, payload: PriceAlertTest) -> dict:
    """用给定行情立即评估一次(不推送、不落库)"""
    alert = await price_alert_service.get_alert(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    ctx = AlertContext(
        price=payload.price,
        change_pct=payload.change_pct,
        volume_ratio=payload.volume_ratio,
        turnover=payload.turnover,
    )
    import json

    try:
        conditions = json.loads(alert.conditions_json)
    except (json.JSONDecodeError, TypeError):
        conditions = {}
    matched = await price_alert_service.evaluate_alert(alert, ctx)
    return {
        "matched": matched,
        "conditions_text": describe(conditions),
    }
