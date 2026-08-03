"""持仓 API(P2.3 实施,P3.5.1 扩展行情字段,v0.4.0 持仓主数据化)

v0.4.0:positions 表为主数据(手动录入 / 截图导入 / 流水同步),
- GET    /api/positions          列出当前持仓(含今日盈亏)
- POST   /api/positions          手动录入 / 覆盖单只持仓(每股成本价)
- DELETE /api/positions/{code}   删除单只持仓(流水保留)

P3.5.1(今日盈亏):引入 QuoteService(新浪主 + 腾讯备 + 5min 缓存),
返回 current_price / prev_close / today_pnl / floating_pnl。
行情全部失败时这些字段为 null,前端降级为骨架屏/"--"。
"""
from decimal import Decimal

from fastapi import APIRouter, HTTPException

from app.core.db_lock import safe_write
from app.models.schemas import ClearPositionRequest, PositionCreate
from app.repositories.transaction_repo import transaction_repo
from app.services.position_service import (
    delete_position,
    get_all_positions,
    get_position,
    upsert_position,
)
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
    from app.core.stock_code import normalize_code

    codes = [normalize_code(p.stock_code) or p.stock_code for p in positions]
    codes = [c for c in codes if c]
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


@router.post("/positions", status_code=201)
async def create_position(payload: PositionCreate) -> dict:
    """手动录入 / 覆盖单只持仓(v0.4.0)

    覆盖语义:以用户提交的股数/每股成本价为准;已实现盈亏保留流水部分。
    """
    pos = await upsert_position(
        stock_code=payload.stock_code,
        shares=payload.shares,
        cost_price=payload.cost_price,
        stock_name=payload.stock_name,
    )
    return {
        "stock_code": pos.stock_code,
        "stock_name": pos.stock_name,
        "shares": pos.shares,
        "total_cost": str(pos.total_cost.quantize(Decimal("0.01"))),
        "avg_cost": str(pos.avg_cost),
        "realized_pnl": str(pos.realized_pnl.quantize(Decimal("0.01"))),
    }


@router.delete("/positions/{code}", status_code=204)
async def remove_position(code: str) -> None:
    """删除单只持仓(v0.4.0)

    联动语义:持仓是主数据,流水是它的影子事件记录。
    删除持仓 → 同时删除该股票全部流水 + 评分(trade_scores 级联删除),防止 recalc 复活。
    """
    from app.core.stock_code import normalize_code
    from app.repositories.transaction_repo import transaction_repo

    normalized = normalize_code(code) or code
    deleted = await delete_position(normalized)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "POSITION_NOT_FOUND", "message": f"持仓 {normalized} 不存在"},
        )
    await transaction_repo.delete_by_stock(normalized)


@router.post("/positions/{code}/clear", status_code=201)
async def clear_position(code: str, payload: ClearPositionRequest) -> dict:
    """一键清仓(v0.4.1 / P-stop-loss-v2)

    以指定价格(默认当前行情价)卖出当前持仓的全部股数。
    业务逻辑:
    1. 取当前持仓(不存在 → 404)
    2. 创建 sell 流水(覆盖全部 shares + payload.price)
    3. recalc_position 触发 → 持仓归零 → 删除持仓行
    4. 返回生成的 sell 流水记录 + 预估已实现盈亏
    """
    from datetime import date as date_cls
    from decimal import Decimal

    from app.core.stock_code import normalize_code
    from app.services.position_service import capture_delta, recalc_position

    normalized = normalize_code(code) or code
    pos = await get_position(normalized)
    if pos is None or pos.shares <= 0:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "POSITION_NOT_FOUND",
                "message": f"持仓 {normalized} 不存在或已清仓",
            },
        )

    shares = pos.shares
    price = payload.price
    realized = (price - pos.avg_cost) * shares  # 预估已实现盈亏

    # 变更前捕获导入基准(否则 recalc 会失准)
    delta = await capture_delta(normalized)

    async def _do_create():
        return await transaction_repo.create(
            stock_code=normalized,
            stock_name=pos.stock_name,
            action="sell",
            shares=shares,
            price=f"{price:.3f}",
            trade_date=date_cls.today(),
            note=payload.note or "一键清仓",
        )

    tx = await safe_write(_do_create)
    await recalc_position(normalized, delta)

    return {
        "stock_code": normalized,
        "shares": shares,
        "price": f"{price:.3f}",
        "realized_pnl": str(realized.quantize(Decimal("0.01"))),
        "trade_id": tx.id,
        "trade_date": tx.trade_date.isoformat(),
    }
