"""thsifind search_news + search_notice 包装层 (改动 C)

ReflectionCard 22:00 弹窗消息面提示用."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from app.data.ifind_events import IfindUnavailable  # 复用统一异常


try:
    from mcode_tools_connector import call as _mcode_call
except ImportError:
    _mcode_call = None


_CN_TZ = timezone(timedelta(hours=8))


async def _search_news(query: str, size: int, time_start: str, time_end: str) -> list[dict[str, Any]]:
    if _mcode_call is None:
        raise IfindUnavailable("mcode-tools connector 未安装")
    return await _mcode_call(
        "thsifind__search_news",
        {"query": query, "size": size, "time_start": time_start, "time_end": time_end},
    )


async def _search_notice(query: str, size: int, time_start: str, time_end: str) -> list[dict[str, Any]]:
    if _mcode_call is None:
        raise IfindUnavailable("mcode-tools connector 未安装")
    return await _mcode_call(
        "thsifind__search_notice",
        {"query": query, "size": size, "time_start": time_start, "time_end": time_end},
    )


def _normalize_items(raw: list) -> list[dict]:
    out = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        out.append({
            "title": r.get("title") or r.get("notice_title") or "",
            "date": r.get("date") or r.get("publish_date") or r.get("time") or "",
        })
    return out


async def fetch_news_for_stock(
    stock_code: str,
    start_date: str,
    end_date: str,
    news_size: int = 5,
    notice_size: int = 5,
) -> dict[str, Any]:
    """拉取单只票在指定日期范围内的新闻 + 公告.

    Returns:
        {
            "stock_code": "600519.SH",
            "announcements": [{"title": ..., "date": ...}, ...],
            "news": [{"title": ..., "date": ...}, ...],
            "fetched_at": "2026-09-22T22:00:00+08:00",
        }

    Raises:
        IfindUnavailable: 任一 ifind 调用失败
    """
    query_base = f"{stock_code}"

    try:
        raw_news = await _search_news(
            query=query_base, size=news_size, time_start=start_date, time_end=end_date,
        )
    except Exception as e:
        raise IfindUnavailable(f"search_news 失败: {e}") from e

    try:
        raw_notices = await _search_notice(
            query=query_base, size=notice_size, time_start=start_date, time_end=end_date,
        )
    except Exception as e:
        raise IfindUnavailable(f"search_notice 失败: {e}") from e

    return {
        "stock_code": stock_code,
        "announcements": _normalize_items(raw_notices if isinstance(raw_notices, list) else []),
        "news": _normalize_items(raw_news if isinstance(raw_news, list) else []),
        "fetched_at": datetime.now(_CN_TZ).isoformat(),
    }


__all__ = ["fetch_news_for_stock"]
