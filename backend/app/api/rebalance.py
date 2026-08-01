"""智能调仓建议 API(A4)

- GET /api/rebalance-suggestion
"""
from fastapi import APIRouter

from app.services.position_service import get_all_positions
from app.services.rebalance_service import PositionLite, calculate_rebalance

router = APIRouter(prefix="/rebalance-suggestion", tags=["rebalance"])


@router.get("")
async def get_rebalance_suggestion() -> dict:
    """基于当前持仓生成调仓建议(纯本地计算,纯结构判断)"""
    positions = await get_all_positions()
    payload: list[PositionLite] = [
        PositionLite(
            stock_code=p.stock_code,
            stock_name=p.stock_name,
            shares=p.shares,
            avg_cost=str(p.avg_cost),
            # MVP 无实时价,用持仓总成本作市值估算
            market_value=float(p.total_cost),
        )
        for p in positions
    ]
    return calculate_rebalance(payload)


__all__ = ["router"]