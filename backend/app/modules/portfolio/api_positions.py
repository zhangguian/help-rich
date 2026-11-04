"""持仓 API(P2.3 实施,P3.5.1 扩展行情字段,v0.4.0 持仓主数据化)

v0.4.0:positions 表为主数据(手动录入 / 截图导入 / 流水同步),
- GET    /api/positions          列出当前持仓(含今日盈亏)
- POST   /api/positions          手动录入 / 覆盖单只持仓(每股成本价)
- DELETE /api/positions/{code}   删除单只持仓(流水保留)

P3.5.1(今日盈亏):引入 QuoteService(新浪主 + 腾讯备 + 5min 缓存),
返回 current_price / prev_close / today_pnl / floating_pnl。

v0.12 今日盈亏口径(2026-11-04):改成**券商口径** —— 当日总资产变动,
含今天买卖的现金影响(公式与推导见 `_today_pnl`)。
行情全部失败时这些字段为 null,前端降级为骨架屏/"--"。
"""
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.db_lock import safe_write
from app.models.schemas import ClearPositionRequest, PositionCreate
from app.modules.portfolio.repository import transaction_repo
from app.modules.portfolio.service import (
    delete_position,
    get_all_positions,
    get_position,
    upsert_position,
)
from app.services.quote_service import QuoteService

router = APIRouter(tags=["positions"])

_quote_service: QuoteService | None = None


def get_quote_service() -> QuoteService:
    global _quote_service
    if _quote_service is None:
        _quote_service = QuoteService()
    return _quote_service


def _today_pnl(
    shares: int,
    price: Decimal,
    prev_close: Decimal,
    flow: dict | None,
) -> Decimal:
    """当日盈亏(**券商口径**)。

    券商持仓页的「当日盈亏」= **当日总资产变动**,不是「(现价−昨收)×持股数」:

    ```
    当日盈亏 = (当前持股×现价 + 今日卖出所得现金 − 今日买入支出现金)
               − 昨收 × 昨日持股数
    昨日持股数 = 当前持股 − 今日买入股数 + 今日卖出股数
    ```

    **为什么必须算成这个口径**:今天买卖过的票,券商的当日盈亏与「只按当前持股算价差」
    差得很远(实测 000657 差 134 元、002185 差 95 元、001896 差 7 元、5 只 ETF 全对得上),
    因为**今天卖出/买入的那部分**,券商是按「成交价 vs 昨收」计的,不是按现价。

    没有今天的流水 → 退化成 `(现价 − 昨收) × 持股数`(与旧口径一致)。
    昨收不可用(≤0)→ 同样退化(不拿 0 当昨收算)。
    """
    if not flow or prev_close <= 0:
        return (price - prev_close) * shares
    yesterday_shares = shares - int(flow["buy_shares"]) + int(flow["sell_shares"])
    if yesterday_shares < 0:
        # 流水与持仓对不上(理论上不会:卖出超过持仓会被链校验挡住)→ 退回已验证口径
        return (price - prev_close) * shares
    return (
        price * shares + flow["sell_amount"] - flow["buy_amount"]
    ) - prev_close * yesterday_shares


async def _today_trade_flow(codes: list[str]) -> dict[str, dict]:
    """今天(自然日)的买卖流水汇总 —— 今日盈亏要用它算「当日总资产变动」。

    按标的聚合:买入金额/股数、卖出金额/股数。
    只认**今天**的流水:昨天的成交已经体现在昨收里,再算一遍就重复了。
    """
    from datetime import date

    from sqlalchemy import select

    from app.db import async_session
    from app.models.orm import Transaction
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    if not codes:
        return {}
    today = date.today()
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Transaction).where(
                    Transaction.account_id == DEFAULT_ACCOUNT_ID,
                    Transaction.stock_code.in_(codes),
                    Transaction.trade_date == today,
                )
            )
        ).scalars().all()

    flow: dict[str, dict] = {}
    for t in rows:
        f = flow.setdefault(
            t.stock_code,
            {
                "buy_amount": Decimal(0),
                "buy_shares": 0,
                "sell_amount": Decimal(0),
                "sell_shares": 0,
            },
        )
        amount = Decimal(t.price) * int(t.shares)
        if t.action == "buy":
            f["buy_amount"] += amount
            f["buy_shares"] += int(t.shares)
        else:
            f["sell_amount"] += amount
            f["sell_shares"] += int(t.shares)
    return flow


