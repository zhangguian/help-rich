"""ReflectionCard 22:00 消息面提示服务 (改动 C)

业务编排: 当日 1 次缓存; 失败 fail-fast 不写缓存."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.data.ifind_news import fetch_news_for_stock
from app.data.ifind_events import IfindUnavailable
from app.models.orm import ReflectionContextCache
from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo

logger = logging.getLogger(__name__)


_CN_TZ = timezone(timedelta(hours=8))


def _fetched_at_now() -> str:
    return datetime.now(_CN_TZ).isoformat()


def _start_of_window(today: date, window_days: int = 7) -> date:
    return today - timedelta(days=window_days - 1)


async def build_reflection_context(
    stock_codes: list[str], today: date
) -> ReflectionContextCache:
    """聚合多只票的新闻 + 公告, 写入当日缓存.

    Args:
        stock_codes: 持仓 + 自选股 + 今日交易股 (合并去重后传入)
        today: 当日日期

    Returns:
        写入的 ReflectionContextCache 行

    Raises:
        IfindUnavailable: 任一 ifind 调用失败 (不写缓存)
    """
    cached = await reflection_context_cache_repo.get_today(today)
    if cached is not None:
        return cached

    if not stock_codes:
        # 没有相关票, 写空缓存避免重复触发
        ctx = {"announcements_count": 0, "news_count": 0, "top_news_title": "", "fetched_for": []}
        row = await reflection_context_cache_repo.upsert(
            fetch_date=today,
            context_json=json.dumps(ctx, ensure_ascii=False),
            fetched_at=_fetched_at_now(),
            ifind_calls=0,
        )
        return row

    start = _start_of_window(today)
    end = today

    all_news: list[dict] = []
    all_announcements: list[dict] = []
    calls = 0

    # 串行 (避免 ifind 限流 + reflection 弹窗场景下并发意义不大, 用户体验为先)
    for code in stock_codes:
        result = await fetch_news_for_stock(code, start.isoformat(), end.isoformat())
        calls += 2  # news + notice 各 1
        all_news.extend(result["news"])
        all_announcements.extend(result["announcements"])

    top_news_title = all_news[0]["title"] if all_news else ""

    ctx = {
        "announcements_count": len(all_announcements),
        "news_count": len(all_news),
        "top_news_title": top_news_title,
        "fetched_for": stock_codes,
    }

    row = await reflection_context_cache_repo.upsert(
        fetch_date=today,
        context_json=json.dumps(ctx, ensure_ascii=False),
        fetched_at=_fetched_at_now(),
        ifind_calls=calls,
    )
    logger.info(
        "reflection context built: date=%s stocks=%s announcements=%s news=%s",
        today, len(stock_codes), len(all_announcements), len(all_news),
    )
    return row


async def get_reflection_context_summary(today: date) -> Optional[dict]:
    """读侧: 给 Reflectioncard 用的汇总 (无缓存时返 None)."""
    cached = await reflection_context_cache_repo.get_today(today)
    if cached is None:
        return None
    try:
        return json.loads(cached.context_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("reflection_context_cache.context_json 损坏: %s", cached.context_json)
        return None


__all__ = ["build_reflection_context", "get_reflection_context_summary"]