"""thsifind search_trending_news 包装层 (改动 A)

提供盘后选股事件因子所需数据:
- fetch_trending_events: 拉取热门事件, 归一为 {event_keywords, stock_codes}
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

# 工具栏内 connector 入口 (mock fixture patch 此路径)
try:
    from mcode_tools_connector import call as _mcode_call
except ImportError:
    _mcode_call = None  # 测试环境无 mcode-tools 时降级, 由 fixture mock


class IfindUnavailable(Exception):
    """ifind 调用失败 (screener 与 reflection 统一异常基类)"""


_CN_TZ = timezone(timedelta(hours=8))


async def _search_trending_news(time_scope: str, size: int, sensitive: str = "全部") -> list[dict[str, Any]]:
    """工具栏入口 (mock 入口). 生产路径走 mcode-tools."""
    if _mcode_call is None:
        raise IfindUnavailable("mcode-tools connector 未安装")
    return await _mcode_call(
        "thsifind__search_trending_news",
        {"time_scope": time_scope, "size": size, "sensitive": sensitive},
    )


async def fetch_trending_events(size: int = 20, time_scope: str = "24小时") -> dict[str, Any]:
    """拉取热门事件, 归一返回.

    Returns:
        {
            "fetched_at": "2026-09-22T22:00:00+08:00",
            "event_keywords": set[str],   # e.g. {"AI", "新能源"}
            "stock_codes": set[str],       # e.g. {"600519.SH", "300750.SZ"}
            "raw": list[dict],             # 原始数据, 供调试/审计
        }
    """
    try:
        raw = await _search_trending_news(time_scope=time_scope, size=size)
    except Exception as e:
        raise IfindUnavailable(f"search_trending_news 失败: {e}") from e

    if not isinstance(raw, list):
        raise IfindUnavailable(f"search_trending_news 返回非 list: {type(raw).__name__}")

    keywords: set[str] = set()
    codes: set[str] = set()
    for r in raw:
        if not isinstance(r, dict):
            continue
        tags = r.get("tags") or []
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, str):
                    keywords.add(t.strip())
        stocks = r.get("stocks") or []
        if isinstance(stocks, list):
            for s in stocks:
                if isinstance(s, str):
                    codes.add(s.strip().upper())

    return {
        "fetched_at": datetime.now(_CN_TZ).isoformat(),
        "event_keywords": keywords,
        "stock_codes": codes,
        "raw": raw,
    }


__all__ = ["IfindUnavailable", "fetch_trending_events"]
