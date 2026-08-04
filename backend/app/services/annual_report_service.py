"""年度账单服务(backend-arch §5.7 / P6.1 v0.2 预留)

- 取所有 transactions(交易需要之前的成本基础,年初状态计算)
- 按 (trade_date, id) 排序后逐笔跑 cost_engine,记录年内 sell 的 realized_pnl
- 输出:year, realized_profit, realized_loss, net_pnl, win_rate, top5_profit, top5_loss

GB-001 修复(2026-08-04):
- IR-4:支持交易费用双口径(realized_*_gross / _net),费用参数来自 cost_settings
- IR-5:胜率按"平仓周期"聚合(一次建仓→彻底清仓为一个周期,做 T 不再虚增笔数)
  - T 净贡献:同股 3 日内反向交易的卖出盈亏合计
  - 时间加权收益率:modified Dietz 近似(加权平均占用资金)

P6.1 阶段只覆盖年内**已清仓**的股票(年内有 sell 且卖完,或部分卖出);
未清仓的浮动盈亏不在此服务内(避免复杂市值快照),后续 v0.2 可加。
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.cost_engine import TradeFees, calculate_after_transaction
from app.db import async_session
from app.models.orm import Transaction
from app.repositories.cost_settings_repo import cost_settings_repo

# 做 T 识别窗口(与 scorer.ROUND_TRIP_WINDOW_DAYS 保持一致,IR-2/IR-5 共用)
ROUND_TRIP_WINDOW_DAYS = 3


def _q_money(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"))


def _is_round_trip_sell(stock_trades: list[dict], idx: int) -> bool:
    """判断某笔卖出是否属于"做 T"(同股近 N 日内有买入)"""
    tx = stock_trades[idx]
    if tx["action"] != "sell":
        return False
    target = tx["trade_date"]
    for prev in stock_trades[:idx][::-1]:
        if (target - prev["trade_date"]).days > ROUND_TRIP_WINDOW_DAYS:
            break
        if prev["action"] == "buy":
            return True
    return False


def _modified_dietz(cycle_cash: list[tuple[date, Decimal]]) -> Decimal:
    """modified Dietz 时间加权收益率(IR-5)

    输入:一个平仓周期内的现金流流 [(date, amount)],amount>0 为流入(卖出),<0 为流出(买入)。
    期末价值=0(周期内已清仓),期初价值=0(周期起点空仓)。
    R = (EMV - BMV - CF) / (BMV + Σ w_i · CF_i)
      = (-Σ CF) / Σ(w_i · CF_i)     # EMV=BMV=0
    其中 w_i = 该现金流距周期结束的天数权重;仅对流出(买入)加权占用资金。
    """
    if not cycle_cash:
        return Decimal("0")
    start = min(d for d, _ in cycle_cash)
    end = max(d for d, _ in cycle_cash)
    span = (end - start).days
    if span <= 0:
        span = 1
    weighted_flow = Decimal("0")
    net_flow = Decimal("0")
    for d, amount in cycle_cash:
        w = Decimal((end - d).days) / Decimal(span)
        weighted_flow += amount * w
        net_flow += amount
    if weighted_flow == 0:
        return Decimal("0")
    return -net_flow / weighted_flow


async def get_annual_report(year: int) -> dict:
    """年度账单聚合"""
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    # GB-001 IR-4:读费用参数
    fees_cfg = await cost_settings_repo.get()
    fees: TradeFees | None = fees_cfg if fees_cfg.enabled else None

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
    closed_in_year: list[dict] = []  # [{code, name, realized_pnl_gross/net, trade_date, fee}]

    for tx in all_tx:
        h = holdings.setdefault(tx.stock_code, {"shares": 0, "cost": Decimal("0")})
        try:
            result = calculate_after_transaction(
                shares_before=h["shares"],
                cost_before=h["cost"],
                action=tx.action,
                tx_shares=tx.shares,
                tx_price=Decimal(tx.price),
                fees=fees,
            )
        except ValueError:
            # 数据异常(卖超额等),跳过
            continue
        h["shares"] = result["shares_after"]
        h["cost"] = result["cost_after"] if result["cost_after"] is not None else Decimal("0")
        if year_start <= tx.trade_date <= year_end and tx.action == "sell":
            gross = result["realized_pnl_gross"]
            net = result["realized_pnl_net"]
            if net != 0 or gross != 0:
                closed_in_year.append({
                    "stock_code": tx.stock_code,
                    "stock_name": tx.stock_name,
                    "realized_pnl_gross": gross,
                    "realized_pnl_net": net,
                    "fee_paid": result["fee_paid"],
                    "trade_date": tx.trade_date,
                })

    # 3. IR-5:按平仓周期聚合(同股:以"建仓→彻底清仓"为一个周期)
    #    周期构建:按股票分组,顺序扫描,持仓归零处切割为一个周期
    cycles: list[dict] = []
    for code in {c["stock_code"] for c in closed_in_year}:
        tx_list = [t for t in all_tx if t.stock_code == code]
        shares = 0
        period_pnl = Decimal("0")
        period_fee = Decimal("0")
        cycle_started = False
        cycle_cash: list[tuple[date, Decimal]] = []
        for t in tx_list:
            if t.action == "buy":
                shares += t.shares
                cycle_started = True
                cycle_cash.append((t.trade_date, -Decimal(t.price) * t.shares))
            else:
                if shares <= 0:
                    continue
                shares -= t.shares
                # 用 cost_engine 结果对应当前卖出的盈亏(fee 已含)
                matched = next(
                    (c for c in closed_in_year if c["stock_code"] == code and c["trade_date"] == t.trade_date),
                    None,
                )
                if matched:
                    period_pnl += matched["realized_pnl_net"]
                    period_fee += matched["fee_paid"]
                cycle_cash.append((t.trade_date, Decimal(t.price) * t.shares))
                if shares == 0 and cycle_started:
                    cycles.append({
                        "stock_code": code,
                        "stock_name": t.stock_name,
                        "pnl": period_pnl,
                        "fee": period_fee,
                        "closed_at": t.trade_date,
                        "dietz": _modified_dietz(cycle_cash),
                        "_cash": cycle_cash,
                    })
                    period_pnl = Decimal("0")
                    period_fee = Decimal("0")
                    cycle_cash = []
                    cycle_started = False

    # 4. IR-5:做 T 识别(同股近 3 日反向)
    #    按股票分组,标记每笔卖出是否 T(仅统计净贡献 = T 卖出的净已实现之和)
    t_contribution = Decimal("0")
    for code in {c["stock_code"] for c in closed_in_year}:
        tx_list = [t for t in all_tx if t.stock_code == code]
        sells = [i for i, t in enumerate(tx_list) if t.action == "sell"]
        for i in sells:
            if _is_round_trip_sell([{"action": t.action, "trade_date": t.trade_date} for t in tx_list], i):
                matched = next(
                    (c for c in closed_in_year if c["stock_code"] == code and c["trade_date"] == tx_list[i].trade_date),
                    None,
                )
                if matched:
                    t_contribution += matched["realized_pnl_net"]

    # 5. 聚合(双口径:gross = 不含费用,net = 含费用;前端默认展示 net)
    def _agg(key: str) -> tuple[Decimal, Decimal]:
        profit = sum((c[key] for c in closed_in_year if c[key] > 0), Decimal("0"))
        loss = sum((c[key] for c in closed_in_year if c[key] < 0), Decimal("0"))
        return profit, loss

    profit_g, loss_g = _agg("realized_pnl_gross")
    profit_n, loss_n = _agg("realized_pnl_net")

    n = len(closed_in_year)
    total_fee = sum((c["fee_paid"] for c in closed_in_year), Decimal("0"))

    # IR-5:胜率按平仓周期
    closed_cycles = [c for c in cycles if year_start <= c["closed_at"] <= year_end]
    win_cycles = [c for c in closed_cycles if c["pnl"] > 0]
    cycle_win_rate = len(win_cycles) / len(closed_cycles) if closed_cycles else 0.0

    # modified Dietz:各平仓周期按资金加权(资金占用 = 周期内累计流出)
    total_dietz = Decimal("0")
    total_capital = Decimal("0")
    for c in closed_cycles:
        capital = Decimal("0")
        for d, amount in c.get("_cash", []):
            if amount < 0:
                capital += -amount
        if capital > 0:
            total_dietz += c["dietz"] * capital
            total_capital += capital
    dietz_annual = (total_dietz / total_capital) if total_capital > 0 else None

    top5_profit = sorted(
        (c for c in closed_in_year if c["realized_pnl_net"] > 0),
        key=lambda c: -c["realized_pnl_net"],
    )[:5]
    top5_loss = sorted(
        (c for c in closed_in_year if c["realized_pnl_net"] < 0),
        key=lambda c: c["realized_pnl_net"],
    )[:5]

    return {
        "year": year,
        "realized_profit": str(_q_money(profit_n)),
        "realized_loss": str(_q_money(abs(loss_n))),
        "net_pnl": str(_q_money(profit_n + loss_n)),
        "realized_profit_gross": str(_q_money(profit_g)),
        "realized_loss_gross": str(_q_money(abs(loss_g))),
        "net_pnl_gross": str(_q_money(profit_g + loss_g)),
        "total_fee": str(_q_money(total_fee)),
        "closed_count": n,
        "win_rate": round(cycle_win_rate, 2),
        "closed_cycles": len(closed_cycles),
        "t_net_contribution": str(_q_money(t_contribution)),
        "trend_net_pnl": str(_q_money(profit_n + loss_n - t_contribution)),
        "dietz_return": str(round(float(dietz_annual), 4)) if dietz_annual is not None else None,
        "fees_enabled": fees_cfg.enabled,
        "top5_profit": [
            {"stock_code": c["stock_code"], "stock_name": c["stock_name"],
             "realized_pnl": str(c["realized_pnl_net"]), "trade_date": c["trade_date"].isoformat()}
            for c in top5_profit
        ],
        "top5_loss": [
            {"stock_code": c["stock_code"], "stock_name": c["stock_name"],
             "realized_pnl": str(c["realized_pnl_net"]), "trade_date": c["trade_date"].isoformat()}
            for c in top5_loss
        ],
        "no_transactions": False,
    }


__all__ = ["get_annual_report"]
