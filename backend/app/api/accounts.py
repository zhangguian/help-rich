"""投资账户 API(阶段5)

- GET    /api/accounts              → 账户列表(含持仓数/成本概览)
- POST   /api/accounts              → 新建账户
- PATCH  /api/accounts/{id}         → 重命名
- DELETE /api/accounts/{id}         → 删除(默认账户/有持仓/有流水时拒绝)
- GET    /api/accounts/{id}/summary → 单账户持仓与盈亏汇总
- GET    /api/accounts/{id}/cash     → 账户可用资金(null = 未填写)
- PUT    /api/accounts/{id}/cash     → 写账户可用资金(null = 清空)
"""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.portfolio.account_service import AccountError, account_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    kind: str = "broker"
    broker: str | None = None
    note: str | None = None


class AccountPatch(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class AccountCashIn(BaseModel):
    """写账户可用资金。null = 清空(= 未填写)。"""

    cash_available: Decimal | None = Field(default=None, ge=0)


class AccountCashOut(BaseModel):
    account_id: int
    cash_available: float | None = None


@router.get("")
async def list_accounts() -> dict:
    return {"items": await account_service.list_with_summary()}


@router.post("")
async def create_account(payload: AccountIn) -> dict:
    account_id = await account_service.create(
        payload.name, payload.kind, payload.broker, payload.note
    )
    return {"id": account_id}


@router.patch("/{account_id}")
async def rename_account(account_id: int, payload: AccountPatch) -> dict:
    try:
        await account_service.rename(account_id, payload.name)
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.delete("/{account_id}")
async def delete_account(account_id: int) -> dict:
    try:
        await account_service.delete(account_id)
    except AccountError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


@router.get("/{account_id}/summary")
async def account_summary(account_id: int) -> dict:
    try:
        return await account_service.summary(account_id)
    except AccountError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{account_id}/cash", response_model=AccountCashOut)
async def get_account_cash(account_id: int) -> AccountCashOut:
    """账户可用资金(正T 测算用)。null = 未填写。"""
    try:
        cash = await account_service.get_cash_available(account_id)
    except AccountError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return AccountCashOut(account_id=account_id, cash_available=cash)


@router.put("/{account_id}/cash", response_model=AccountCashOut)
async def put_account_cash(
    account_id: int, payload: AccountCashIn
) -> AccountCashOut:
    """写账户可用资金。传 null 表示清空(= 未填写)。"""
    value = payload.cash_available
    if value is not None:
        try:
            value = Decimal(value).quantize(Decimal("0.01"))
        except InvalidOperation:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_CASH",
                    "message": "可用资金必须是数字",
                    "detail": {"value": str(payload.cash_available)},
                },
            ) from None
    try:
        saved = await account_service.set_cash_available(account_id, value)
    except AccountError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return AccountCashOut(account_id=account_id, cash_available=saved)
