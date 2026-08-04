"""交易费用设置 API(GB-001 IR-4)

- GET /api/cost/settings  → 返回费用参数 + enabled
- PUT /api/cost/settings  → 保存费用参数

默认关闭:enabled=false 时所有代价/盈亏展示完全不含费用(保持旧版行为)。
"""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.repositories.cost_settings_repo import cost_settings_repo

router = APIRouter(prefix="/cost", tags=["cost"])


class CostSettingsIn(BaseModel):
    enabled: bool = False
    commission_rate: str = "0.00025"
    min_commission: str = "5.00"
    stamp_tax_rate: str = "0.0005"
    transfer_fee_rate: str = "0.00001"


class CostSettingsOut(CostSettingsIn):
    pass


@router.get("/settings", response_model=CostSettingsOut)
async def get_cost_settings() -> CostSettingsOut:
    """获取费用参数"""
    f = await cost_settings_repo.get()
    return CostSettingsOut(
        enabled=f.enabled,
        commission_rate=str(f.commission_rate),
        min_commission=str(f.min_commission),
        stamp_tax_rate=str(f.stamp_tax_rate),
        transfer_fee_rate=str(f.transfer_fee_rate),
    )


@router.put("/settings", response_model=CostSettingsOut)
async def put_cost_settings(payload: CostSettingsIn) -> CostSettingsOut:
    """保存费用参数(数值字段必须是合法 Decimal)"""
    for label, v in {
        "commission_rate": payload.commission_rate,
        "min_commission": payload.min_commission,
        "stamp_tax_rate": payload.stamp_tax_rate,
        "transfer_fee_rate": payload.transfer_fee_rate,
    }.items():
        try:
            d = Decimal(v)
        except InvalidOperation:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_RATE",
                    "message": f"{label} 必须是数字",
                    "detail": {"field": label, "value": v},
                },
            )
        if d < 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_RATE",
                    "message": f"{label} 不能为负数",
                    "detail": {"field": label, "value": v},
                },
            )
    f = await cost_settings_repo.save(
        enabled=payload.enabled,
        commission_rate=payload.commission_rate,
        min_commission=payload.min_commission,
        stamp_tax_rate=payload.stamp_tax_rate,
        transfer_fee_rate=payload.transfer_fee_rate,
    )
    return CostSettingsOut(
        enabled=f.enabled,
        commission_rate=str(f.commission_rate),
        min_commission=str(f.min_commission),
        stamp_tax_rate=str(f.stamp_tax_rate),
        transfer_fee_rate=str(f.transfer_fee_rate),
    )


__all__ = ["router"]