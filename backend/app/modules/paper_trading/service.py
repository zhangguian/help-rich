"""模拟盘用例层(阶段3)。

核心目标:让用户**零风险验证选股/提醒闭环**,因此:
- 与真实持仓**物理隔离**(独立表 + 独立 service,禁止导入真实 repo)
- 费用口径与实盘一致(复用 core/cost_engine),否则模拟结果没有参考价值
- 下单走真实行情价,而不是让用户手填价格(否则模拟即虚构)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.cost_engine import TradeFees, buy_fee, sell_fee
from app.core.logging import logger
from app.core.stock_code import normalize_code
from app.modules.paper_trading.repository import paper_trading_repo

LOT_SIZE = 100


class PaperTradingError(Exception):
    """模拟盘业务错误(API 层转 400)。"""


class InsufficientCash(PaperTradingError):
    pass


class InsufficientPosition(PaperTradingError):
    pass


def _dec(v) -> Decimal:
    return Decimal(str(v if v is not None else 0))


def _q(d: Decimal) -> str:
    """量化到分,返回字符串(与项目 Decimal 存字符串约定一致)。"""
    return str(d.quantize(Decimal("0.01")))


class PaperTradingService:
    """模拟盘交易服务。"""

    def __init__(self, fees: TradeFees | None = None) -> None:
        # 模拟盘必须计费(否则模拟收益虚高)
        self.fees = fees or TradeFees(enabled=True)

    # ---------- 账户 ----------

    async def ensure_default_account(self, initial_capital: str = "1000000.00") -> int:
        acc = await paper_trading_repo.get_first_account()
        if acc is not None:
            return acc.id
        return await paper_trading_repo.create_account("默认模拟账户", initial_capital)

    async def list_accounts(self) -> list[dict]:
        rows = await paper_trading_repo.list_accounts()
        return [
            {
                "id": r.id,
                "name": r.name,
                "initial_capital": r.initial_capital,
                "cash": r.cash,
                "realized_pnl": r.realized_pnl,
                "auto_follow": r.auto_follow,
            }
            for r in rows
        ]

    async def create_account(self, name: str, initial_capital: str) -> int:
        return await paper_trading_repo.create_account(name, initial_capital)

    async def list_orders(self, account_id: int, limit: int = 50) -> dict:
        rows = await paper_trading_repo.list_orders(account_id, limit)
        return {
            "items": [
                {
                    "id": r.id,
                    "stock_code": r.stock_code,
                    "stock_name": r.stock_name,
                    "action": r.action,
                    "shares": r.shares,
                    "price": r.price,
                    "fee": r.fee,
                    "trade_date": r.trade_date.isoformat(),
                    "origin": r.origin,
                    "note": r.note,
                }
                for r in rows
            ]
        }

    # ---------- 交易 ----------

    async def buy(
        self,
        account_id: int,
        stock_code: str,
        shares: int,
        price: float,
        origin: str = "manual",
        trade_date: date | None = None,
        note: str | None = None,
        stock_name: str | None = None,
    ) -> dict:
        code = normalize_code(stock_code) or stock_code
        shares = int(shares)
        if shares <= 0:
            raise PaperTradingError("股数必须为正")
        if shares % LOT_SIZE != 0:
            raise PaperTradingError(f"A 股必须按 {LOT_SIZE} 股整手买入")

        acc = await paper_trading_repo.get_account(account_id)
        if acc is None:
            raise PaperTradingError("账户不存在")

        px = _dec(price)
        amount = px * shares
        fee = buy_fee(shares, px, self.fees)
        total_cost = amount + fee

        cash = _dec(acc.cash)
        if total_cost > cash:
            raise InsufficientCash(
                f"现金不足:需 {total_cost:.2f},可用 {cash:.2f}"
            )

        pos = await paper_trading_repo.get_position(account_id, code)
        if pos is None:
            await self._insert_position(account_id, code, stock_name, shares, total_cost / shares, trade_date)
        else:
            old_shares = pos.shares
            new_shares = old_shares + shares
            old_cost = _dec(pos.avg_cost) * old_shares
            new_avg = (old_cost + total_cost) / new_shares
            await self._update_position(pos.id, new_shares, new_avg)

        await self._write_order(
            account_id, code, stock_name, "buy", shares, px, fee,
            trade_date or date.today(), origin, note,
        )
        await self._update_cash(account_id, cash - total_cost, fee)
        return {"ok": True, "action": "buy", "stock_code": code, "shares": shares, "fee": _q(fee)}

    async def sell(
        self,
        account_id: int,
        stock_code: str,
        shares: int,
        price: float,
        origin: str = "manual",
        trade_date: date | None = None,
        note: str | None = None,
    ) -> dict:
        code = normalize_code(stock_code) or stock_code
        shares = int(shares)
        if shares <= 0:
            raise PaperTradingError("股数必须为正")

        acc = await paper_trading_repo.get_account(account_id)
        if acc is None:
            raise PaperTradingError("账户不存在")
        pos = await paper_trading_repo.get_position(account_id, code)
        if pos is None:
            raise InsufficientPosition(f"无持仓: {code}")
        if shares > pos.shares:
            raise InsufficientPosition(f"持仓不足:持有 {pos.shares},卖出 {shares}")

        px = _dec(price)
        proceeds = px * shares
        fee = sell_fee(shares, px, self.fees)
        net = proceeds - fee

        cost_basis = _dec(pos.avg_cost) * shares
        realized = net - cost_basis

        remaining = pos.shares - shares
        if remaining == 0:
            await self._delete_position(pos.id)
        else:
            await self._update_position(pos.id, remaining, _dec(pos.avg_cost))

        await self._write_order(
            account_id, code, None, "sell", shares, px, fee,
            trade_date or date.today(), origin, note,
        )
        cash = _dec(acc.cash)
        await self._update_cash(
            account_id, cash + net, fee, extra_realized=realized
        )
        return {
            "ok": True, "action": "sell", "stock_code": code, "shares": shares,
            "fee": _q(fee), "realized_pnl": _q(realized),
        }

    # ---------- 查询 ----------

    async def get_summary(self, account_id: int) -> dict:
        acc = await paper_trading_repo.get_account(account_id)
        if acc is None:
            raise PaperTradingError("账户不存在")

        from app.services.quote_service import QuoteService

        positions = await paper_trading_repo.list_positions(account_id)
        market_value = Decimal("0")
        pos_view = []
        if positions:
            quotes = {}
            try:
                qs = await QuoteService().get_quotes([p.stock_code for p in positions])
                quotes = {q.code: float(q.current_price) for q in qs}
            except Exception as e:  # noqa: BLE001 — 行情失败不该让页面打不开
                logger.warning(f"[paper] 拉行情失败,按成本价估值: {e}")

            for p in positions:
                cur = quotes.get(p.stock_code) or float(p.avg_cost)
                mv = cur * p.shares
                market_value += mv
                cost = _dec(p.avg_cost) * p.shares
                pos_view.append(
                    {
                        "stock_code": p.stock_code,
                        "stock_name": p.stock_name,
                        "shares": p.shares,
                        "avg_cost": p.avg_cost,
                        "current_price": round(cur, 3),
                        "market_value": round(mv, 2),
                        "unrealized_pnl": round(mv - float(cost), 2),
                        "unrealized_pct": round((mv / float(cost) - 1) * 100, 2) if cost > 0 else 0.0,
                    }
                )

        cash = _dec(acc.cash)
        total = cash + market_value
        initial = _dec(acc.initial_capital)
        return {
            "account_id": account_id,
            "name": acc.name,
            "initial_capital": acc.initial_capital,
            "cash": _q(cash),
            "market_value": round(market_value, 2),
            "total_equity": round(total, 2),
            "total_return_pct": round((total / initial - 1) * 100, 2) if initial > 0 else 0.0,
            "realized_pnl": acc.realized_pnl,
            "positions": pos_view,
            "position_count": len(pos_view),
        }

    async def get_equity_curve(self, account_id: int) -> dict:
        rows = await paper_trading_repo.list_equity(account_id)
        if not rows:
            return {"dates": [], "equity": [], "metrics": {}}

        from app.services.backtest.metrics import compute_metrics

        dates = [r.snapshot_date.isoformat() for r in rows]
        equity = [float(r.total_equity) for r in rows]
        initial = float(rows[0].total_equity)
        m = compute_metrics(equity, initial_capital=initial).to_dict()
        return {"dates": dates, "equity": [round(e, 2) for e in equity], "metrics": m}

    async def snapshot_equity(self, account_id: int) -> dict:
        """给定时器调用:记录当日净值快照。"""
        summary = await self.get_summary(account_id)
        acc = await paper_trading_repo.get_account(account_id)
        await paper_trading_repo.upsert_equity(
            account_id,
            date.today(),
            str(summary["total_equity"]),
            summary["cash"],
            str(summary["market_value"]),
        )
        return summary

    # ---------- 内部 ----------

    async def _insert_position(self, account_id, code, stock_name, shares, avg_cost, trade_date):
        from datetime import datetime

        from app.db import async_session
        from app.models.orm import PaperPosition

        async with async_session() as s:
            s.add(
                PaperPosition(
                    account_id=account_id,
                    stock_code=code,
                    stock_name=stock_name,
                    shares=shares,
                    avg_cost=_q(_dec(avg_cost)),
                    opened_at=datetime.now(),
                )
            )
            await s.commit()

    async def _update_position(self, pos_id, shares, avg_cost):
        from datetime import datetime

        from app.db import async_session
        from app.models.orm import PaperPosition

        async with async_session() as s:
            row = await s.get(PaperPosition, pos_id)
            if row is None:
                return
            row.shares = shares
            row.avg_cost = _q(_dec(avg_cost))
            row.updated_at = datetime.now()
            await s.commit()

    async def _delete_position(self, pos_id):
        from app.db import async_session
        from app.models.orm import PaperPosition

        async with async_session() as s:
            row = await s.get(PaperPosition, pos_id)
            if row is not None:
                await s.delete(row)
                await s.commit()

    async def _write_order(self, account_id, code, name, action, shares, price, fee, trade_date, origin, note):
        from app.db import async_session
        from app.models.orm import PaperOrder

        async with async_session() as s:
            s.add(
                PaperOrder(
                    account_id=account_id,
                    stock_code=code,
                    stock_name=name,
                    action=action,
                    shares=shares,
                    price=_q(_dec(price)),
                    fee=_q(_dec(fee)),
                    trade_date=trade_date,
                    origin=origin,
                    note=note,
                )
            )
            await s.commit()

    async def _update_cash(self, account_id, new_cash, fee, extra_realized: Decimal | None = None):
        from datetime import datetime

        from app.db import async_session
        from app.models.orm import PaperAccount

        async with async_session() as s:
            acc = await s.get(PaperAccount, account_id)
            if acc is None:
                return
            acc.cash = _q(_dec(new_cash))
            acc.total_fees = _q(_dec(acc.total_fees) + _dec(fee))
            if extra_realized is not None:
                acc.realized_pnl = _q(_dec(acc.realized_pnl) + extra_realized)
            acc.updated_at = datetime.now()
            await s.commit()


paper_trading_service = PaperTradingService()

__all__ = ["PaperTradingService", "PaperTradingError", "InsufficientCash", "InsufficientPosition", "paper_trading_service"]
