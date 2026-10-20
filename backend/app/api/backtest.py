"""回测 API(阶段2)

- POST /api/backtest/signal        → 历史选股信号回测(无前视偏差)
- POST /api/backtest/compare-weights → 多套权重对比(含前视偏差,仅供敏感度参考)
"""
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.backtest.service import compare_weights, run_signal_backtest

router = APIRouter(prefix="/backtest", tags=["backtest"])


class SignalBacktestIn(BaseModel):
    days: int = Field(default=180, ge=10, le=1000)
    hold_days: int = Field(default=10, ge=1, le=120)
    initial_capital: float = Field(default=1_000_000.0, gt=0)
    max_positions: int = Field(default=10, ge=1, le=50)
    slippage_bps: float = Field(default=0.0, ge=0, le=200)


class WeightSetIn(BaseModel):
    label: str
    # {factor_name: weight}
    weights: dict[str, float] = Field(default_factory=dict)


class CompareWeightsIn(BaseModel):
    weight_sets: list[WeightSetIn] = Field(min_length=1, max_length=5)
    days: int = Field(default=180, ge=10, le=1000)
    hold_days: int = Field(default=10, ge=1, le=120)
    initial_capital: float = Field(default=1_000_000.0, gt=0)
    max_positions: int = Field(default=10, ge=1, le=50)


@router.post("/signal")
async def signal_backtest(payload: SignalBacktestIn) -> dict:
    return await run_signal_backtest(
        days=payload.days,
        hold_days=payload.hold_days,
        initial_capital=payload.initial_capital,
        max_positions=payload.max_positions,
        slippage_bps=payload.slippage_bps,
    )


@router.post("/compare-weights")
async def compare(payload: CompareWeightsIn) -> dict:
    sets = {ws.label: ws.weights for ws in payload.weight_sets}
    return await compare_weights(
        weight_sets=sets,
        days=payload.days,
        hold_days=payload.hold_days,
        initial_capital=payload.initial_capital,
        max_positions=payload.max_positions,
    )
