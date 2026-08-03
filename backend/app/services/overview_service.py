"""M2.3 三线叠加(个股 + 大盘指数 + 行业)服务

一次返回三条归一化日K,供前端 overlay 对比「今天涨的是大盘还是我的行业」。
- 个股:新浪直连(DB 缓存)
- 大盘:上证指数 000001.SH(新浪直连,不落 KlineCache)
- 行业:所属行业成分等权合成(见 sector_kline_service)
归一化:以三条线**首个共同交易日**收盘为基准(=100),后续相对基准。
时间对齐:取交易日交集(不做前向填充),保证对比公平。
行业线不可用 → sector=None(空态),不影响前两条。
"""
import asyncio
import logging
from datetime import date
from typing import Any

from app.services.industry_service import resolve_industry
from app.services.kline_service import _fetch_sina_kline, fetch_klines
from app.services.sector_kline_service import get_sector_kline

logger = logging.getLogger(__name__)

#: 大盘指数(上证指数)
INDEX_CODE = "000001.SH"
#: 各线最大根数
DEFAULT_COUNT = 60


def align_and_normalize(lines: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """归一化对齐(纯函数,可单测)

    lines: 每组 [{date, close}]。以所有**非空**组日期交集为轴;基准 = 交集
    首日的每股 close → 100。空组保持 [] 不参与交集,仍返回与输入同序。
    若所有组交集为空 → 全组返回 []。
    """
    maps = [
        {str(r["date"])[:10]: float(r["close"]) for r in line} if line else {}
        for line in lines
    ]
    non_empty = [m for m in maps if m]
    if not non_empty:
        return [[] for _ in lines]
    common = sorted(set(non_empty[0]).intersection(*[m for m in non_empty[1:]]))
    if not common:
        return [[] for _ in lines]
    base = common[0]

    out: list[list[dict[str, Any]]] = []
    for m in maps:
        if not m:
            out.append([])
            continue
        b = m[base]
        out.append([
            {"date": d, "close": round(m[d] / b * 100, 2)}
            for d in common
        ])
    return out


def _to_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """K线行 → {date(yyyy-mm-dd), close}"""
    out = []
    for r in rows:
        raw = str(r.get("date") or "")[:10]
        if not raw:
            continue
        try:
            date.fromisoformat(raw)
        except ValueError:
            continue
        out.append({"date": raw, "close": float(r["close"])})
    return out


async def get_overview(stock_code: str, count: int = DEFAULT_COUNT) -> dict:
    """三线对比数据;行业不可用 → sector=[] + sector_unavailable=True"""
    ind = await resolve_industry(stock_code)
    ind_name = ind.get("industry")

    async def fetch_stock():
        try:
            return await fetch_klines(stock_code, period="daily", count=count)
        except Exception as e:  # noqa: BLE001
            logger.warning("三线-个股拉取失败(%s): %s", stock_code, e)
            return []

    async def fetch_index():
        try:
            return await _fetch_sina_kline(INDEX_CODE, period="daily", count=count)
        except Exception as e:  # noqa: BLE001
            logger.warning("三线-指数拉取失败: %s", e)
            return []

    async def fetch_sector():
        if not ind_name:
            return []
        try:
            d = await get_sector_kline(ind_name, period="daily", count=count)
            return d["items"]
        except Exception as e:  # noqa: BLE001
            logger.warning("三线-行业拉取失败(%s): %s", ind_name, e)
            return []

    stock, index, sector = await asyncio.gather(
        fetch_stock(), fetch_index(), fetch_sector()
    )

    [n_stock, n_index, n_sector] = align_and_normalize([
        _to_points(stock),
        _to_points(index),
        _to_points(sector),
    ])

    return {
        "stock_code": stock_code,
        "industry": ind_name,
        "count": len(n_stock),
        "lines": {
            "stock": n_stock,
            "index": n_index,
            "sector": n_sector,
        },
        "sector_unavailable": (not n_sector) and bool(ind_name),
    }


__all__ = ["get_overview", "align_and_normalize", "INDEX_CODE"]