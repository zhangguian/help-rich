"""K 线 API(guide §3.2 新浪备用)

- GET /api/kline/{stock_code}?period=daily&limit=60
- 数据源失败 → 502 DATA_SOURCE_UNAVAILABLE(无 mock 兜底)
"""
from fastapi import APIRouter, HTTPException

from app.services.kline_service import KLineSourceUnavailable, fetch_klines

router = APIRouter(prefix="/kline", tags=["kline"])


@router.get("/{stock_code}")
async def get_kline(
    stock_code: str,
    period: str = "daily",
    limit: int = 60,
) -> dict:
    """获取 K 线(guide §3.2 新浪;数据源失败返 502)"""
    if period not in {"daily", "weekly", "monthly", "60min", "30min", "15min", "5min", "1min"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "UNSUPPORTED_PERIOD", "message": f"暂不支持 period={period}"},
        )
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_LIMIT", "message": "limit 应在 1~500"},
        )
    try:
        items = await fetch_klines(stock_code, period=period, count=limit)
    except KLineSourceUnavailable as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e
    return {
        "stock_code": stock_code,
        "period": period,
        "count": len(items),
        "items": items,
    }


__all__ = ["router"]