@router.get("/positions")
async def list_positions() -> dict:
    """列出当前持仓(含今日盈亏)

    P3.5.1 新增字段:
      current_price: 现价(行情)
      prev_close:    昨收
      today_pnl:     今日盈亏(**券商口径**:当日总资产变动,含今天买卖的现金影响
                     —— 见 `_today_pnl`;没有今天的流水时退化成 (现价−昨收)×持股数)
      floating_pnl:  浮动盈亏 = (现价 - 成本) × 持仓股数
    行情不可用时为 null。

    v0.11 成本口径:
      avg_cost      = **摊薄成本价**(券商持仓页口径 = 净投入 ÷ 持股数)
      total_cost    = 摊薄总额(净投入 = 累计买入金额 − 累计卖出金额)
      floating_pnl  按摊薄成本算 → 与券商持仓页的浮动盈亏同口径
    """
    positions = await get_all_positions()
    from app.core.stock_code import normalize_code

    codes = [normalize_code(p.stock_code) or p.stock_code for p in positions]
    codes = [c for c in codes if c]
    quotes: dict[str, object] = {}
    if codes:
        quotes = {q.code: q for q in await get_quote_service().get_quotes(codes)}

    # 今日的买卖流水(当日盈亏要按「当日总资产变动」算,见 _today_pnl)
    today_flow = await _today_trade_flow(codes)

    items = []
    for p in positions:
        item = {
            "stock_code": p.stock_code,
            "stock_name": p.stock_name,
            "shares": p.shares,
            "avg_cost": str(p.avg_cost),
            "total_cost": str(p.total_cost.quantize(Decimal("0.01"))),
            "realized_pnl": str(p.realized_pnl.quantize(Decimal("0.01"))),
        }
        q = quotes.get(p.stock_code)
        if q is not None:
            price = q.current_price
            prev_close = q.prev_close
            item["current_price"] = str(price)
            item["prev_close"] = str(prev_close)
            item["today_pnl"] = str(
                _today_pnl(
                    p.shares,
                    Decimal(str(price)),
                    Decimal(str(prev_close)),
                    today_flow.get(p.stock_code),
                ).quantize(Decimal("0.01"))
            )
            item["floating_pnl"] = str(((price - p.avg_cost) * p.shares).quantize(Decimal("0.01")))
        else:
            item["current_price"] = None
            item["prev_close"] = None
            item["today_pnl"] = None
            item["floating_pnl"] = None
        items.append(item)
    return {"items": items}


@router.post("/positions", status_code=201)
async def create_position(payload: PositionCreate) -> dict:
    """手动录入 / 覆盖单只持仓(v0.4.0)

    覆盖语义(v0.5.0):以用户提交的股数/每股成本价为准,并**重置基准**
    —— 该股票现有流水全部视为「已被基准吸收」,不再参与重放。

    cost_price 口径(v0.11):**摊薄成本价**(= 券商持仓页的「成本价」),
    录入后展示值与录入值完全一致,不受已实现盈亏影响。

    realized_pnl(可选):用户手填的累计已实现盈亏(可为负)。
    不传 = 沿用当前累计值。

    base_date(可选):这份持仓快照是哪一天。只吸收该日期(含)之前的流水,
    该日期之后的流水留在链里继续生效(可改可删、每笔带 after 快照)。
    """
    pos = await upsert_position(
        stock_code=payload.stock_code,
        shares=payload.shares,
        cost_price=payload.cost_price,
        stock_name=payload.stock_name,
        realized_pnl=payload.realized_pnl,
        base_date=payload.base_date,
    )
    return {
        "stock_code": pos.stock_code,
        "stock_name": pos.stock_name,
        "shares": pos.shares,
        "total_cost": str(pos.total_cost.quantize(Decimal("0.01"))),
        "avg_cost": str(pos.avg_cost),
        "realized_pnl": str(pos.realized_pnl.quantize(Decimal("0.01"))),
    }


@router.delete("/positions/{code}", status_code=204)
async def remove_position(code: str) -> None:
    """删除单只持仓(v0.4.0)

    联动语义:持仓是主数据,流水是它的影子事件记录。
    删除持仓 → 同时删除该股票全部流水 + 评分(trade_scores 级联删除),防止 recalc 复活。
    """
    from app.core.stock_code import normalize_code
    from app.modules.portfolio.repository import transaction_repo

    normalized = normalize_code(code) or code
    deleted = await delete_position(normalized)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "POSITION_NOT_FOUND", "message": f"持仓 {normalized} 不存在"},
        )
    await transaction_repo.delete_by_stock(normalized)


@router.post("/positions/{code}/clear", status_code=201)
async def clear_position(
    code: str,
    payload: ClearPositionRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """一键清仓(v0.4.1 / P-stop-loss-v2)

    以指定价格(默认当前行情价)卖出当前持仓的全部股数。
    业务逻辑:
    1. 取当前持仓(不存在 → 404)
    2. 创建 sell 流水(覆盖全部 shares + payload.price,时间点 = 当前时刻)
    3. recalc_position 触发 → 持仓归零(保留持仓行,已实现盈亏留存)
    4. 返回生成的 sell 流水记录 + 预估已实现盈亏

    评分:清仓也是一笔交易 → 后台触发评分(与 /transactions 录入同口径),
    否则这笔流水会**永远没有分数**(历史 bug:清仓路径不触发评分)。
    """
    from datetime import date as date_cls
    from datetime import datetime as dt_cls
    from decimal import Decimal

    from app.core.stock_code import normalize_code
    from app.modules.portfolio.service import recalc_position

    normalized = normalize_code(code) or code
    pos = await get_position(normalized)
    if pos is None or pos.shares <= 0:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "POSITION_NOT_FOUND",
                "message": f"持仓 {normalized} 不存在或已清仓",
            },
        )

    shares = pos.shares
    price = payload.price
    realized = (price - pos.avg_cost) * shares  # 预估已实现盈亏

    async def _do_create():
        return await transaction_repo.create(
            stock_code=normalized,
            stock_name=pos.stock_name,
            action="sell",
            shares=shares,
            price=f"{price:.3f}",
            trade_date=date_cls.today(),
            # 清仓发生在当下 → 时间点 = 当前时刻(不是未知)
            trade_time=dt_cls.now().time(),
            note=payload.note or "一键清仓",
        )

    tx = await safe_write(_do_create)
    await recalc_position(normalized)

    # 后台评分(不阻塞响应)
    from app.services.diagnose_service import diagnose_service

    background_tasks.add_task(diagnose_service.score_and_notify, tx.id)

    return {
        "stock_code": normalized,
        "shares": shares,
        "price": f"{price:.3f}",
        "realized_pnl": str(realized.quantize(Decimal("0.01"))),
        "trade_id": tx.id,
        "trade_date": tx.trade_date.isoformat(),
    }
