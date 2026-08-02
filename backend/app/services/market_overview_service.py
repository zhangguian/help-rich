"""大盘盯盘服务(v0.4-roadmap §3.9 大盘盯盘模块)

主路径(overview):
- 三大主指:上证 / 深证 / 创业板(走 QuoteService,5min JSONCache)
- 领涨 / 领跌:沪深 A 股排行前 3(走新浪接口 fetch_market_movers)

扩展路径(v0.4.1 行情中心):
- 指数 sparkline:走新浪 K 线接口(不落 KlineCache)
- 涨跌家数 + 区间分布:hs_a 接口聚合
- A 股个股主力净流入榜:hs_a 估算(降级方案)

降级策略:
- 指数部分任一失败 → 单只缺失不影响整体,缺位标 --
- 领涨 / 领跌失败 → 返回空数组(不影响指数部分)
- 扩展端点失败 → 整体端点返 503
"""
import logging
from datetime import datetime
from typing import Any

import httpx

from app.core.stock_code import normalize_code
from app.data.sina import SINA_HEADERS
from app.services.kline_service import _fetch_sina_kline
from app.services.quote_service import QuoteService

logger = logging.getLogger(__name__)

# ============ overview(主路径) ============

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
    return [found_map.get(code) for code in INDEX_CODES]


