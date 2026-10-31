"""K 线 API(guide §3.2 新浪备用)

- GET /api/kline/{stock_code}?period=daily&limit=60
- GET /api/kline/{stock_code}/indicators?period=&limit=
    K 线 + 全量指标 + 信号标注点(轻量,不触发 LLM、不进前端 IndexedDB 缓存)
    追加 `behavior_markers`:四类异动行为标注(主力异动/低吸/锁仓/高抛)
- 数据源失败 → 502 DATA_SOURCE_UNAVAILABLE(无 mock 兜底)
"""
from fastapi import APIRouter, HTTPException

from app.core.config import BEHAVIOR_MARKERS_LOOKBACK_DAYS
from app.core.stock_code import normalize_code
from app.services.behavior_fund_flow_service import (
    FundFlowUnavailable,
    align_by_date,
    fetch_flow_daily,
)
from app.services.behavior_signal_service import (
    base_date_from_klines,
    detect_behavior_markers,
    filter_markers_by_window,
)
from app.services.kline_service import KLineSourceUnavailable, fetch_intraday, fetch_klines
from app.services.overview_service import get_overview
from app.services.ta_service import TaError, compute_indicators

router = APIRouter(prefix="/kline", tags=["kline"])


async def _build_behavior_markers(
    normalized: str,
    items: list[dict],
    period: str,
) -> tuple[list[dict], bool]:
    """算四类异动行为标注。

    Returns:
        (markers, unavailable) —— `unavailable=True` 表示资金流不可用,
        此时 markers 为空(**不编数字**),但 K 线与既有指标照常返回。
    """
    # 只对**日线**做形态回溯标注(周/月/分钟线的口径不同,含义会误导)
    if period != "daily" or not items:
        return [], False

    try:
        flows = await fetch_flow_daily(normalized, count=len(items))
    except FundFlowUnavailable:
        return [], True
    except Exception:  # noqa: BLE001 —— 任何异常都只降级,绝不阻断 K 线主流程
        return [], True

    flows_by_date = align_by_date(flows)
    result = detect_behavior_markers(items, flows_by_date)

    # 只回传最近 N 个**日历天**的标注(避免响应体过大)
    #
    # ⚠️ **两条路径共用 `filter_markers_by_window`**(闸 2 完备闸):
    # 旧版这里自己算阈值,基准日取不到时还**全量返回**(窗口闸门形同虚设);
    # 找股路径用的是「跑批日」—— 两边口径不同
    # (实测 61% 的信号找股页有、K 线上找不到)。
    # 现在两边都用「该票自己的 K 线末根日期」作基准日、走同一个过滤函数,
    # 一致性由**同一实现**物理保证。
    if not result.markers:
        return [], False
    base = base_date_from_klines(items)
    if base is None:
        # 基准日取不到 → 无法判断窗口 → **不产出标注**(不编数字)
        return [], False
    windowed = filter_markers_by_window(
        result.markers, base, BEHAVIOR_MARKERS_LOOKBACK_DAYS
    )
    return [m.to_dict() for m in windowed], False


@router.get("/{stock_code}/indicators")
async def get_kline_indicators(
    stock_code: str,
    period: str = "daily",
    limit: int = 120,
) -> dict:
    """K 线 + 全量技术指标(K线图叠加专用,轻量端点)

    - 数据源失败 → 502
    - 计算失败 / 数据不足 → 指标字段为 None/空,degraded 列表说明
    - 资金流不可用 → `behavior_markers=[]` + `behavior_markers_unavailable=true`,
      **不影响** K 线与既有指标
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

    behavior_markers, behavior_unavailable = await _build_behavior_markers(
        normalized, items, period
    )

    return {
        "stock_code": normalized,
        "period": period,
        "count": len(items),
        "items": items,
        "indicators": indicators,
        "behavior_markers": behavior_markers,
        "behavior_markers_unavailable": behavior_unavailable,
    }


@router.get("/{stock_code}/overview")
async def get_overview_endpoint(stock_code: str) -> dict:
    """M2.3 三线叠加:个股 + 大盘(000001.SH) + 行业(归一化日K)

    行业未命中 / 拉取失败 → sector=[] 与 sector_unavailable=true(空态,
    不影响前两条)。个股 K 线失败 → 502。
    """
    normalized = normalize_code(stock_code)
    if normalized is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_STOCK_CODE", "message": "代码格式应为 6 位数字或带市场后缀"},
        )
    try:
        data = await get_overview(normalized)
    except KLineSourceUnavailable as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e
    return data


@router.get("/{stock_code}/intraday")
async def get_intraday(stock_code: str) -> dict:
    """当日分时数据(分钟线聚合:价格 + 均价线 + 成交量)

    - 数据源失败 → 502
    - 未开盘/无分钟数据 → items 为空(不报错)
    """
    normalized = normalize_code(stock_code)
    if normalized is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_STOCK_CODE", "message": "代码格式应为 6 位数字或带市场后缀"},
        )
    try:
        data = await fetch_intraday(normalized)
    except KLineSourceUnavailable as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": str(e)},
        ) from e
    return data


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