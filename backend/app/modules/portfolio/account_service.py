"""投资账户用例层(阶段5)。

API 层不直连 repository(架构守卫强制),账户概览里的持仓聚合与
行情估值属于业务逻辑,因此收拢到这里。
"""
from __future__ import annotations

from decimal import Decimal

from app.core.logging import logger
from app.modules.portfolio.account_repository import account_repo


class AccountError(Exception):
    pass


class AccountService:
    """账户增删改查 + 概览聚合。"""

    async def list_with_summary(self) -> list[dict]:
        """账户列表 + 持仓数/成本/已实现盈亏概览。"""
        from app.modules.portfolio.service import get_all_positions

        rows = await account_repo.list_all()
        items = []
        for r in rows:
            try:
                positions = await get_all_positions(r.id)
            except Exception as e:  # noqa: BLE001 — 单账户概览失败不该让整个列表挂掉
                logger.warning(f"[account] 账户 {r.id} 持仓读取失败: {e}")
                positions = []
            items.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "kind": r.kind,
                    "broker": r.broker,
                    "note": r.note,
                    "is_default": r.is_default,
                    "position_count": len(positions),
                    "total_cost": round(sum(float(p.total_cost) for p in positions), 2),
                    "realized_pnl": round(sum(float(p.realized_pnl) for p in positions), 2),
                }
            )
        return items

    async def create(self, name: str, kind: str, broker: str | None, note: str | None) -> int:
        return await account_repo.create(name, kind, broker, note)

    async def rename(self, account_id: int, name: str) -> None:
        ok = await account_repo.rename(account_id, name)
        if not ok:
            raise AccountError("账户不存在,或默认账户不可重命名")

    async def delete(self, account_id: int) -> None:
        ok, msg = await account_repo.delete(account_id)
        if not ok:
            raise AccountError(msg or "删除失败")

    async def summary(self, account_id: int) -> dict:
        """单账户持仓汇总(未实现盈亏需实时行情)。"""
        from app.modules.portfolio.service import get_all_positions
        from app.services.quote_service import QuoteService

        acc = await account_repo.get(account_id)
        if acc is None:
            raise AccountError("账户不存在")

        positions = await get_all_positions(account_id)
        quotes: dict = {}
        if positions:
            try:
                qs = await QuoteService().get_quotes([p.stock_code for p in positions])
                quotes = {q.code: q for q in qs}
            except Exception as e:  # noqa: BLE001 — 行情失败退回按成本估值
                logger.warning(f"[account] 账户 {account_id} 行情获取失败,按成本估值: {e}")

        items = []
        market_value = 0.0
        for p in positions:
            cost = float(p.total_cost)
            q = quotes.get(p.stock_code)
            cur = float(q.current_price) if q else 0.0
            mv = cur * p.shares if cur > 0 else cost
            market_value += mv
            items.append(
                {
                    "stock_code": p.stock_code,
                    "stock_name": p.stock_name,
                    "shares": p.shares,
                    "total_cost": round(cost, 2),
                    "realized_pnl": p.realized_pnl,
                    "current_price": round(cur, 3),
                    "market_value": round(mv, 2),
                    "unrealized_pnl": round(mv - cost, 2),
                    "unrealized_pct": round((mv / cost - 1) * 100, 2) if cost > 0 else 0.0,
                }
            )

        total_cost = sum(float(p.total_cost) for p in positions)
        realized = sum(float(p.realized_pnl) for p in positions)
        return {
            "id": acc.id,
            "name": acc.name,
            "is_default": acc.is_default,
            "position_count": len(items),
            "total_cost": round(total_cost, 2),
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(market_value - total_cost, 2),
            "realized_pnl": round(realized, 2),
            "positions": items,
        }


    async def get_cash_available(self, account_id: int) -> Decimal | None:
        """账户可用资金(元)。None = 未填写(不是 0)。

        账户不存在 → 抛 AccountError(API 层转 404);
        账户存在但没填 → 返回 None(判定层据此降级,不编数字)。
        """
        acc = await account_repo.get(account_id)
        if acc is None:
            raise AccountError("账户不存在")
        return await account_repo.get_cash_available(account_id)

    async def set_cash_available(
        self, account_id: int, value: Decimal | None
    ) -> Decimal | None:
        """写账户可用资金。value=None = 清空(= 未填写)。返回落库后的值。"""
        ok = await account_repo.set_cash_available(account_id, value)
        if not ok:
            raise AccountError("账户不存在")
        return value


account_service = AccountService()

__all__ = ["AccountError", "AccountService", "account_service"]
