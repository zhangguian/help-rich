"""计算器 API(P3.2 实施)

POST /api/calculator 试算加仓/减仓/做T 后新成本 + 21 档盈亏表

v2.1 §5.1 / docs/api-contract §5.1
"""
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.cost_engine import (
    PRICE_QUANTUM,
    build_pnl_grid,
    calculate_after_transaction,
)

router = APIRouter(tags=["calculator"])


class CalculatorRequest(BaseModel):
    """POST /api/calculator body

    stock_code: 接受 600519 / 600519.SH / sh600519,统一转规范格式(P3.5.1)
    """
    stock_code: str
    action: Literal["buy", "sell"]
    tx_shares: int = Field(gt=0)
    tx_price: Decimal = Field(gt=0, max_digits=10, decimal_places=3)

    @field_validator("stock_code")
    @classmethod
    def _normalize_stock_code(cls, v: str) -> str:
        from app.core.stock_code import normalize_code

        normalized = normalize_code(v)
        if normalized is None:
            raise ValueError("股票代码格式应为 6 位数字或带市场后缀(如 600519.SH)")
        return normalized


class PnlGridRow(BaseModel):
    pct: int
    price: str  # 字符串保精度
    market_value: str
    pnl: str


class CalculatorBefore(BaseModel):
    shares: int
    cost_price: str
    total_cost: str


class CalculatorAfter(BaseModel):
    shares: int
    cost_price: str | None  # 清仓时 None
    total_cost: str
    delta_cost: str | None
    realized_pnl: str


class CalculatorResponse(BaseModel):
    algo_version: str = "2.0"
    input: CalculatorRequest
    before: CalculatorBefore
    after: CalculatorAfter
    pnl_grid: list[PnlGridRow]


@router.post("/calculator", response_model=CalculatorResponse)
async def calculator(req: CalculatorRequest) -> CalculatorResponse:
    """试算交易后的持仓 + 21 档盈亏表

    v2.1 §5.1
    """
    # 1. 取当前持仓(用于 before)
    from app.services.position_service import get_position

    position = await get_position(req.stock_code)
    shares_before = position.shares if position else 0
    cost_before = position.avg_cost if position else Decimal("0")
    total_cost_before = position.total_cost if position else Decimal("0")

    # 2. 边界校验:卖出超额 → 422
    if req.action == "sell" and req.tx_shares > shares_before:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INSUFFICIENT_SHARES",
                "message": f"这只票只剩 {shares_before} 股了,卖不出 {req.tx_shares} 股",
                "detail": {"have": shares_before, "want": req.tx_shares},
            },
        )

    # 3. 调纯函数
    price_str = format(req.tx_price, ".3f")
    try:
        result = calculate_after_transaction(
            shares_before=shares_before,
            cost_before=cost_before,
            action=req.action,
            tx_shares=req.tx_shares,
            tx_price=req.tx_price,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "CALC_ERROR", "message": str(e)},
        )

    # 4. 构造 21 档网格
    grid_rows = build_pnl_grid(
        cost_after=result["cost_after"],
        shares_after=result["shares_after"],
    )

    # 5. 组装响应
    return CalculatorResponse(
        algo_version="2.0",
        input=req,
        before=CalculatorBefore(
            shares=shares_before,
            cost_price=str(cost_before.quantize(PRICE_QUANTUM)) if cost_before > 0 else "0.000",
            total_cost=str(total_cost_before.quantize(Decimal("0.01"))),
        ),
        after=CalculatorAfter(
            shares=result["shares_after"],
            cost_price=(
                str(result["cost_after"].quantize(PRICE_QUANTUM))
                if result["cost_after"] is not None else None
            ),
            total_cost=str(result["total_cost_after"]),
            delta_cost=(
                str(result["delta_cost"].quantize(PRICE_QUANTUM))
                if result["delta_cost"] is not None else None
            ),
            realized_pnl=str(result["realized_pnl"]),
        ),
        pnl_grid=[
            PnlGridRow(
                pct=row["pct"],
                price=str(row["price"]),
                market_value=str(row["market_value"]),
                pnl=str(row["pnl"]),
            )
            for row in grid_rows
        ],
    )