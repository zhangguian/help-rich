"""申万行业成分股映射(新浪 `Market_Center` · node=`hangye_*`)

**为什么必须有这个模块**

选股 4 因子里的「板块主力净流入」与「板块强度」都是**板块级**指标:
要知道「这只票属于哪个板块」,才能把它和板块资金榜对上。

⚠️ **本项目里存在两套互不相通的行业分类** —— 这是个真实的坑:

| 来源 | 分类体系 | 例子 |
|---|---|---|
| `app/data/industry_map.json`(baostock 离线表) | **证监会行业分类** | `J66货币金融服务` `K70房地产业` |
| 新浪板块资金榜(`fenlei=2`) | **申万行业** | `hangye_ZC39` 计算机、通信和其他 |

两者**名称永不相交**。用离线表的行业名去查资金榜 → 永远查不到 →
「主力净流入」与「板块强度」两个因子**恒为 0 分**(155 分里丢掉 85 分)。

本模块提供与资金榜**同源**的映射:申万行业 node → 该行业成分股。

**为什么用申万行业(fenlei=2)而不是概念板块(fenlei=1)**
- 申万一级行业里**一只票只属于一个行业** → 映射是 1:1,语义干净
- 概念板块里一只票属于十几个概念 → 要做「取最强主线」的额外裁决,成本与歧义都更高
- 行业板块的成分股总量 ≈ 全市场,一次拉完可**全天复用**

**降级**:网络失败 → 抛 `SectorMembersUnavailable`,由调用方决定兜底
(上层会让两个板块因子记 0 分并如实披露,不编数)。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from app.core.stock_code import normalize_code

logger = logging.getLogger(__name__)

SINA_NODE_URL = (
    "https://vip.stock.finance.sina.com.cn/"
    "quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
)

_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn",
}

_PAGE_SIZE = 100
_MAX_PAGES_PER_NODE = 60      # 单个行业最多 6000 只(申万一级远小于此)
_CONCURRENCY = 10             # 并发页数(与 market_snapshot 同档)
_NODE_TIMEOUT = 15.0
# 单个行业的成分股缓存有效期(秒)—— 行业归属一天内不会变
_CACHE_TTL = 30 * 60

# node → (成分股代码列表, 缓存时间戳)
_NODE_CACHE: dict[str, tuple[list[str], float]] = {}


class SectorMembersUnavailable(Exception):
    """申万行业成分股映射不可用(网络/接口变更/限流)"""


def _to_internal(symbol: str) -> str | None:
    """新浪 symbol(sh600519) → 内部代码(600519.SH)"""
    if not symbol:
        return None
    return normalize_code(symbol)


async def _fetch_node_page(
    client: httpx.AsyncClient, node: str, page: int
) -> list[dict[str, Any]]:
    params = {
        "node": node,
        "sort": "symbol",   # 按代码升序 → 翻页稳定且不重叠
        "asc": 0,
        "num": _PAGE_SIZE,
        "page": page,
    }
    resp = await client.get(SINA_NODE_URL, params=params, headers=_SINA_HEADERS)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"新浪行业成分返回非数组: {type(data).__name__}")
    return data


async def _fetch_node(client: httpx.AsyncClient, node: str) -> list[str]:
    """拉某个行业的全部成分股代码(升序)"""
    codes: list[str] = []
    seen: set[str] = set()
    for page in range(1, _MAX_PAGES_PER_NODE + 1):
        try:
            rows = await _fetch_node_page(client, node, page)
        except (httpx.HTTPError, ValueError) as e:
            if not codes:
                raise SectorMembersUnavailable(
                    f"新浪申万行业成分拉取失败({node} 第 {page} 页): {e}"
                ) from e
            logger.warning("新浪申万行业成分部分失败(%s 第 %s 页): %s", node, page, e)
            break
        if not rows:
            break
        for r in rows:
            if not isinstance(r, dict):
                continue
            code = _to_internal(str(r.get("symbol") or ""))
            if not code or code in seen:
                continue
            seen.add(code)
            codes.append(code)
    return codes


async def fetch_sector_members(nodes: list[str]) -> dict[str, str]:
    """取若干申万行业的成分股 → `{股票代码: 行业 node}`

    一只票只属于一个申万一级行业 → 映射是 1:1。
    重复出现(理论上不会)时**先到先得**,不覆盖。

    网络整体失败 → 抛 `SectorMembersUnavailable`(上层降级为「板块因子记 0 分」)。
    """
    targets = [n for n in dict.fromkeys(nodes or []) if n]
    if not targets:
        return {}

    # 命中缓存的直接取,未命中的才去拉
    todo: list[str] = []
    cached: dict[str, list[str]] = {}
    now = time.monotonic()
    for node in targets:
        hit = _NODE_CACHE.get(node)
        if hit and (now - hit[1]) < _CACHE_TTL:
            cached[node] = hit[0]
        else:
            todo.append(node)

    if todo:
        async with httpx.AsyncClient(trust_env=False, timeout=_NODE_TIMEOUT) as client:
            sem = asyncio.Semaphore(_CONCURRENCY)

            async def _one(node: str) -> tuple[str, list[str]]:
                async with sem:
                    return node, await _fetch_node(client, node)

            results = await asyncio.gather(*[_one(n) for n in todo], return_exceptions=True)
            first_error: BaseException | None = None
            for res in results:
                if isinstance(res, BaseException):
                    if first_error is None:
                        first_error = res
                    continue
                node, codes = res
                cached[node] = codes
                _NODE_CACHE[node] = (codes, time.monotonic())
            if first_error is not None and not cached:
                raise SectorMembersUnavailable(str(first_error)) from first_error
            if first_error is not None:
                logger.warning("部分申万行业成分拉取失败: %s", first_error)

    out: dict[str, str] = {}
    for node in targets:
        for code in cached.get(node) or []:
            out.setdefault(code, node)
    return out


def reset_sector_members_cache() -> None:
    """测试辅助:清空行业成分缓存"""
    _NODE_CACHE.clear()


__all__ = [
    "SectorMembersUnavailable",
    "fetch_sector_members",
    "reset_sector_members_cache",
]
