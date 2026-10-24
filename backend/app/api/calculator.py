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
    realized_pnl_gross: str  # GB-001 IR-4:不含费用
    realized_pnl_net: str    # GB-001 IR-4:扣除费用
    fee_paid: str            # GB-001 IR-4:本笔费用


class CalculatorResponse(BaseModel):
    algo_version: str = "2.0"
    input: CalculatorRequest
    before: CalculatorBefore
    after: CalculatorAfter
    pnl_grid: list[PnlGridRow]


# ============================================================
# 拟交易复核(v0.6 新增)
#
# 与 /calculator 的分工:
# - /calculator        纯算术,秒出,回答「成交后持仓长什么样」
# - /calculator/review 深度判定,回答「这笔对不对 / 适合做 T 吗 / T 时机是什么」
#
# 判定规则全部在纯函数层 app/services/trade_review_service.py,
# 本层只做 IO 编排 + 错误码映射。
# ============================================================

class ReviewPriceCheck(BaseModel):
    suggested: float | None
    your_price: float
    verdict: str
    note: str


class ReviewSizeCheck(BaseModel):
    suggested_shares: int | None
    your_shares: int
    note: str


class ReviewTAssessment(BaseModel):
    suitable: bool
    t_high: float | None
    t_low: float | None
    sell_trigger: str
    buyback_trigger: str
    your_price_in_range: bool | None
    max_t_shares: int | None
    note: str


class ReviewPositionAfter(BaseModel):
    shares: int
    avg_cost: str | None
    total_cost: str
    realized_pnl: str


class ReviewTStep(BaseModel):
    role: str
    text: str


class ReviewTDirection(BaseModel):
    """做 T 的一个方向(反T / 正T)"""

    key: str
    label: str
    applicable: bool
    # ok / no_cash / cash_too_little / no_position / not_suitable / no_t_range
    # / base_too_large / no_base_ratio / unknown
    # 前端据此决定「缺资金 → 引导去填」还是「真不适用 → 只灰显」
    reason_code: str
    prerequisite: str
    max_shares: int | None
    max_amount: str | None
    steps: list[ReviewTStep]
    status_text: str


class ReviewRequest(CalculatorRequest):
    """POST /api/calculator/review body

    `cash_available` 是**可选覆盖值**:
    - 字段未传 → 用账户已保存的可用资金
    - 传 null    → 明确表示「没有可用资金」(判定层据此给正T 股数 = null)
    - 传数字     → 本次试算用这个值(不落库)

    区分「未传」与「传 null」靠 Pydantic v2 的 `model_fields_set`
    (字段是否出现在请求体里),不用哨兵值 —— 契约更直白。
    """

    cash_available: Decimal | None = Field(default=None, ge=0)


class ReviewTDirections(BaseModel):
    """正T / 反T 两行对照 + 推荐"""

    reverse: ReviewTDirection
    forward: ReviewTDirection
    recommended: str | None
    recommend_reason: str
    your_leg: str | None
    t_plus_one_note: str


class TradeReviewResponse(BaseModel):
    verdict: Literal["ok", "conditional", "not_recommended", "unknown"]
    headline: str
    reasons: list[str]
    blockers: list[str]
    price_check: ReviewPriceCheck
    size_check: ReviewSizeCheck
    t_assessment: ReviewTAssessment
    position_after: ReviewPositionAfter
    risk_flags: list[str]
    degraded: list[str]
    t_directions: ReviewTDirections


