"""持仓 API(P2.3 实施,P3.5.1 扩展行情字段)

P3.5.1(今日盈亏):引入 QuoteService(新浪主 + 腾讯备 + 5min 缓存),
返回 current_price / prev_close / today_pnl / floating_pnl。
行情全部失败时这些字段为 null,前端降级为骨架屏/"--"。
"""
from decimal import Decimal

from fastapi import APIRouter

from app.services.position_service import get_all_positions
from app.services.quote_service import QuoteService

router = APIRouter(tags=["positions"])

_quote_service: QuoteService | None = None


def get_quote_service() -> QuoteService:
    global _quote_service
    if _quote_service is None:
        _quote_service = QuoteService()
    return _quote_service


@router.get("/positions")
async def list_positions() -> dict:
    """列出当前持仓(含今日盈亏)

    P3.5.1 新增字段:
      current_price: 现价(行情)
      prev_close:    昨收
      today_pnl:     今日盈亏 = (现价 - 昨收) × 持仓股数
      floating_pnl:  浮动盈亏 = (现价 - 成本) × 持仓股数
    行情不可用时为 null。
    """
    positions = await get_all_positions()
    codes = [p.stock_code for p in positions]
    quotes: dict[str, object] = {}
    if codes:
        quotes = {q.code: q for q in await get_quote_service().get_quotes(codes)}

    items = []
    for p in positions:
        item = {
            "stock_code": p.stock_code,
            "stock_name": p.stock_name,
            "shares": p.shares,
            "avg_cost": str(p.avg_cost),
            "total_cost": str(p.total_cost.quantize(Decimal("0.01"))),
            "realized_pnl": str(p.realized_pnl.quantize(Decimal("0.01"))),
        }
        q = quotes.get(p.stock_code)
        if q is not None:
            price = q.current_price
            prev_close = q.prev_close
            item["current_price"] = str(price)
            item["prev_close"] = str(prev_close)
            item["today_pnl"] = str(((price - prev_close) * p.shares).quantize(Decimal("0.01")))
            item["floating_pnl"] = str(((price - p.avg_cost) * p.shares).quantize(Decimal("0.01")))
        else:
            item["current_price"] = None
            item["prev_close"] = None
            item["today_pnl"] = None
            item["floating_pnl"] = None
        items.append(item)
    return {"items": items}
