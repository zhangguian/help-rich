"""价格提醒 API(阶段1)

- GET    /api/price-alerts                → 规则列表(可按股票过滤)
- POST   /api/price-alerts                → 创建规则(条件树非法 → 422)
- PATCH  /api/price-alerts/{id}           → 更新
- DELETE /api/price-alerts/{id}           → 删除
- GET    /api/price-alerts/{id}/triggers  → 触发流水
- POST   /api/price-alerts/{id}/test      → 立即评估一次(不落库,便于调试)
- GET    /api/price-alerts/meta/metrics   → 支持的指标与比较符(前端渲染表单用)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.alert.engine import (
    SUPPORTED_METRICS,
    SUPPORTED_OPS,
    AlertConditionError,
    AlertContext,
    describe,
)
from app.modules.alert.service import price_alert_service

router = APIRouter(prefix="/price-alerts", tags=["price-alert"])


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
