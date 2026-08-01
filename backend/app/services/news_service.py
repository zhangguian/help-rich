"""新浪快讯服务(guide §9.2)"""
import logging
from typing import Any

from app.data.sina import fetch_sina_news

logger = logging.getLogger(__name__)


async def get_sina_news(page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
    """7×24 快讯(guide §9.2 新浪 zhibo)"""
    raw = await fetch_sina_news(page=page, page_size=page_size)
    out: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        out.append({
            "id": r.get("id"),
            "rich_text": r.get("rich_text", ""),
            "type": r.get("type"),
            "create_time": r.get("create_time"),
            "tag": r.get("tag", ""),
        })
    return out


__all__ = ["get_sina_news"]