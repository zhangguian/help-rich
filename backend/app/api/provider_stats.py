"""多 Provider 占比月度统计 API(A3 / v0.4.1)

- GET /api/provider-stats/monthly?year=2026   12 个月分布
- GET /api/provider-stats/summary?year=2026   年度汇总(柱状图友好)
"""
from fastapi import APIRouter, HTTPException, Query

from app.services.provider_stats_service import (
    get_monthly_provider_stats,
    get_provider_summary,
    validate_year,
)

router = APIRouter(prefix="/provider-stats", tags=["provider-stats"])


@router.get("/monthly")
async def get_monthly(year: int = Query(default=2026, ge=2020, le=2100)) -> dict:
    """12 个月 Provider 分布

    每条:{"month": "2026-01", "total": N, "providers": {...}, "statuses": {...}}
    """
    if not validate_year(year):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_YEAR", "message": f"year 范围应在 2020~{year}"},
        )
    items = await get_monthly_provider_stats(year)
    return {"year": year, "items": items}


@router.get("/summary")
async def get_summary(year: int = Query(default=2026, ge=2020, le=2100)) -> dict:
    """年度 Provider 汇总(柱状图)

    providers: [{"provider": "deepseek", "count": x, "pct": y}, ...]
    """
    return await get_provider_summary(year)


__all__ = ["router"]