"""大盘盯盘服务(v0.4-roadmap §3.9 大盘盯盘模块)

- 三大主指:上证 / 深证 / 创业板(走 QuoteService,5min JSONCache)
- 领涨 / 领跌:沪深 A 股排行前 3(走新浪接口 fetch_market_movers)

降级策略:
- 指数部分任一失败 → 单只缺失不影响整体,缺位标 --
- 领涨 / 领跌失败 → 返回空数组(不影响指数部分)
"""
import logging
from datetime import datetime
from typing import Any

from app.data.sina import fetch_market_movers
from app.services.quote_service import QuoteService

logger = logging.getLogger(__name__)

INDEX_CODES = ["000001.SH", "399001.SZ", "399006.SZ"]

_index_service: QuoteService | None = None


def get_market_index_service() -> QuoteService:
    """指数行情服务单例(与普通股票共用 QuoteService + 5min 缓存)"""
    global _index_service
    if _index_service is None:
        _index_service = QuoteService()
    return _index_service


def _quote_to_index_dict(q) -> dict[str, Any]:
    """UnifiedQuote → 大盘指数响应字段"""
    return {
        "code": q.code,
        "name": q.name,
        "current_price": str(q.current_price),
        "prev_close": str(q.prev_close),
        "open": str(q.open),
        "high": str(q.high),
        "low": str(q.low),
        "change": str(q.change),
        "change_pct": q.change_pct,
        "volume": q.volume,
        "amount": str(q.amount),
        "timestamp": q.timestamp.isoformat(),
    }


async def _fetch_indexes() -> list[dict[str, Any]]:
    """拉三大主指,失败 → 返回空 list(前端按缺失处理)"""
    try:
        quotes = await get_market_index_service().get_quotes(INDEX_CODES)
    except Exception as e:  # noqa: BLE001
        logger.warning("大盘指数拉取失败: %s", e)
        return []
    found_map = {q.code: _quote_to_index_dict(q) for q in quotes}
    # 按 INDEX_CODES 顺序回填,缺失 → None 占位(让前端能按位显示 --)
    return [found_map.get(code) for code in INDEX_CODES]


async def _fetch_movers(direction: str, num: int = 3) -> list[dict[str, Any]]:
    """拉领涨(up)/领跌(down)前 N,失败 → []

    注:direction 非法由 fetch_market_movers 抛 ValueError,此处透传不兜,
    让上层明确感知(避免静默错误)。
    """
    try:
        raw = await fetch_market_movers(direction=direction, num=num)
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("大盘 %s 排行拉取失败: %s", direction, e)
        return []
    out: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        symbol = r.get("symbol") or ""
        if not symbol:
            continue
        # symbol 形如 "sh600519" / "sz000001",需归一化为 600519.SH
        prefix = symbol[:2]
        num_part = symbol[2:]
        market = {"sh": "SH", "sz": "SZ", "bj": "BJ"}.get(prefix, "SH")
        code = f"{num_part}.{market}"
        try:
            change_pct = float(r["changeratio"])
            trade = float(r["trade"])
        except (KeyError, TypeError, ValueError):
            # 关键字段缺失或解析失败 → 跳过这条(避免污染榜单)
            continue
        out.append({
            "code": code,
            "name": r.get("name", ""),
            "current_price": f"{trade:.3f}",
            "change_pct": change_pct,
        })
    return out


async def get_market_overview() -> dict[str, Any]:
    """大盘盯盘总览(指数 + 领涨 + 领跌)

    Returns: {indexes: list[dict|None], gainers: list, losers: list, fetched_at}
    单一部分失败不阻断整体。
    """
    indexes = await _fetch_indexes()
    gainers = await _fetch_movers("up", 3)
    losers = await _fetch_movers("down", 3)
    return {
        "indexes": indexes,
        "gainers": gainers,
        "losers": losers,
        "fetched_at": datetime.now().isoformat(),
    }


def reset_market_overview_service() -> None:
    """测试辅助:重置指数服务单例"""
    global _index_service
    _index_service = None


__all__ = [
    "INDEX_CODES",
    "get_market_index_service",
    "get_market_overview",
    "reset_market_overview_service",
]