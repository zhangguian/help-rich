"""持仓体检 API(v0.4.0)

- GET /api/holdings-health → 持仓体检(组合浮盈 + 单只盈亏 + 风险评分)
"""
from fastapi import APIRouter

from app.services.holdings_health_service import get_holdings_health

router = APIRouter(prefix="/holdings-health", tags=["holdings-health"])


@router.get("")
async def holdings_health() -> dict:
    """持仓体检:从真实持仓表出发,结合实时行情计算组合/单只健康度"""
    try:
        return await get_holdings_health()
    except Exception as e:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=502,
            detail={"code": "HEALTH_ERROR", "message": str(e)},
        ) from e


__all__ = ["router"]
