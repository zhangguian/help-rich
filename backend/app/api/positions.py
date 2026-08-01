"""持仓 API(P2.3 实施)

MVP 阶段暂不调用行情接口(akshare / 东财),只返回:
  - 持仓股数 / 加权成本 / 总成本 / 已实现盈亏

current_price / today_pnl 等字段留 v0.2(需 ak-share / 东财 装包,P3.5 实施)
"""
from decimal import Decimal

from fastapi import APIRouter

from app.services.position_service import get_all_positions

router = APIRouter(tags=["positions"])


@router.get("/positions")
async def list_positions() -> dict:
    """列出当前持仓

    v2.1 §4.1
    MVP 字段:stock_code / stock_name / shares / avg_cost / total_cost / realized_pnl
    v0.2 加:current_price / prev_close / today_pnl / floating_pnl(需行情接口)
    """
    positions = await get_all_positions()
    items = [
        {
            "stock_code": p.stock_code,
            "stock_name": p.stock_name,
            "shares": p.shares,
            "avg_cost": str(p.avg_cost),
            "total_cost": str(p.total_cost.quantize(Decimal("0.01"))),
            "realized_pnl": str(p.realized_pnl.quantize(Decimal("0.01"))),
        }
        for p in positions
    ]
    return {"items": items}