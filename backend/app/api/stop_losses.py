"""止损 API(P5.1 + P5.2 实施)

- POST   /api/stop-losses             → 设置/更新止损(safe_write,同 stock_code 覆盖)
- GET    /api/stop-losses             → 止损列表
- DELETE /api/stop-losses/{code}      → 删除止损
- POST   /api/stop-losses/{code}/triggered → 标记触发(幂等,同日重复 200)
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.db_lock import safe_write
from app.core.stock_code import normalize_code
from app.repositories.stop_loss_repo import stop_loss_repo

router = APIRouter(prefix="/stop-losses", tags=["stop-loss"])


class StopLossUpsert(BaseModel):
    """POST /api/stop-losses body"""
    stock_code: str
    stop_loss_price: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    enabled: bool = True
    notify_sound: bool = True
    notify_desktop: bool = True
    notify_vibrate: bool = True


class StopLossOut(BaseModel):
    id: int
    stock_code: str
    stop_loss_price: str
    enabled: bool
    notify_sound: bool
    notify_desktop: bool
    notify_vibrate: bool
    last_triggered_at: date | None = None


@router.post("", response_model=StopLossOut)
async def upsert_stop_loss(payload: StopLossUpsert) -> StopLossOut:
    """设置/更新止损(stock_code 规范化,同 code 覆盖)"""
    code = normalize_code(payload.stock_code)

    async def _do():
        return await stop_loss_repo.upsert(
            stock_code=code,
            stop_loss_price=f"{payload.stop_loss_price:.3f}",
            enabled=payload.enabled,
            notify_sound=payload.notify_sound,
            notify_desktop=payload.notify_desktop,
            notify_vibrate=payload.notify_vibrate,
        )

    row = await safe_write(_do)
    return StopLossOut(
        id=row.id,
        stock_code=row.stock_code,
        stop_loss_price=row.stop_loss_price,
        enabled=row.enabled,
        notify_sound=row.notify_sound,
        notify_desktop=row.notify_desktop,
        notify_vibrate=row.notify_vibrate,
        last_triggered_at=row.last_triggered_at,
    )


@router.get("", response_model=list[StopLossOut])
async def list_stop_losses() -> list[StopLossOut]:
    """止损列表"""
    rows = await stop_loss_repo.list_all()
    return [
        StopLossOut(
            id=r.id, stock_code=r.stock_code,
            stop_loss_price=r.stop_loss_price, enabled=r.enabled,
            notify_sound=r.notify_sound, notify_desktop=r.notify_desktop,
            notify_vibrate=r.notify_vibrate,
            last_triggered_at=r.last_triggered_at,
        )
        for r in rows
    ]


@router.delete("/{stock_code}")
async def delete_stop_loss(stock_code: str) -> dict:
    """删除止损"""
    code = normalize_code(stock_code)
    ok = await stop_loss_repo.remove(code)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "STOP_LOSS_NOT_FOUND", "message": f"{code} 未设置止损"},
        )
    return {"ok": True, "stock_code": code}


@router.post("/{stock_code}/triggered")
async def mark_triggered(stock_code: str) -> dict:
    """P5.2 标记今日已触发(幂等:同日重复返回 200 + duplicate=true)"""
    code = normalize_code(stock_code)

    async def _do():
        new_trigger = await stop_loss_repo.mark_triggered(code)
        return new_trigger

    new_trigger = await safe_write(_do)
    if not new_trigger:
        # 没设置止损,或同日重复
        existing = await stop_loss_repo.list_all()
        if not any(r.stock_code == code for r in existing):
            raise HTTPException(
                status_code=404,
                detail={"code": "STOP_LOSS_NOT_FOUND", "message": f"{code} 未设置止损"},
            )
        return {"ok": True, "stock_code": code, "duplicate": True}
    return {"ok": True, "stock_code": code, "duplicate": False}