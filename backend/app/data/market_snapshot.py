"""沪深京 A 股全市场快照(全量翻页,无采样偏差)

**为什么存在**
旧实现用新浪 `Market_Center.getHQNodeData` 的**首页**当全市场统计 ——
但该接口单页硬上限 100 条,且按 `sort=changepercent` 排序时取回的必然是
涨幅榜前列。用它统计"涨跌家数 / 涨停家数"是**采样偏差**:
2026-10-20 实测旧实现输出 `up=100 / down=0 / limit_up=93`,而真实全市场是
`up=3777 / down=1667 / limit_up=59`。首页天然全是上涨股。

本模块按 `sort=symbol`(代码升序)稳定翻页,覆盖全部沪深京 A 股,
实测 5574 只 / 56 页 / 约 3.4 秒(symbol 去重数 == 拉取数,无重无漏)。

**涨跌停按板块判定**(不是所有股票都 ±10%):
- 创业板(300/301)、科创板(688/689):±20%(含 ST)
- 北交所(8xx / 4xx / 920):±30%
- 主板 ST / *ST:±5%
- 其他主板:±10%

**为什么不用东方财富**:`push2.eastmoney.com` 的 clist 接口能一次给 `total=5924`
且更省请求,但实测在本机网络下 **Python 栈(httpx / urllib)一律被服务端断开**
(`RemoteDisconnected: Remote end closed connection without response`),
而 Windows/.NET 客户端可通 —— 属 TLS 客户端指纹差异,故不采用。

**降级**:网络失败抛 `MarketSnapshotUnavailable`,由调用方决定兜底策略。
"""
import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SINA_LIST_URL = (
    "https://vip.stock.finance.sina.com.cn/"
    "quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
)

_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn",
}

# 单页硬上限 100 条(pz 传任何值都只返回 100)
_PAGE_SIZE = 100
# 全市场约 5600 只 → 56 页;留余量
_MAX_PAGES = 80
_PAGE_TIMEOUT = 15.0
# 并发页数(实测 10 稳定,过高会被限流)
_CONCURRENCY = 10

# 全量快照缓存(拉 56 页约 3.4s,必须缓存)
_CACHE: dict[str, tuple[list[dict[str, Any]], float]] = {}
_CACHE_TTL = 60.0  # 秒


class MarketSnapshotUnavailable(Exception):
    """全市场快照数据源不可用(网络/接口变更/限流)"""


def _to_internal_code(symbol: str) -> str:
    """新浪 symbol(sh600519) → 内部代码(600519.SH)"""
    s = (symbol or "").lower()
    if len(s) > 2 and s[:2] in ("sh", "sz", "bj"):
        return f"{s[2:]}.{s[:2].upper()}"
    return s.upper()


def limit_pct(code: str, name: str) -> float:
    """该股当日涨跌停幅度(%)—— 按板块区分

    - 创业板(300/301)、科创板(688/689):±20%(含 ST)
    - 北交所(8xx / 4xx / 920):±30%
    - 主板 ST / *ST:±5%
    - 其他主板:±10%
    """
    code = str(code)
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    if code.startswith(("8", "4", "92")):
        return 30.0
    if "ST" in str(name).upper():
        return 5.0
    return 10.0


def bucket_by_limit(pct: float, limit: float) -> str:
    """按板块涨停幅度分桶(与前端 8 档桶名对齐)

    limit_up / limit_down 用板块阈值判定(容忍 0.1 个百分点浮点误差);
    中间档位沿用固定 5% / 1% 切点。
    """
    if pct >= limit - 0.1:
        return "limit_up"
    if pct >= 5:
        return "up_5_10"
    if pct >= 1:
        return "up_1_5"
    if pct > 0:
        return "up_0_1"
    if pct <= -(limit - 0.1):
        return "limit_down"
    if pct <= -5:
        return "down_5_10"
    if pct <= -1:
        return "down_1_5"
    if pct < 0:
        return "down_0_1"
    return "flat"


