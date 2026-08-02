"""K 线 API(guide §3.2 新浪备用)

- GET /api/kline/{stock_code}?period=daily&limit=60
- GET /api/kline/{stock_code}/indicators?period=&limit=
    K 线 + 全量指标 + 信号标注点(轻量,不触发 LLM、不进前端 IndexedDB 缓存)
- 数据源失败 → 502 DATA_SOURCE_UNAVAILABLE(无 mock 兜底)
"""
from fastapi import APIRouter, HTTPException

from app.core.stock_code import normalize_code
from app.services.kline_service import KLineSourceUnavailable, fetch_klines
from app.services.ta_service import TaError, compute_indicators

router = APIRouter(prefix="/kline", tags=["kline"])


@router.get("/{stock_code}/indicators")
async def get_kline_indicators(
    stock_code: str,
    period: str = "daily",
    limit: int = 120,
) -> dict:
    """K 线 + 全量技术指标(K线图叠加专用,轻量端点)

    - 数据源失败 → 502
    - 计算失败 / 数据不足 → 指标字段为 None/空,degraded 列表说明
    """
    if period not in {"daily", "weekly", "monthly", "60min", "30min", "15min", "5min", "1min"}:
        raise HTTPException(
            status_code=400,
            detail={"code": "UNSUPPORTED_PERIOD", "message": f"暂不支持 period={period}"},
        )
    if limit < 30 or limit > 500:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_LIMIT", "message": "limit 应在 30~500"},
        )
    normalized = normalize_code(stock_code)
    if normalized is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_STOCK_CODE", "message": "代码格式应为 6 位数字或带市场后缀"},
        )

    try:
        items = await fetch_klines(normalized, period=period, count=limit)
    except KLineSourceUnavailable as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e

    try:
        indicators = compute_indicators(items)
    except TaError as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "INDICATOR_CALC_FAILED", "message": str(e)},
        ) from e

    return {
        "stock_code": normalized,
        "period": period,
        "count": len(items),
        "items": items,
        "indicators": indicators,
    }


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