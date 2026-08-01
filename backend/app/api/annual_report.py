"""年度账单 API(P6.1 / v0.2 接口预留)"""
from fastapi import APIRouter, HTTPException

from app.models.schemas import AnnualReportOut
from app.services.annual_report_service import get_annual_report

router = APIRouter(prefix="/annual-report", tags=["annual-report"])


@router.get("/{year}", response_model=AnnualReportOut)
async def annual_report(year: int) -> AnnualReportOut:
    """年度账单聚合(已实现盈亏 + 胜率 + Top5)"""
    if year < 2000 or year > 2100:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_YEAR", "message": "年份超出合理范围"},
        )
    return AnnualReportOut(**(await get_annual_report(year)))