async def _fetch_page(client: httpx.AsyncClient, page: int) -> list[dict[str, Any]]:
    """拉单页(代码升序,保证翻页无重叠)"""
    params = {
        "node": "hs_a",
        "sort": "symbol",   # 按代码排序 → 翻页稳定且不重叠
        "asc": 0,
        "num": _PAGE_SIZE,
        "page": page,
    }
    resp = await client.get(SINA_LIST_URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"新浪 hs_a 返回非数组: {type(data).__name__}")
    return data


async def fetch_market_snapshot(
    max_pages: int = _MAX_PAGES,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    """沪深京 A 股全市场快照(全量)

    返回归一化后的行:
        {code, name, price, change_pct, prev_close, amount_yi, limit_pct, volume}

    `code` 带市场后缀(600519.SH / 000001.SZ / 920096.BJ)。

    网络失败抛 MarketSnapshotUnavailable。
    """
    if use_cache:
        cached = _CACHE.get("snapshot")
        if cached and (time.monotonic() - cached[1]) < _CACHE_TTL:
            return cached[0]

    raw_rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        headers=_SINA_HEADERS, timeout=_PAGE_TIMEOUT, trust_env=False
    ) as client:
        # 先取第 1 页:既验证连通性,也用来判断总页数
        try:
            first = await _fetch_page(client, 1)
        except (httpx.HTTPError, ValueError) as e:
            raise MarketSnapshotUnavailable(f"新浪全市场快照第 1 页失败: {e}") from e
        if not first:
            raise MarketSnapshotUnavailable("新浪全市场快照第 1 页返回空")
        raw_rows.extend(first)

        # 翻页:继续拉到某页返回空为止(不硬编码总页数,适应市场扩容)
        sem = asyncio.Semaphore(_CONCURRENCY)
        empty_streak = 0
        page = 2
        while page <= max_pages:
            batch = list(range(page, min(page + _CONCURRENCY, max_pages + 1)))
            page = batch[-1] + 1

            async def _one(p: int) -> list[dict[str, Any]]:
                async with sem:
                    try:
                        return await _fetch_page(client, p)
                    except (httpx.HTTPError, ValueError) as e:
                        logger.warning("新浪全市场快照第 %s 页失败: %s", p, e)
                        return []

            results = await asyncio.gather(*(_one(p) for p in batch))
            got = 0
            for rows in results:
                raw_rows.extend(rows)
                got += len(rows)
            if got == 0:
                empty_streak += 1
                # 连续两批都空 → 已到末尾
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0

    # 去重(按 symbol,防御分页边界重复)
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for r in raw_rows:
        if not isinstance(r, dict):
            continue
        symbol = r.get("symbol") or ""
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        code = str(r.get("code") or symbol[2:])
        name = str(r.get("name") or "")
        try:
            price = float(r.get("trade") or 0)
            pct = float(r.get("changepercent") or 0)
            prev_close = float(r.get("settlement") or 0)
            amount = float(r.get("amount") or 0)
            volume = int(r.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            # 停牌 / 无效报价
            continue
        normalized.append({
            "code": _to_internal_code(symbol),
            "name": name,
            "price": price,
            "change_pct": pct,
            "prev_close": prev_close,
            "amount_yi": round(amount / 1e8, 4),
            "volume": volume,
            "limit_pct": limit_pct(code, name),
        })

    if not normalized:
        raise MarketSnapshotUnavailable("新浪全市场快照归一化后为空")

    logger.info(
        "新浪全市场快照: 拉取 %s 条 → 去重有效 %s 只", len(raw_rows), len(normalized)
    )
    _CACHE["snapshot"] = (normalized, time.monotonic())
    return normalized


def reset_market_snapshot_cache() -> None:
    """测试辅助:清空全量快照缓存"""
    _CACHE.clear()


__all__ = [
    "MarketSnapshotUnavailable",
    "fetch_market_snapshot",
    "limit_pct",
    "bucket_by_limit",
    "reset_market_snapshot_cache",
]
