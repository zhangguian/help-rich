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
        # 新浪该接口的排序字段是 changepercent(changeratio 已失效,见 ADR-0011);
        # 兼容两种字段名,缺失则跳过该行
        raw_pct = r.get("changepercent", r.get("changeratio"))
        try:
            change_pct = float(raw_pct)
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

# 全市场快照的 60s 缓存由 `app.data.market_snapshot` 内部维护
# (拉 56 页约 3~6s,必须缓存);本模块不再另设缓存层,避免两处 TTL 不一致。


async def _fetch_hs_a_quotes(page_size: int = 200) -> list[dict[str, Any]]:
    """沪深 A 股快照(**仅首页采样,不可用于全市场统计**)

    ⚠️ 警告:该接口单页硬上限 100 条,且按 `sort=changepercent` 排序时取回的
    必然是涨幅榜前列 —— 用它统计"涨跌家数/涨停家数"是**采样偏差**,
    会得出 "93 家涨停、0 家下跌" 这类失真结论(实测于 2026-10-20)。

    保留本函数仅作 `fetch_main_fund_flow` 的**降级兜底**(全量快照不可用时);
    全市场统计请用 `app.data.market_snapshot.fetch_market_snapshot`
    (新浪按 `sort=symbol` 全量翻页,56 页覆盖全部沪深京 A 股)。
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
    """根据涨跌幅分桶(固定 ±10% 口径,**不区分板块**)

    ⚠️ 仅适用于主板。创业板/科创板 ±20%、北交所 ±30%,用本函数会把它们的
    涨停股误判进 up_5_10 桶。板块感知请用
    `app.data.eastmoney.bucket_by_limit(pct, limit_pct)`。
    """
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


def _empty_buckets() -> dict[str, int]:
    return {
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


async def fetch_market_sentiment() -> dict[str, Any]:
    """沪深 A 股涨跌家数 + 9 档区间分布 + 涨停/跌停家数 + 成交额(亿元)

    **数据源:新浪全 A 股快照(全量翻页,无采样偏差)**
    旧实现取新浪"涨幅榜首页 200 条"当全市场统计,会得出严重失真的结论
    (实测 2026-10-20:旧实现 up=100/down=0/limit_up=93,真实为
    up=3777/down=1667/limit_up=59)。

    - 全市场口径:sample_size ≈ 5500+ 只沪深京 A 股
    - 涨跌停按**板块**判定(主板 ±10% / 创业板科创板 ±20% / 北交所 ±30% / ST ±5%)
    - 数据源失败 → 抛 MarketSnapshotUnavailable,由 API 返回 503(不返回假数据)
    """
    from app.data.market_snapshot import (
        MarketSnapshotUnavailable,
        bucket_by_limit,
        fetch_market_snapshot,
    )

    try:
        rows = await fetch_market_snapshot()
    except MarketSnapshotUnavailable as e:
        logger.warning("全市场快照失败: %s", e)
        raise

    buckets = _empty_buckets()
    up_total = down_total = flat_total = 0
    total_amount = 0.0

    for r in rows:
        pct = r["change_pct"]
        total_amount += r["amount_yi"]
        if abs(pct) < 0.01:
            buckets["flat"] += 1
            flat_total += 1
            continue
        if pct > 0:
            up_total += 1
        else:
            down_total += 1
        bucket = bucket_by_limit(pct, r["limit_pct"])
        buckets[bucket] = buckets.get(bucket, 0) + 1

    return {
        "sample_size": len(rows),
        "up_total": up_total,
        "down_total": down_total,
        "flat_total": flat_total,
        "buckets": buckets,
        "amount_yi": round(total_amount, 2),
        # 涨停/跌停家数单列(小白第一眼)
        "limit_up": buckets["limit_up"],
        "limit_down": buckets["limit_down"],
        # 口径标记:full=全市场统计,partial=首页采样(前端据此提示,不再假装全市场)
        "source": "sina_full",
        "partial": False,
    }


# ============ M2.5 两市成交额 N 日趋势 ============


async def fetch_amount_trend(days: int = 5) -> dict[str, Any]:
    """两市量能 N 日趋势(上证指数日K volume,单位:亿手→成交额约估)

    新浪指数日K 无 amount(amount=0),用 volume(成交量,单位股)趋势近似
    资金活跃度。"成交额"仅供参考,前端以「两市量能」命名,不造假成金额。
    """
    try:
        rows = await _fetch_sina_kline("000001.SH", period="daily", count=days)
    except Exception as e:  # noqa: BLE001
        logger.warning("两市量能趋势拉取失败: %s", e)
        return {"days": 0, "items": []}

    items = []
    for r in rows:
        raw = str(r.get("date") or "")[:10]
        if not raw:
            continue
        try:
            vol_yi = float(r.get("volume") or 0) / 1e8  # 手 → 亿手
        except (TypeError, ValueError):
            continue
        items.append({"date": raw, "volume_yi": round(vol_yi, 2)})
    return {"days": len(items), "items": items}


# ============ 扩展:A 股个股主力净流入榜 ============


async def fetch_main_fund_flow(limit: int = 10) -> list[dict[str, Any]]:
    """A 股个股主力净流入榜(降级估算)

    新浪 Market_Center 不暴露个股净流入接口;本方案按全市场快照,
    估算净额 = 成交额 × sign(涨幅) × (1 + |涨幅%| / 10) ,反映"涨越凶越流入"
    的近似规律。仅供可视化,非真实主力净额。

    ⚠️ 旧实现只取新浪首页 200 条(按涨幅降序 → 全是涨幅榜前列),
    榜单天然偏科;现改用全量快照,与"主力净流入"语义更贴近。
    """
    from app.data.market_snapshot import MarketSnapshotUnavailable, fetch_market_snapshot

    try:
        rows = await fetch_market_snapshot()
    except MarketSnapshotUnavailable as e:
        logger.warning("全市场快照失败,主力净流入降级新浪采样: %s", e)
        rows = await _fetch_hs_a_quotes(page_size=200)
        items = []
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
            amount_yi = amount_wan / 1e8
            net = amount_yi * (1 if change_pct > 0 else -1) * (1 + abs(change_pct) / 10)
            items.append({
                "code": f"{num}.{market}",
                "name": r.get("name", ""),
                "current_price": r.get("trade", ""),
                "change_pct": change_pct,
                "netamount_yi": round(net, 2),
            })
    else:
        items = [
            {
                "code": r["code"],
                "name": r["name"],
                "current_price": f"{r['price']:.3f}",
                "change_pct": r["change_pct"],
                "netamount_yi": round(
                    r["amount_yi"]
                    * (1 if r["change_pct"] > 0 else -1)
                    * (1 + abs(r["change_pct"]) / 10),
                    2,
                ),
            }
            for r in rows
        ]

    items.sort(key=lambda x: x["netamount_yi"], reverse=True)
    return items[:limit]


def reset_sentiment_cache() -> None:
    """测试辅助:清空情绪统计相关缓存"""
    from app.data.market_snapshot import reset_market_snapshot_cache

    reset_market_snapshot_cache()


__all__ = [
    "INDEX_CODES",
    "get_market_index_service",
    "get_market_overview",
    "fetch_market_sparklines",
    "fetch_market_sentiment",
    "fetch_main_fund_flow",
    "fetch_amount_trend",
    "reset_market_overview_service",
    "reset_sentiment_cache",
]