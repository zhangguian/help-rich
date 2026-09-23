"""thsifind search_securities 包装层 (改动 B)

screener Top N 基本面兜底过滤用."""
from __future__ import annotations

from typing import Any

from app.data.ifind_events import IfindUnavailable  # 复用统一异常


try:
    from mcode_tools_connector import call as _mcode_call
except ImportError:
    _mcode_call = None


async def _search_securities(market: str, query: str) -> list[dict[str, Any]]:
    if _mcode_call is None:
        raise IfindUnavailable("mcode-tools connector 未安装")
    return await _mcode_call(
        "thsifind__search_securities",
        {"market": market, "query": query},
    )


async def is_hit_fundamental_filter(stock_code: str, query: str, market: str = "A股") -> bool:
    """单只票是否命中基本面筛条件.

    Args:
        stock_code: 6 位股票代码 (规整后)
        query: 筛条件字符串 (e.g. "扣非ROE>0 PE<行业中位数 剔除ST")
        market: 默认 A 股

    Returns:
        True = 命中 (通过筛条件), False = 不命中 (踢出)

    Raises:
        IfindUnavailable: ifind 调用失败
    """
    try:
        raw = await _search_securities(market=market, query=query)
    except Exception as e:
        raise IfindUnavailable(f"search_securities 失败: {e}") from e

    if not isinstance(raw, list):
        raise IfindUnavailable(f"search_securities 返回非 list: {type(raw).__name__}")

    norm = stock_code.upper().strip()
    for r in raw:
        if not isinstance(r, dict):
            continue
        code = r.get("stock_code")
        if isinstance(code, str) and code.upper().strip() == norm:
            return bool(r.get("hit", False))
    return False


__all__ = ["is_hit_fundamental_filter"]