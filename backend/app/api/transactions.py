"""交易流水 + 自选股 API(P2.1 / P2.2 实施)"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.core.db_lock import safe_write
from app.models.schemas import (
    ApiError,
    TransactionCreate,
    TransactionListOut,
    TransactionOut,
    TransactionUpdate,
    WatchlistAdd,
    WatchlistListOut,
    WatchlistOut,
)
from app.repositories.transaction_repo import transaction_repo
from app.repositories.watchlist_repo import watchlist_repo

router = APIRouter(tags=["transactions"])

# ============================================================
# Transactions
# ============================================================

@router.get("/transactions", response_model=TransactionListOut)
async def list_transactions(
    stock_code: Optional[str] = Query(default=None),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> TransactionListOut:
    """列出流水(支持分页 / 筛选)

    v2.1 §3.1
    stock_code: 接受 600519 / 600519.SH,统一转规范格式
    """
    if stock_code:
        from app.core.stock_code import normalize_code

        stock_code = normalize_code(stock_code) or stock_code
    items, total = await transaction_repo.list_all(
        stock_code=stock_code, limit=limit, offset=offset
    )
    # 关联 score
    from app.repositories.trade_score_repo import trade_score_repo

    out_items = []
    for tx in items:
        score = await trade_score_repo.get_by_trade_id(tx.id)
        out_items.append(
            TransactionOut.from_orm_with_score(tx, score.score if score else None)
        )
    return TransactionListOut(items=out_items, total=total)


@router.post(
    "/transactions",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_transaction(
    payload: TransactionCreate,
    background_tasks: BackgroundTasks,
) -> TransactionOut:
    """录入一笔交易(P2.2)

    v2.1 §3.2
    P4.4:录入后异步触发诊断(评分 + AI 评语,SSE 推送)
    """
    # 校验:卖出不能超过持仓(P2.3 加的实时校验)
    if payload.action == "sell":
        from app.services.position_service import get_position

        existing = await get_position(payload.stock_code)
        current_shares = existing.shares if existing else 0
        if payload.shares > current_shares:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INSUFFICIENT_SHARES",
                    "message": f"这只票只剩 {current_shares} 股了,卖不出 {payload.shares} 股",
                    "detail": {"have": current_shares, "want": payload.shares},
                },
            )

    price_str = format(payload.price, ".3f")  # Decimal → "10.500"

    async def _do_create():
        return await transaction_repo.create(
            stock_code=payload.stock_code,
            action=payload.action,
            shares=payload.shares,
            price=price_str,
            trade_date=payload.trade_date,
            stock_name=payload.stock_name,
            note=payload.note,
        )

    tx = await safe_write(_do_create)

    # P4.4:异步触发诊断(评分 + AI 评语,SSE 推送,不阻塞录入响应)
    from app.services.diagnose_service import diagnose_service

    background_tasks.add_task(diagnose_service.score_and_notify, tx.id)

    return TransactionOut.from_orm_with_score(tx, score=None)


@router.patch("/transactions/{tx_id}", response_model=TransactionOut)
async def update_transaction(tx_id: int, payload: TransactionUpdate) -> TransactionOut:
    """修改一笔交易(只能改 note / shares / price)"""
    updates = payload.model_dump(exclude_none=True)
    if "price" in updates:
        updates["price"] = format(updates["price"], ".3f")

    async def _do_update():
        return await transaction_repo.update(tx_id, **updates)

    tx = await safe_write(_do_update)
    if tx is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TX_NOT_FOUND", "message": f"交易 #{tx_id} 不存在"},
        )

    from app.repositories.trade_score_repo import trade_score_repo
    score = await trade_score_repo.get_by_trade_id(tx.id)
    return TransactionOut.from_orm_with_score(tx, score.score if score else None)


@router.delete("/transactions/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(tx_id: int) -> None:
    async def _do_delete():
        return await transaction_repo.delete(tx_id)

    ok = await safe_write(_do_delete)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "TX_NOT_FOUND", "message": f"交易 #{tx_id} 不存在"},
        )


# ============================================================
# Watchlist
# ============================================================

@router.get("/watchlist", response_model=WatchlistListOut)
async def list_watchlist() -> WatchlistListOut:
    items = await watchlist_repo.list_all()
    return WatchlistListOut(
        items=[WatchlistOut.model_validate(item) for item in items]
    )


@router.post(
    "/watchlist",
    response_model=WatchlistOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_to_watchlist(payload: WatchlistAdd) -> WatchlistOut:
    row = await watchlist_repo.add(
        stock_code=payload.stock_code,
        stock_name=payload.stock_name,
        note=payload.note,
    )
    return WatchlistOut.model_validate(row)


@router.delete("/watchlist/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_watchlist(code: str) -> None:
    ok = await watchlist_repo.remove(code)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "WL_NOT_FOUND", "message": f"自选股 {code} 不存在"},
        )