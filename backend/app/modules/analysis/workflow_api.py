"""三段式 Agent API(阶段4)

- GET  /api/workflow/schedule   → 时间窗配置(前端展示"下次什么时候跑")
- POST /api/workflow/premarket  → 立即生成盘前简报(不推送)
- POST /api/workflow/premarket/dispatch → 生成并推送
- POST /api/workflow/intraday   → 立即生成盘中速览(不推送;slot: 11:30 / 14:00 / 14:50)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.modules.analysis.workflow_scheduler import SLOT_LABEL, TIME_WINDOWS
from app.modules.analysis.workflow import workflow_agent_service

router = APIRouter(prefix="/workflow", tags=["workflow"])

# 盘中档位:11:30(上午收盘)/ 14:00(下午盘初,阶段 T2 起)/ 14:50(尾盘,历史档位)
INTRADAY_SLOTS = ("11:30", "14:00", "14:50")


class IntradayIn(BaseModel):
    slot: str = "11:30"
    dispatch: bool = False


@router.get("/schedule")
async def schedule() -> dict:
    """调度时间窗(供前端展示)。"""
    return {
        "windows": [
            {
                "kind": kind,
                "at": SLOT_LABEL.get(kind, kind),
                "hour": h,
                "minute": m,
            }
            for kind, h, m, _ in TIME_WINDOWS
        ]
    }


@router.post("/premarket")
async def premarket() -> dict:
    try:
        result = await workflow_agent_service.run_premarket()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"生成盘前简报失败: {e}") from e
    return {
        "kind": result.kind,
        "title": result.title,
        "summary": result.summary,
        "lines": result.lines,
        "stock_codes": result.stock_codes,
    }


@router.post("/premarket/dispatch")
async def premarket_dispatch() -> dict:
    try:
        result = await workflow_agent_service.run_premarket()
        delivered = await workflow_agent_service.dispatch(result)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"推送失败: {e}") from e
    return {
        "kind": result.kind,
        "summary": result.summary,
        "delivered": [
            {"channel": d.channel, "ok": d.ok, "detail": d.detail} for d in delivered
        ],
    }


@router.post("/intraday")
async def intraday(payload: IntradayIn) -> dict:
    """生成盘中速览(异动扫描;阶段 T2 起,盘中主产出是 `/api/intraday-review`)。"""
    if payload.slot not in INTRADAY_SLOTS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的档位: {payload.slot}(可用: {', '.join(INTRADAY_SLOTS)})",
        )
    try:
        result = await workflow_agent_service.run_intraday(payload.slot)
        delivered = await workflow_agent_service.dispatch(result) if payload.dispatch else []
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"生成盘中速览失败: {e}") from e
    return {
        "kind": result.kind,
        "title": result.title,
        "summary": result.summary,
        "lines": result.lines,
        "stock_codes": result.stock_codes,
        "delivered": [
            {"channel": d.channel, "ok": d.ok, "detail": d.detail} for d in delivered
        ],
    }
