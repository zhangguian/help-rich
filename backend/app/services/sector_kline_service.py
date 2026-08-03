"""M2.2 板块K线合成服务(等权,30min 内存缓存)

成分来源:行业归属离线表(app/data/industry_map.json, baostock 生成)反向索引。
合成口径:同交易日成分股收盘价等权平均(open/high/low 同法等权, volume 求和)。
缓存:进程内 30 分钟(纯内存,重启失效,决策见 v0.5-5)。
"""
import asyncio
import logging
import time
from collections import defaultdict
from statistics import mean

from app.services.kline_service import KLineSourceUnavailable, fetch_klines

logger = logging.getLogger(__name__)

#: 单行业最多拉取成分股数(首次合成性能控制)
MAX_COMPONENTS = 30
#: 缓存有效期(秒)
_CACHE_TTL = 30 * 60

_cache: dict[str, tuple[float, list[dict]]] = {}


def load_industry_components() -> dict[str, list[str]] | None:
    """读离线表 → {industry: [codes]};表缺失/空返回 None"""
    try:
        from app.services.industry_service import _load_industry_map

        m = _load_industry_map()
    except Exception as e:  # noqa: BLE001
        logger.warning("行业表加载失败: %s", e)
        return None
    out: dict[str, list[str]] = defaultdict(list)
    for code, name in m.items():
        if name:
            out[name].append(code)
    return {k: sorted(v) for k, v in out.items()} if out else None


def pick_components(industry: str, components: dict[str, list[str]] | None) -> list[str]:
    """成分选择(纯函数,可单测):全量 → 取前 MAX_COMPONENTS

    components: 行业名 → 代码列表(可能 None=表缺失)
    """
    if not components:
        return []
    codes = components.get(industry) or []
    return codes[:MAX_COMPONENTS]


def _align_dates(rows_by_code: list[list[dict]]) -> list[dict]:
    """等权合成(纯函数,可单测)

    rows_by_code: 每个成分的日K列表(升序)。取日期交集,均值 close。
    """
    date_map: defaultdict[str, list[float]] = defaultdict(list)
    for rows in rows_by_code:
        for r in rows:
            date_map[r["date"]].append(float(r["close"]))
    dates = sorted(date_map.keys())
    # 只保留每个成分都有的日期(交集)
    n = len(rows_by_code)
    out = [
        {"date": d, "close": round(mean(date_map[d]), 4)}
        for d in dates
        if len(date_map[d]) == n
    ]
    return out


async def get_sector_kline(
    industry: str, period: str = "daily", count: int = 60,
    component_loader=None, fetch_one=None,
) -> dict:
    """板块K线(按行业合成)

    component_loader: () -> {industry: [codes]} | None(测试可注入,默认读表)
    fetch_one: async (code) -> [klines](测试可注入,默认 fetch_klines)
    """
    cache_key = f"{industry}::{period}::{count}"
    now = time.time()

    if cache_key in _cache:
        ts, cached = _cache[cache_key]
        if now - ts < _CACHE_TTL:
            return cached

    loader = component_loader or load_industry_components
    comps = loader()
    codes = pick_components(industry, comps)
    if not codes:
        raise KLineSourceUnavailable(f"行业 {industry} 无成分股")

    fetcher = fetch_one or fetch_klines
    results = await asyncio.gather(
        *[fetcher(c, period=period, count=count) for c in codes],
        return_exceptions=True,
    )
    # 单个成分失败跳过(不影响整体);全部失败抛错
    rows_list = []
    for r in results:
        if isinstance(r, BaseException):
            logger.warning("板块K线成分拉取失败(跳过): %s", r)
        elif r:
            rows_list.append(r)
    if not rows_list:
        raise KLineSourceUnavailable(f"行业 {industry} 成分股全部拉取失败")

    items = _align_dates(rows_list)
    if not items:
        raise KLineSourceUnavailable(f"行业 {industry} 合成失败(日期交集为空)")

    result = {
        "industry": industry,
        "period": period,
        "count": len(items),
        "components": len(rows_list),
        "items": items,
    }
    _cache[cache_key] = (now, result)
    logger.info("板块K线合成: %s %s (%d 根/%d 成分)", industry, period, len(items), len(rows_list))
    return result


__all__ = ["get_sector_kline", "load_industry_components", "pick_components", "_align_dates"]