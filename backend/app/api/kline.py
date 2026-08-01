"""K 线 API(D)

- GET /api/kline/{stock_code}?period=daily&limit=60  返回日 K 线
"""
from fastapi import APIRouter, HTTPException

from app.services.kline_service import fetch_klines

router = APIRouter(prefix="/kline", tags=["kline"])


@router.get("/{stock_code}")
async def get_kline(
    stock_code: str,
    period: str = "daily",
    limit: int = 60,
) -> dict:
    """获取 K 线(MVP:mock 数据,v0.2.2 接 akshare)"""
    if period not in {"daily", "weekly"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "UNSUPPORTED_PERIOD", "message": f"暂不支持 period={period}"},
        )
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_LIMIT", "message": "limit 应在 1~500"},
        )
    items = await fetch_klines(stock_code, period=period, count=limit)
    return {
        "stock_code": stock_code,
        "period": period,
        "count": len(items),
        "items": items,
    }


__all__ = ["router"]