async def _fetch_movers(direction: str, num: int = 3) -> list[dict[str, Any]]:
    """拉领涨(up)/领跌(down)前 N,失败 → []

    注:direction 非法由 fetch_market_movers 抛 ValueError,此处透传不兜。
    """
    from app.data.sina import fetch_market_movers
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
        prefix = symbol[:2]
        num_part = symbol[2:]
        market = {"sh": "SH", "sz": "SZ", "bj": "BJ"}.get(prefix, "SH")
        code = f"{num_part}.{market}"
        try:
            change_pct = float(r["changeratio"])
            trade = float(r["trade"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({
            "code": code,
            "name": r.get("name", ""),
            "current_price": f"{trade:.3f}",
            "change_pct": change_pct,
        })
    return out


async def get_market_overview() -> dict[str, Any]:
    """大盘盯盘总览(指数 + 领涨 + 领跌)"""
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


# ============ 扩展:指数 sparkline ============


async def _fetch_one_spark(code: str, count: int) -> list[dict[str, Any]]:
    """单只指数 sparkline(直接调新浪 K 线 JSONP,不落 KlineCache)

    返回 [{date, close}, ...] 升序
    """
    normalized = normalize_code(code) or code
    rows = await _fetch_sina_kline(normalized, period="daily", count=count)
    return [{"date": r["date"], "close": float(r["close"])} for r in rows]


async def fetch_market_sparklines(count: int = 60) -> dict[str, list[dict[str, Any]]]:
    """三大主指迷你趋势线(供 sparkline 用)

    返回:{"000001.SH": [{date, close}, ...], "399001.SZ": [...], "399006.SZ": [...]}
    单只失败 → 空 list,不影响其它
    """
    out: dict[str, list[dict[str, Any]]] = {code: [] for code in INDEX_CODES}
    for code in INDEX_CODES:
        try:
            out[code] = await _fetch_one_spark(code, count)
        except Exception as e:  # noqa: BLE001
            logger.warning("指数 sparkline 拉取失败 %s: %s", code, e)
            out[code] = []
    return out


# ============ 扩展:涨跌家数 + 区间分布 ============


_SENTIMENT_URL = (
    "https://vip.stock.finance.sina.com.cn/"
    "quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
)


async def _fetch_hs_a_quotes(page_size: int = 200) -> list[dict[str, Any]]:
    """沪深 A 股全市场快照首页(用于涨跌家数统计)

    MVP 取首页 page_size=200,反映情绪概览,非全市场精确统计。
    """
    params = {
        "node": "hs_a",
        "sort": "changepercent",
        "asc": 0,
        "num": page_size,
        "page": 1,
    }
    async with httpx.AsyncClient(
        headers=SINA_HEADERS, timeout=15.0, trust_env=False
    ) as client:
        resp = await client.get(_SENTIMENT_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"新浪 hs_a 返回非数组: {type(data).__name__}")
    return data


def _bucket_pct(pct: float) -> str:
    """根据涨跌幅分桶"""
    if pct >= 9.9:
        return "limit_up"
    if pct >= 5:
        return "up_5_10"
    if pct >= 1:
        return "up_1_5"
    if pct > 0:
        return "up_0_1"
    if pct > -1:
        return "down_0_1"
    if pct > -5:
        return "down_1_5"
    if pct > -9.9:
        return "down_5_10"
    return "limit_down"


async def fetch_market_sentiment() -> dict[str, Any]:
    """沪深 A 股涨跌家数 + 9 档区间分布 + 成交额(亿元)

    样本量只覆盖首页 ~200 条,反映当日情绪概览。
    """
    rows = await _fetch_hs_a_quotes(page_size=200)

    buckets: dict[str, int] = {
        "limit_up": 0,
        "up_5_10": 0,
        "up_1_5": 0,
        "up_0_1": 0,
        "flat": 0,
        "down_0_1": 0,
        "down_1_5": 0,
        "down_5_10": 0,
        "limit_down": 0,
    }
    up_total = 0
    down_total = 0
    flat_total = 0
    total_amount = 0.0  # 亿元

    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            pct = float(r.get("changepercent", 0) or 0)
            amount_wan = float(r.get("amount", 0) or 0)
        except (TypeError, ValueError):
            continue
        total_amount += amount_wan / 1e8

        if abs(pct) < 0.01:
            buckets["flat"] += 1
            flat_total += 1
        elif pct > 0:
            up_total += 1
            bucket = _bucket_pct(pct)
            buckets[bucket] = buckets.get(bucket, 0) + 1
        else:
            down_total += 1
            bucket = _bucket_pct(pct)
            buckets[bucket] = buckets.get(bucket, 0) + 1

    return {
        "sample_size": len(rows),
        "up_total": up_total,
        "down_total": down_total,
        "flat_total": flat_total,
        "buckets": buckets,
        "amount_yi": round(total_amount, 2),
    }


# ============ 扩展:A 股个股主力净流入榜 ============


async def fetch_main_fund_flow(limit: int = 10) -> list[dict[str, Any]]:
    """A 股个股主力净流入榜(降级方案)

    新浪 Market_Center 不暴露个股净流入接口;本方案按 hs_a 全市场数据,
    估算净额 = 成交额 × sign(涨幅) × (1 + |涨幅%| / 10) ,反映"涨越凶越流入"
    的近似规律。仅供可视化,非真实主力净额。
    """
    rows = await _fetch_hs_a_quotes(page_size=200)

    items: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        symbol = r.get("symbol") or ""
        if not symbol:
            continue
        try:
            change_pct = float(r.get("changepercent", 0) or 0)
            amount_wan = float(r.get("amount", 0) or 0)
        except (TypeError, ValueError):
            continue
        prefix = symbol[:2]
        num = symbol[2:]
        market = {"sh": "SH", "sz": "SZ"}.get(prefix, "SH")
        code = f"{num}.{market}"
        amount_yi = amount_wan / 1e8
        net = amount_yi * (1 if change_pct > 0 else -1) * (1 + abs(change_pct) / 10)
        items.append({
            "code": code,
            "name": r.get("name", ""),
            "current_price": r.get("trade", ""),
            "change_pct": change_pct,
            "netamount_yi": round(net, 2),
        })

    items.sort(key=lambda x: x["netamount_yi"], reverse=True)
    return items[:limit]


__all__ = [
    "INDEX_CODES",
    "get_market_index_service",
    "get_market_overview",
    "fetch_market_sparklines",
    "fetch_market_sentiment",
    "fetch_main_fund_flow",
    "reset_market_overview_service",
]