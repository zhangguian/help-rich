"""统一行情格式(arch §5.5)"""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class UnifiedQuote(BaseModel):
    """所有数据源归一为内部统一格式"""

    code: str
    name: str
    current_price: Decimal
    prev_close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    change: Decimal
    change_pct: float
    volume: int
    amount: Decimal
    timestamp: datetime

    # 可选字段
    turnover_pct: float | None = None
    pe: float | None = None
    pb: float | None = None
