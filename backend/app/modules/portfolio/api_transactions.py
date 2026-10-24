"""交易流水 + 自选股 API(P2.1 / P2.2 实施)"""
from datetime import date
from decimal import Decimal
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
    WatchlistFavoriteUpdate,
    WatchlistListOut,
    WatchlistOut,
)
from app.modules.portfolio.repository import transaction_repo
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

    v0.5.0:录入 = 在链尾追加一笔 → 从基准重放全链 → 写快照 + 更新持仓行。
    卖出额度按「该笔落位时」的持仓判定(补录更早日期的流水也准)。
    """
    from app.modules.portfolio.service import (
        PositionChainError,
        TxSpec,
        check_chain,
        recalc_position,
        shares_available_at,
    )

    # 校验:卖出不能超过持仓(v0.5.0 按该笔落位时的链状态判定)
    if payload.action == "sell":
        current_shares = await shares_available_at(
            payload.stock_code, payload.trade_date
        )
        if payload.shares > current_shares:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INSUFFICIENT_SHARES",
                    "message": f"这只票在 {payload.trade_date} 只剩 {current_shares} 股了,卖不出 {payload.shares} 股",
                    "detail": {"have": current_shares, "want": payload.shares},
                },
            )

    price_str = format(payload.price, ".3f")  # Decimal → "10.500"

    # 写库前先验算:确保落库后链仍然自洽
    try:
        await check_chain(
            payload.stock_code,
            insert=TxSpec(
                id=0,
                trade_date=payload.trade_date,
                action=payload.action,
                shares=payload.shares,
                price=payload.price,
            ),
        )
    except PositionChainError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "CHAIN_INVALID", "message": str(e)},
        ) from e

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

    # v0.5.0:流水变动 → 从基准重放链尾,重写快照 + 持仓行
    await recalc_position(tx.stock_code)

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

    from app.modules.portfolio.service import (
        PositionChainError,
        TxSpec,
        check_chain,
        is_absorbed,
        recalc_position,
    )

    before = await transaction_repo.get_by_id(tx_id)
    if before is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TX_NOT_FOUND", "message": f"交易 #{tx_id} 不存在"},
        )

    # v0.5.0:已被导入基准吸收的流水不参与重放,改它不会影响成本 → 明确拒绝
    if await is_absorbed(before.stock_code, tx_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TX_ABSORBED",
                "message": (
                    f"交易 #{tx_id} 已被导入的持仓基准吸收,修改它不会改变成本价。"
                    "如需修正这笔历史,请先在持仓页重新导入该股票的基准。"
                ),
            },
        )

    # 写库前先验算改完之后链是否自洽
    new_shares = updates.get("shares", before.shares)
    new_price = Decimal(updates["price"]) if "price" in updates else Decimal(before.price)
    try:
        await check_chain(
            before.stock_code,
            override=TxSpec(
                id=before.id,
                trade_date=before.trade_date,
                action=before.action,
                shares=new_shares,
                price=new_price,
            ),
        )
    except PositionChainError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "CHAIN_INVALID", "message": str(e)},
        ) from e

    async def _do_update():
        return await transaction_repo.update(tx_id, **updates)

    tx = await safe_write(_do_update)
    if tx is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TX_NOT_FOUND", "message": f"交易 #{tx_id} 不存在"},
        )

    await recalc_position(tx.stock_code)

    from app.repositories.trade_score_repo import trade_score_repo
    score = await trade_score_repo.get_by_trade_id(tx.id)
    return TransactionOut.from_orm_with_score(tx, score.score if score else None)


@router.delete("/transactions/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(tx_id: int) -> None:
    from app.db import async_session as _db_session
    from app.models.orm import Transaction as _TxOrm
    from sqlalchemy import select as _select

    async with _db_session() as _s:
        _row = (
            await _s.execute(_select(_TxOrm).where(_TxOrm.id == tx_id))
        ).scalar_one_or_none()
        _code = _row.stock_code if _row else None

    from app.modules.portfolio.service import (
        PositionChainError,
        check_chain,
        is_absorbed,
        recalc_position,
    )

    # v0.5.0:已被基准吸收的流水不参与重放,删它不会改变成本 → 明确拒绝
    if _code and await is_absorbed(_code, tx_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TX_ABSORBED",
                "message": (
                    f"交易 #{tx_id} 已被导入的持仓基准吸收,删除它不会改变成本价。"
                    "如需清掉这段历史,请先在持仓页重新导入该股票的基准。"
                ),
            },
        )

    # 删掉这笔后链是否还自洽(例如后面的卖出会失去成本基准)
    if _code:
        try:
            await check_chain(_code, drop_id=tx_id)
        except PositionChainError as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "CHAIN_INVALID",
                    "message": f"删除这笔会让后续流水失去成本基准:{e}",
                },
            ) from e

    async def _do_delete():
        return await transaction_repo.delete(tx_id)

    ok = await safe_write(_do_delete)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "TX_NOT_FOUND", "message": f"交易 #{tx_id} 不存在"},
        )

    if _code:
        await recalc_position(_code)


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


@router.patch("/watchlist/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def update_watchlist_favorite(
    code: str, payload: WatchlistFavoriteUpdate
) -> None:
    """切换特别关注标记(v0.5)"""
    from app.core.stock_code import normalize_code

    normalized = normalize_code(code) or code
    ok = await watchlist_repo.set_favorite(normalized, payload.is_favorite)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "WL_NOT_FOUND", "message": f"自选股 {normalized} 不存在"},
        )