"""年度账单服务(backend-arch §5.7 / P6.1 v0.2 预留)

- 取所有 transactions(交易需要之前的成本基础,年初状态计算)
- 按 (trade_date, id) 排序后逐笔跑 cost_engine,记录年内 sell 的 realized_pnl
- 输出:year, realized_profit, realized_loss, net_pnl, win_rate, top5_profit, top5_loss

P6.1 阶段只覆盖年内**已清仓**的股票(年内有 sell 且卖完,或部分卖出);
未清仓的浮动盈亏不在此服务内(避免复杂市值快照),后续 v0.2 可加。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.cost_engine import calculate_after_transaction
from app.db import async_session
from app.models.orm import Transaction


def _q_money(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"))


async def get_annual_report(year: int) -> dict:
    """年度账单聚合"""
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    # 1. 加载所有交易(需要之前的成本基础来算 sell 的 realized)
    async with async_session() as session:
        stmt = select(Transaction).order_by(Transaction.trade_date, Transaction.id)
        all_tx = list((await session.execute(stmt)).scalars().all())

    if not all_tx:
        # v0.4.0:无流水 → 明确提示(持仓可直接导入,不强制有流水)
        return {
            "year": year,
            "realized_profit": "0.00",
            "realized_loss": "0.00",
            "net_pnl": "0.00",
            "closed_count": 0,
            "win_rate": 0.0,
            "top5_profit": [],
            "top5_loss": [],
            "no_transactions": True,
        }

    # 2. 按 stock 分桶,逐笔跑 cost_engine
    holdings: dict[str, dict] = {}  # code -> {"shares": int, "cost": Decimal}
    closed_in_year: list[dict] = []  # [{code, name, realized_pnl, closed_at: date}]

    for tx in all_tx:
        h = holdings.setdefault(tx.stock_code, {"shares": 0, "cost": Decimal("0")})
        try:
            result = calculate_after_transaction(
                shares_before=h["shares"],
                cost_before=h["cost"],
                action=tx.action,
                tx_shares=tx.shares,
                tx_price=Decimal(tx.price),
            )
        except ValueError:
            # 数据异常(卖超额等),跳过
            continue
        h["shares"] = result["shares_after"]
        h["cost"] = result["cost_after"] if result["cost_after"] is not None else Decimal("0")
        if year_start <= tx.trade_date <= year_end and tx.action == "sell":
            realized = result["realized_pnl"]
            if realized != 0:
                closed_in_year.append({
                    "stock_code": tx.stock_code,
                    "stock_name": tx.stock_name,
                    "realized_pnl": realized,
                    "trade_date": tx.trade_date.isoformat(),
                })

    # 3. 聚合
    profit_list = [c for c in closed_in_year if c["realized_pnl"] > 0]
    loss_list = [c for c in closed_in_year if c["realized_pnl"] < 0]

    total_profit = sum((c["realized_pnl"] for c in profit_list), Decimal("0"))
    total_loss = sum((c["realized_pnl"] for c in loss_list), Decimal("0"))

    n = len(closed_in_year)
    win_rate = len(profit_list) / n if n > 0 else 0.0

    top5_profit = sorted(profit_list, key=lambda c: -c["realized_pnl"])[:5]
    top5_loss = sorted(loss_list, key=lambda c: c["realized_pnl"])[:5]

    return {
        "year": year,
        "realized_profit": str(_q_money(total_profit)),
        "realized_loss": str(_q_money(abs(total_loss))),
        "net_pnl": str(_q_money(total_profit + total_loss)),
        "closed_count": n,
        "win_rate": round(win_rate, 2),
        "top5_profit": [
            {"stock_code": c["stock_code"], "stock_name": c["stock_name"],
             "realized_pnl": str(c["realized_pnl"]), "trade_date": c["trade_date"]}
            for c in top5_profit
        ],
        "top5_loss": [
            {"stock_code": c["stock_code"], "stock_name": c["stock_name"],
             "realized_pnl": str(c["realized_pnl"]), "trade_date": c["trade_date"]}
            for c in top5_loss
        ],
        "no_transactions": False,
    }


__all__ = ["get_annual_report"]