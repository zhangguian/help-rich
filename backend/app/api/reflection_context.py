"""/api/reflection-context 端点 (改动 C)

返回 ReflectionCard 22:00 消息面上下文提示用数据。"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.core.stock_code import normalize_code
from app.data.ifind_events import IfindUnavailable
from app.modules.portfolio.repository import transaction_repo
from app.repositories.watchlist_repo import watchlist_repo
from app.modules.portfolio.service import get_all_positions
from app.services.reflection_context_service import (
    build_reflection_context,
    get_reflection_context_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reflection-context", tags=["reflection-context"])


async def _collect_relevant_codes(target: date) -> set[str]:
    """收集相关股票代码: 持仓 + 自选股 + 今日交易."""
    codes: set[str] = set()

    # 持仓
    positions = await get_all_positions()
    for p in positions:
        normalized = normalize_code(p.stock_code)
        codes.add(normalized or p.stock_code)

    # 自选股 (list_all 已实现,返 Watchlist ORM 对象列表)
    watchlist = await watchlist_repo.list_all()
    for w in watchlist:
        raw = getattr(w, "stock_code", None) or (w.get("stock_code") if isinstance(w, dict) else None)
        if raw:
            normalized = normalize_code(raw)
            codes.add(normalized or raw)

    # 今日交易 (transaction_repo 没有 list_by_date,使用 list_all 后 filter in memory;MVP 量级可接受)
    all_tx, _ = await transaction_repo.list_all(limit=500)
    for t in all_tx:
        if t.trade_date == target:
            normalized = normalize_code(t.stock_code)
            codes.add(normalized or t.stock_code)

    return {c for c in codes if c}


@router.get("")
async def get_reflection_context(
    date_str: str = Query(..., alias="date", description="YYYY-MM-DD"),
) -> dict:
    """拉取当日 ReflectionCard 消息面上下文汇总。

    流程:
    1. 收集相关股票: 持仓 + 自选股 + 今日交易
    2. build_reflection_context (写当日缓存, 失败 fail-fast 返 503)
    3. 返 summary
    """
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"date 格式错: {date_str}")

    codes = await _collect_relevant_codes(target)

    try:
        await build_reflection_context(sorted(codes), target)
    except IfindUnavailable as e:
        logger.warning("reflection-context ifind failed: %s", e)
        raise HTTPException(status_code=503, detail=f"ifind 拉取失败: {e}")

    summary = await get_reflection_context_summary(target)
    return {
        "date": date_str,
        "summary": summary,
        "fetched_for_count": len(codes),
        "fetched_for": sorted(codes),
    }


__all__ = ["router"]