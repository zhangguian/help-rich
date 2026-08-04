"""交易费用设置仓储(cost_settings 单行表,GB-001 IR-4)"""
from decimal import Decimal

from sqlalchemy import select

from app.core.cost_engine import TradeFees
from app.db import async_session
from app.models.orm import CostSettings


class CostSettingsRepository:
    async def get(self) -> TradeFees:
        """读取费用设置,无记录时插入默认值"""
        async with async_session() as session:
            row = await session.get(CostSettings, 1)
            if row is None:
                row = CostSettings(id=1)
                session.add(row)
                await session.commit()
                return TradeFees(enabled=False)
            return TradeFees(
                enabled=row.enabled,
                commission_rate=Decimal(row.commission_rate),
                min_commission=Decimal(row.min_commission),
                stamp_tax_rate=Decimal(row.stamp_tax_rate),
                transfer_fee_rate=Decimal(row.transfer_fee_rate),
            )

    async def save(
        self,
        enabled: bool,
        commission_rate: str,
        min_commission: str,
        stamp_tax_rate: str,
        transfer_fee_rate: str,
    ) -> TradeFees:
        """保存费用设置,返回最新 TradeFees"""
        async with async_session() as session:
            row = await session.get(CostSettings, 1)
            if row is None:
                row = CostSettings(id=1)
                session.add(row)
            row.enabled = enabled
            row.commission_rate = commission_rate
            row.min_commission = min_commission
            row.stamp_tax_rate = stamp_tax_rate
            row.transfer_fee_rate = transfer_fee_rate
            await session.commit()
        return TradeFees(
            enabled=enabled,
            commission_rate=Decimal(commission_rate),
            min_commission=Decimal(min_commission),
            stamp_tax_rate=Decimal(stamp_tax_rate),
            transfer_fee_rate=Decimal(transfer_fee_rate),
        )


cost_settings_repo = CostSettingsRepository()