@router.post("/calculator", response_model=CalculatorResponse)
async def calculator(req: CalculatorRequest) -> CalculatorResponse:
    """试算交易后的持仓 + 21 档盈亏表

    v2.1 §5.1
    """
    # 1. 取当前持仓(用于 before)
    from app.modules.portfolio.service import get_position

    position = await get_position(req.stock_code)
    shares_before = position.shares if position else 0
    # ⚠️ 必须用**未量化**的均价做链计算(与 portfolio 的 ChainState.avg_cost 同源):
    # Position.avg_cost 是 3 位小数量化值,而 v0.5 起真实均价可能有 6 位
    # (002185 = 17021.46 / 1000 = 17.02146)。
    # 直接拿量化值算,每次试算都会把 total_cost 拉偏(17021.46 → 17021.00,差 0.46 元),
    # 且与 /calculator/review 的 position_after 对不上。
    cost_before = (
        position.total_cost / position.shares
        if position is not None and position.shares > 0
        else Decimal("0")
    )
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
    # GB-001 IR-4:读费用参数(开启时双口径,关闭时 net=gross)
    from app.core.instrument import fees_for_instrument
    from app.repositories.cost_settings_repo import cost_settings_repo

    fees_holder = await cost_settings_repo.get()
    fees = fees_holder if fees_holder.enabled else None
    # 品种差异:场内 ETF 免印花税、免过户费 → 换 ETF 费用档
    fees = fees_for_instrument(req.stock_code, fees)

    try:
        result = calculate_after_transaction(
            shares_before=shares_before,
            cost_before=cost_before,
            action=req.action,
            tx_shares=req.tx_shares,
            tx_price=req.tx_price,
            fees=fees,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "CALC_ERROR", "message": str(e)},
        ) from e

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
            realized_pnl_gross=str(result["realized_pnl_gross"]),
            realized_pnl_net=str(result["realized_pnl_net"]),
            fee_paid=str(result["fee_paid"]),
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


@router.post("/calculator/review", response_model=TradeReviewResponse)
async def calculator_review(req: ReviewRequest) -> TradeReviewResponse:
    """拟交易复核:这笔买卖是否正确 / 是否适合做 T / 做 T 的时机

    判定全部走纯函数层(`app/services/trade_review_service.py`),
    本端点只负责拉数据(K 线 + 指标 + 行情 + 持仓 + 大盘)与错误码映射。

    - 卖出超过持仓 → 422 INSUFFICIENT_SHARES(与 /calculator 同文案)
    - K 线完全不可用 → 502 DATA_SOURCE_UNAVAILABLE
    - 其余数据源失败 → 对应字段降级为 null + degraded(不编数字)
    """
    from app.modules.calculator.service import (
        CASH_UNSET,
        CalculatorDataUnavailable,
        review_proposed_trade,
    )
    from app.modules.portfolio.service import get_position

    # 1. 卖出超额 → 422(前端已有同样的错误处理)
    # 持仓读失败(SQLite 并发写时可能 locked)不能让整张判定卡 500 ——
    # 按空仓继续,真正的降级标注由 IO 层写进 degraded。
    # 注意:读失败时**不**做超额校验(否则会把正常的卖出误判成 422)。
    position_failed = False
    try:
        position = await get_position(req.stock_code)
    except Exception:  # noqa: BLE001
        position = None
        position_failed = True
    shares_before = position.shares if position else 0
    if not position_failed and req.action == "sell" and req.tx_shares > shares_before:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INSUFFICIENT_SHARES",
                "message": f"这只票只剩 {shares_before} 股了,卖不出 {req.tx_shares} 股",
                "detail": {"have": shares_before, "want": req.tx_shares},
            },
        )

    # 2. 深度判定
    # 可用资金:字段未传 → 用账户已保存的值;传 null → 明确"没有可用资金"
    cash: Decimal | None | object
    if "cash_available" in req.model_fields_set:
        cash = req.cash_available
    else:
        cash = CASH_UNSET
    try:
        result = await review_proposed_trade(
            req.stock_code, req.action, req.tx_shares, req.tx_price, cash
        )
    except CalculatorDataUnavailable as e:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "DATA_SOURCE_UNAVAILABLE",
                "message": f"K 线指标计算失败: {e}",
            },
        ) from e

    # 3. 组装
    return TradeReviewResponse(**result)