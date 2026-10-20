"""模拟盘 API(阶段3)

- GET    /api/paper-trading/accounts            → 账户列表
- POST   /api/paper-trading/accounts            → 新建账户
- GET    /api/paper-trading/{id}/summary        → 账户概览(现金/持仓/总收益)
- POST   /api/paper-trading/{id}/buy            → 买入(自动取最新价)
- POST   /api/paper-trading/{id}/sell           → 卖出
- GET    /api/paper-trading/{id}/orders         → 订单流水
- GET    /api/paper-trading/{id}/equity-curve   → 净值曲线 + 绩效指标
- POST   /api/paper-trading/{id}/snapshot       → 立即记录一次净值快照
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.paper_trading.service import PaperTradingError, paper_trading_service

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])


class AccountCreate(BaseModel):
    name: str = "模拟账户"
    initial_capital: str = Field(default="1000000.00")


class BuyIn(BaseModel):
    stock_code: str
    shares: int = Field(gt=0)
    note: str | None = None


class SellIn(BaseModel):
    stock_code: str
    shares: int = Field(gt=0)
    note: str | None = None


async def _fetch_price(stock_code: str) -> float:
    """取最新价。取不到直接报错 —— 绝不让用户手填价格(否则模拟即虚构)。"""
    from app.services.quote_service import QuoteService

    try:
        q = await QuoteService().get_quote(stock_code)
        return float(q.current_price)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"取行情失败: {e}") from e


def _wrap(coro):
    try:
        return coro
    except PaperTradingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/accounts")
async def list_accounts() -> dict:
    return {"items": await paper_trading_service.list_accounts()}


@router.post("/accounts")
async def create_account(payload: AccountCreate) -> dict:
    account_id = await paper_trading_service.create_account(
        payload.name, payload.initial_capital
    )
    return {"id": account_id}


@router.get("/{account_id}/summary")
async def summary(account_id: int) -> dict:
    try:
        return await paper_trading_service.get_summary(account_id)
    except PaperTradingError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{account_id}/buy")
async def buy(account_id: int, payload: BuyIn) -> dict:
    price = await _fetch_price(payload.stock_code)
    try:
        return await paper_trading_service.buy(
            account_id, payload.stock_code, payload.shares, price, note=payload.note
        )
    except PaperTradingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/{account_id}/sell")
async def sell(account_id: int, payload: SellIn) -> dict:
    price = await _fetch_price(payload.stock_code)
    try:
        return await paper_trading_service.sell(
            account_id, payload.stock_code, payload.shares, price, note=payload.note
        )
    except PaperTradingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{account_id}/orders")
async def orders(account_id: int, limit: int = 50) -> dict:
    return await paper_trading_service.list_orders(account_id, limit)


@router.get("/{account_id}/equity-curve")
async def equity_curve(account_id: int) -> dict:
    return await paper_trading_service.get_equity_curve(account_id)


@router.post("/{account_id}/snapshot")
async def snapshot(account_id: int) -> dict:
    try:
        return await paper_trading_service.snapshot_equity(account_id)
    except PaperTradingError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
