"""风险敞口 API(C1)

- GET /api/risk-report → 基于当前持仓计算风险报告
"""
from fastapi import APIRouter

from app.services.position_service import get_all_positions
from app.services.risk_service import PositionExposure, calc_risk

router = APIRouter(prefix="/risk-report", tags=["risk-report"])


@router.get("")
async def get_risk_report() -> dict:
    """根据当前持仓计算风险敞口报告"""
    positions = await get_all_positions()
    exposures: list[PositionExposure] = [
        PositionExposure(
            stock_code=p.stock_code,
            stock_name=p.stock_name,
            shares=p.shares,
            avg_cost=str(p.avg_cost),
            market_value=float(p.shares * p.avg_cost),
        )
        for p in positions
    ]
    return calc_risk(exposures)


__all__ = ["router"]