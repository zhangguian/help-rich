"""板块资金流服务(guide §7 新浪)"""
import logging
from datetime import datetime
from typing import Any

from app.data.sina import fetch_sector_fund_flow_rank

logger = logging.getLogger(__name__)

FENLEI_MAP = {
    0: "全部",
    1: "行业",
    2: "概念",
    3: "地域",
}

# 板块资金流排行不入库(高频更新,只读排行;MVP 仅查询)


async def get_sector_fund_flow(
    fenlei: int = 0, num: int = 20, sort: str = "netamount"
) -> list[dict[str, Any]]:
    """拉板块资金流排行(guide §7 新浪)"""
    raw = await fetch_sector_fund_flow_rank(fenlei=fenlei, num=num, sort=sort)
    out: list[dict[str, Any]] = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        out.append({
            "category": r.get("category", ""),
            "name": r.get("name", ""),
            "avg_price": float(r.get("avg_price", 0) or 0),
            "change_pct": float(r.get("avg_changeratio", 0) or 0),
            "turnover_yi": float(r.get("turnover", 0) or 0),
            "inamount_yi": float(r.get("inamount", 0) or 0),
            "outamount_yi": float(r.get("outamount", 0) or 0),
            "netamount_yi": float(r.get("netamount", 0) or 0),
            "ratioamount": float(r.get("ratioamount", 0) or 0),
            "top_stock": {
                "code": r.get("ts_symbol", ""),
                "name": r.get("ts_name", ""),
                "price": float(r.get("ts_trade", 0) or 0),
                "change_pct": float(r.get("ts_changeratio", 0) or 0),
                "ratioamount": float(r.get("ts_ratioamount", 0) or 0),
            } if r.get("ts_symbol") else None,
        })
    return out


__all__ = ["get_sector_fund_flow", "FENLEI_MAP"]