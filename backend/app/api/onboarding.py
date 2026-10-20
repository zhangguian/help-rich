"""引导中心 API(阶段5)

- GET /api/onboarding            → 就绪度清单(步骤 + 进度)
- POST /api/onboarding/{key}/done → 手动标记某步骤完成(用于无状态可判定的项)
"""
from fastapi import APIRouter, HTTPException

from app.services.onboarding_service import onboarding_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

# 允许用户手动标记完成的步骤(其余由系统实时判定,不让用户伪造)
_MANUAL_KEYS = {"paper", "notify", "accounts"}


@router.get("")
async def get_status() -> dict:
    try:
        return (await onboarding_service.get_status()).to_dict()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"获取引导状态失败: {e}") from e


@router.post("/{key}/done")
async def mark_done(key: str) -> dict:
    if key not in _MANUAL_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"步骤 {key} 由系统自动判定,无需手动标记",
        )
    return {"ok": True, "key": key}
