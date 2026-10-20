"""screener 事件因子服务 (改动 A)

业务编排: 当日 1 次缓存; 失败 fail-fast 不写缓存."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from app.data.ifind_events import IfindUnavailable, fetch_trending_events
from app.models.orm import EventFactorCache
from app.repositories.event_factor_cache_repo import event_factor_cache_repo

logger = logging.getLogger(__name__)


async def build_event_factor_cache(trade_date: date) -> EventFactorCache:
    """拉取 ifind 热门事件并写当日缓存; 已缓存则跳过.

    Raises:
        IfindUnavailable: ifind 拉取失败 (不写缓存)
    """
    cached = await event_factor_cache_repo.get_today(trade_date)
    if cached is not None:
        return cached

    result = await fetch_trending_events(size=20)

    row = await event_factor_cache_repo.upsert(
        trade_date=trade_date,
        event_keywords_json=json.dumps(sorted(result["event_keywords"]), ensure_ascii=False),
        stock_codes_json=json.dumps(sorted(result["stock_codes"]), ensure_ascii=False),
        fetched_at=result["fetched_at"],
        ifind_calls=1,
    )
    logger.info(
        "event factor cache built: trade_date=%s codes=%s",
        trade_date, len(result["stock_codes"]),
    )
    return row


async def get_event_factor_codes(trade_date: date) -> set[str]:
    """读侧: 给 screener 用的事件命中股票代码集合 (空集 = 今日无事件或缓存失败)."""
    cached = await event_factor_cache_repo.get_today(trade_date)
    if cached is None:
        return set()
    try:
        codes = json.loads(cached.stock_codes_json)
        return {c.upper() for c in codes if isinstance(c, str)}
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "event_factor_cache.stock_codes_json 损坏: %s", cached.stock_codes_json,
        )
        return set()


__all__ = ["build_event_factor_cache", "get_event_factor_codes"]
