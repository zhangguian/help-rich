"""盘中复盘 API(阶段 T2)

- GET  /api/intraday-review?date=&slot=   取某日某档 / 某日全部档(查不到 → 404,不返回空壳)
- GET  /api/intraday-review/schedule       今日状态(是否交易日 / 已产出哪几档 / 下一档倒计时)
- POST /api/intraday-review/generate       手动生成(**不推送**)
- POST /api/intraday-review/dispatch       生成并推送(**真发消息,不可撤回**)

**生成 / 推送分离**:推送不可撤回,所以两个按钮分开(沿用 BriefPanel 既有设计原则)。

**返回形态**(`GET /api/intraday-review`):
- 带 `slot` → 直接返回该档的复盘对象(字段与 `POST /generate` 的返回**逐字段一致**);
- 不带 `slot` → 返回 `{"date": ..., "count": n, "reviews": [各档复盘对象...]}`。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.modules.analysis.intraday_review import (
    VALID_SLOTS,
    dispatch_intraday_review,
    get_reviews,
    run_intraday_review,
)
from app.services.trading_calendar_service import trading_day_meta

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intraday-review", tags=["intraday-review"])

# 档位 → 当天的窗口时刻
SLOT_TIMES: dict[str, tuple[int, int]] = {"11:30": (11, 30), "14:00": (14, 0)}


class SlotRequest(BaseModel):
    slot: str = "11:30"


def _parse_date(raw: str | None) -> date:
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from None


async def _generate(slot: str) -> dict:
    """生成一次复盘(带交易日标注),失败转成可读的 HTTP 错误"""
    if slot not in VALID_SLOTS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的档位: {slot}(可用: {', '.join(VALID_SLOTS)})",
        )
    try:
        meta = await trading_day_meta()
        return await run_intraday_review(slot, trading_day=meta)
    except ValueError as e:
        # 今日作战计划还没生成 / 档位非法 → 422(响亮失败,不返回半成品)
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("生成盘中复盘失败")
        raise HTTPException(status_code=500, detail=f"生成盘中复盘失败: {e}") from e


@router.get("/schedule")
async def schedule() -> dict:
    """今日状态:是否交易日(含 estimated 标记)/ 已产出哪几档 / 下一档窗口与倒计时。"""
    try:
        meta = await trading_day_meta()
    except Exception as e:  # noqa: BLE001 — 交易日历故障不应让整个端点 500
        logger.warning("读取交易日历失败: %s", e)
        meta = {
            "is_trading_day": date.today().weekday() < 5,
            "trade_date_source": "weekday_fallback",
            "trading_day_estimated": True,
            "trade_date": None,
        }

    today = date.today()
    reviews = await get_reviews(today.isoformat())
    produced = [str(r.get("slot")) for r in reviews if r.get("slot")]

    now = datetime.now()
    next_slot: str | None = None
    minutes_left: int | None = None
    for slot in VALID_SLOTS:
        hour, minute = SLOT_TIMES[slot]
        window = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < window:
            next_slot = slot
            minutes_left = int((window - now).total_seconds() // 60)
            break
    if next_slot is None:
        # 今天的窗口都过了 → 下一档是明天上午
        hour, minute = SLOT_TIMES[VALID_SLOTS[0]]
        window = (now + timedelta(days=1)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        next_slot = VALID_SLOTS[0]
        minutes_left = int((window - now).total_seconds() // 60)

    return {
        "date": today.isoformat(),
        "is_trading_day": bool(meta.get("is_trading_day")),
        "trade_date_source": meta.get("trade_date_source"),
        "trading_day_estimated": bool(meta.get("trading_day_estimated")),
        "trade_date": meta.get("trade_date"),
        "slots": list(VALID_SLOTS),
        "produced_slots": produced,
        "next_slot": next_slot,
        "next_slot_at": next_slot,
        "next_slot_minutes_left": minutes_left,
        "now": now.isoformat(timespec="seconds"),
    }


@router.get("")
async def read_reviews(
    trade_date: str | None = Query(default=None, alias="date"),
    slot: str | None = Query(default=None),
) -> dict:
    """取某日某档 / 某日全部档。查不到 → 404(不返回空壳)。"""
    target = _parse_date(trade_date)
    if slot:
        if slot not in VALID_SLOTS:
            raise HTTPException(
                status_code=422,
                detail=f"不支持的档位: {slot}(可用: {', '.join(VALID_SLOTS)})",
            )
        reviews = await get_reviews(target.isoformat())
        for r in reviews:
            if r.get("slot") == slot:
                payload = r.get("payload") or {}
                return {**payload, "trade_date": target.isoformat(), "slot": slot}
        raise HTTPException(
            status_code=404,
            detail=f"{target.isoformat()} {slot} 的盘中复盘尚未生成",
        )

    reviews = await get_reviews(target.isoformat())
    if not reviews:
        raise HTTPException(
            status_code=404,
            detail=f"{target.isoformat()} 还没有任何盘中复盘",
        )
    return {
        "date": target.isoformat(),
        "count": len(reviews),
        "reviews": [(r.get("payload") or {}) for r in reviews],
    }


@router.post("/generate")
async def generate(req: SlotRequest | None = None) -> dict:
    """手动生成盘中复盘(**不推送**)。"""
    slot = req.slot if req and req.slot else "11:30"
    return await _generate(slot)


@router.post("/dispatch")
async def dispatch(req: SlotRequest | None = None) -> dict:
    """生成并推送到已启用渠道(**真发消息,不可撤回**)。"""
    slot = req.slot if req and req.slot else "11:30"
    payload = await _generate(slot)
    delivered = await dispatch_intraday_review(payload)
    return {
        "trade_date": payload.get("trade_date"),
        "slot": payload.get("slot"),
        "delivered": [
            {"channel": d.channel, "ok": d.ok, "detail": d.detail} for d in delivered
        ],
        "review": payload,
    }


__all__ = ["router"]
