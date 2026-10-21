"""持仓主数据 service(v0.4.0 重构)

v0.4.0 设计哲学翻转:
- positions 表是主数据(股民真实持仓,手动录入 / 截图导入 / 流水同步)
- transactions 流水是事件记录(复盘用),自动同步持仓

一致性核心 recalc_position(stock_code):
  持仓 = 导入基准(delta) + 全部流水聚合
  其中 delta = positions 当前值 - 流水聚合当前值(导入/手动调整部分,运行时推导,不落库)

诊断服务对"单笔交易前状态"的判定仍用 aggregate_positions 纯函数(交易上下文,非持仓视图)。
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from sqlalchemy import select

from app.db import async_session
from app.models.orm import Position as PositionRow
from app.models.orm import Transaction


@dataclass
class Position:
    """单只股票的持仓汇总(兼容旧接口:avg_cost / total_cost / realized_pnl)"""
    stock_code: str
    stock_name: Optional[str] = None
    shares: int = 0
    total_cost: Decimal = field(default_factory=lambda: Decimal("0"))
    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def avg_cost(self) -> Decimal:
        """加权平均成本"""
        if self.shares <= 0:
            return Decimal("0")
        # 保留 3 位小数(与中国券商对齐)
        return (self.total_cost / self.shares).quantize(Decimal("0.001"))

    @property
    def total_cost_fmt(self) -> str:
        return format(self.total_cost.quantize(Decimal("0.01")), ".2f")


@dataclass
class DeltaBaseline:
    """导入基准:持仓主数据相对流水聚合的差额(不落库,运行时推导)

    capture_delta(变更前) → 变更流水 → recalc_position(变更后)
    """
    shares: int = 0
    cost: Decimal = field(default_factory=lambda: Decimal("0"))
    pnl: Decimal = field(default_factory=lambda: Decimal("0"))


# ============================================================
# 纯函数:流水聚合(v0.4.0 后仅用于交易前状态判定 / 迁移 backfill)
# ============================================================

def aggregate_positions(
    transactions: list[Transaction],
    strict: bool = True,
    keep_zero: bool = True,
) -> list[Position]:
    """纯函数:从流水列表聚合持仓

    按交易日期顺序处理(同一天内按 id 顺序,确保可复现)。

    strict: 默认 True 校验 sell <= 当前持仓(纯流水场景保护);
      False 跳过校验(用于 recalc_position 的 delta+flow 模式:row 内的
      导入基准可能允许 sell 超过纯流水聚合)。
    keep_zero: 默认 True 过滤掉 shares <= 0 的股票(纯流水场景只关心仍有持仓);
      False 不过滤(用于 recalc_position:flow 可能为负,需要返回供 delta+flow 计算)。
    """
    # 按 stock_code 分组
    by_code: dict[str, Position] = {}
    # 全局排序:trade_date 升序,id 升序
    sorted_tx = sorted(transactions, key=lambda t: (t.trade_date, t.id))

    for tx in sorted_tx:
        if tx.stock_code not in by_code:
            by_code[tx.stock_code] = Position(
                stock_code=tx.stock_code,
                stock_name=tx.stock_name,
            )
        pos = by_code[tx.stock_code]
        # 更新名称(以最新一条为准)
        if tx.stock_name:
            pos.stock_name = tx.stock_name

        price = Decimal(tx.price)
        if tx.action == "buy":
            pos.shares += tx.shares
            pos.total_cost += price * tx.shares
        elif tx.action == "sell":
            if strict and tx.shares > pos.shares:
                # 卖出超过持仓(理论上 Pydantic 已校验,但双保险)
                raise ValueError(
                    f"卖出 {tx.shares} 股超过持仓 {pos.shares} 股 "
                    f"(stock={tx.stock_code}, tx_id={tx.id})"
                )
            realized_per_share = price - pos.avg_cost  # 用卖出前的成本
            pos.realized_pnl += realized_per_share * tx.shares
            pos.total_cost -= pos.avg_cost * tx.shares
            pos.shares -= tx.shares

    if keep_zero:
        # 只返回仍有持仓的股票(shares > 0)
        return [p for p in by_code.values() if p.shares > 0]
    return list(by_code.values())


# ============================================================
# 持仓表读写 + recalc_position(v0.4.0 主数据路径)
# ============================================================

def _row_to_position(row: PositionRow) -> Position:
    return Position(
        stock_code=row.stock_code,
        stock_name=row.stock_name,
        shares=row.shares,
        total_cost=Decimal(row.total_cost),
        realized_pnl=Decimal(row.realized_pnl),
    )


async def _load_flow(session, code: str, account_id: int | None = None) -> list[Transaction]:
    """加载某股票全部流水(已排序),限定账户"""
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    stmt = (
        select(Transaction)
        .where(Transaction.stock_code == code, Transaction.account_id == acct)
        .order_by(Transaction.trade_date, Transaction.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def capture_delta(stock_code: str) -> "DeltaBaseline":
    """变更前捕获导入基准(流水变动前调用)

    delta = 当前持仓 - 当前流水聚合(导入/手动调整部分)
    - row 不存在(纯流水持仓)→ 基准为 0
    调用方必须在流水变更前调用,变更后传给 recalc_position 才能正确同步。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    async with async_session() as session:
        row = (
            await session.execute(
                select(PositionRow).where(
                    PositionRow.account_id == DEFAULT_ACCOUNT_ID,
                    PositionRow.stock_code == stock_code,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return DeltaBaseline(shares=0, cost=Decimal("0"), pnl=Decimal("0"))
        flow_tx = await _load_flow(session, stock_code)
        # 与 recalc_position 一致:delta+flow 模式允许 sell 超过纯流水聚合
        # (持仓主数据 + 仅卖/少数流水的场景),strict=False 避免抛错
        flow = next(
            (
                p
                for p in aggregate_positions(
                    flow_tx, strict=False, keep_zero=False
                )
                if p.stock_code == stock_code
            ),
            None,
        )
        return DeltaBaseline(
            shares=row.shares - (flow.shares if flow else 0),
            cost=Decimal(row.total_cost) - (flow.total_cost if flow else Decimal("0")),
            pnl=Decimal(row.realized_pnl)
            - (flow.realized_pnl if flow else Decimal("0")),
        )


async def recalc_position(stock_code: str, delta: Optional["DeltaBaseline"] = None) -> None:
    """流水变动后重算该股票持仓(一致性核心)

    持仓 = 导入基准(delta) + 全部流水聚合
    - delta 由调用方在流水变更前 capture_delta 捕获(不落库,运行时推导)
    - 重放全部流水后:新持仓 = delta + 新流水聚合
    - 股数为 0 且成本为 0 → 删除持仓行

    阶段5:全链路限定默认账户(多账户下需按账户分别重算,见下方 TODO 说明)。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = DEFAULT_ACCOUNT_ID
    if delta is None:
        delta = await capture_delta(stock_code)
    async with async_session() as session:
        row = (
            await session.execute(
                select(PositionRow).where(
                    PositionRow.account_id == acct,
                    PositionRow.stock_code == stock_code,
                )
            )
        ).scalar_one_or_none()

        flow_tx = await _load_flow(session, stock_code, acct)
        # strict=False / keep_zero=False:delta+flow 模式下 row 内的导入基准可能
        # 允许 sell > flow 聚合,且 flow 本身可能为负(清仓后),需要返回所有股票
        flow = next(
            (p for p in aggregate_positions(flow_tx, strict=False, keep_zero=False) if p.stock_code == stock_code),
            None,
        )

        new_shares = delta.shares + (flow.shares if flow else 0)
        new_cost = delta.cost + (flow.total_cost if flow else Decimal("0"))
        new_pnl = delta.pnl + (flow.realized_pnl if flow else Decimal("0"))

        if new_shares <= 0:
            # 持仓被卖光 → 删除持仓行(成本归零)
            if row is not None:
                await session.delete(row)
            await session.commit()
            return

        # 防御:股数 > 0 但 cost/pnl 不一致 → 量化处理
        new_cost = max(Decimal("0"), new_cost)
        new_pnl = max(Decimal("0"), new_pnl)

        if row is None:
            row = PositionRow(
                stock_code=stock_code,
                stock_name=flow.stock_name if flow else None,
                shares=new_shares,
                total_cost=str(new_cost.quantize(Decimal("0.01"))),
                realized_pnl=str(new_pnl.quantize(Decimal("0.01"))),
            )
            session.add(row)
        else:
            row.shares = new_shares
            row.total_cost = str(new_cost.quantize(Decimal("0.01")))
            row.realized_pnl = str(new_pnl.quantize(Decimal("0.01")))
            if flow and flow.stock_name:
                row.stock_name = flow.stock_name
        await session.commit()


# ============================================================
# 主数据读写接口(对外)
# ============================================================

async def get_all_positions(account_id: int | None = None) -> list[Position]:
    """读 positions 表(主数据)。account_id 省略 = 只看默认账户。"""
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        rows = list(
            (
                await session.execute(
                    select(PositionRow).where(PositionRow.account_id == acct)
                )
            )
            .scalars()
            .all()
        )
    return [_row_to_position(r) for r in rows]


async def get_position(stock_code: str, account_id: int | None = None) -> Optional[Position]:
    """读 positions 表单条。account_id 省略 = 只看默认账户。"""
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        row = (
            await session.execute(
                select(PositionRow).where(
                    PositionRow.account_id == acct,
                    PositionRow.stock_code == stock_code,
                )
            )
        ).scalar_one_or_none()
    return _row_to_position(row) if row else None


async def upsert_position(
    stock_code: str,
    shares: int,
    cost_price: Decimal,
    stock_name: str | None = None,
    account_id: int | None = None,
) -> Position:
    """手动录入 / 截图导入:覆盖式写入持仓(以用户提供为准,不算 delta)

    delta 推导规则:新值 = 导入值 + (流水聚合 - 旧流水聚合)。流水不变时,
    新持仓 = 导入值,等价于覆盖;流水变动后导入值作为基准保留。

    account_id 省略时落到默认账户(阶段5),保持存量调用方行为不变。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        row = (
            await session.execute(
                select(PositionRow).where(
                    PositionRow.account_id == acct,
                    PositionRow.stock_code == stock_code,
                )
            )
        ).scalar_one_or_none()
        total_cost = (Decimal(str(cost_price)) * int(shares)).quantize(Decimal("0.01"))

        # 当前流水聚合值(用于计算 delta 基准)
        #
        # strict=False / keep_zero=False:与 capture_delta / recalc_position 同一口径。
        # 导入基准场景下,流水的**第一条可能就是「卖出」**(底仓不在流水里),
        # strict=True 会抛「卖出 N 股超过持仓 0 股」→ POST /api/positions 直接 500。
        # keep_zero=False:卖出后 flow.shares 会变成 0 或负数,keep_zero=True 会把它
        # 过滤掉,导致已实现盈亏被当成 0 写回(把历史已实现盈亏抹掉)。
        flow_tx = await _load_flow(session, stock_code, acct)
        flow_pos = aggregate_positions(flow_tx, strict=False, keep_zero=False)
        flow = next((p for p in flow_pos if p.stock_code == stock_code), None)
        flow_pnl = flow.realized_pnl if flow else Decimal("0")

        if row is None:
            row = PositionRow(
                account_id=acct,
                stock_code=stock_code,
                stock_name=stock_name,
                shares=int(shares),
                total_cost=str(total_cost),
                # 已实现盈亏与覆盖分支同一口径:流水部分保留(导入不覆盖历史已实现)。
                # 两个分支必须一致,否则「先有卖出流水、后导入持仓」会把这笔历史盈亏抹成 0。
                realized_pnl=str(flow_pnl.quantize(Decimal("0.01"))),
            )
            session.add(row)
        else:
            # 用户导入值 = 新的"持仓 - 流水"基准
            row.shares = int(shares)
            row.total_cost = str(total_cost)
            # 已实现盈亏:流水部分保留(导入不覆盖历史已实现)
            row.realized_pnl = str(flow_pnl.quantize(Decimal("0.01")))
            if stock_name:
                row.stock_name = stock_name
        await session.commit()
        await session.refresh(row)
        return _row_to_position(row)


async def delete_position(stock_code: str, account_id: int | None = None) -> bool:
    """删除持仓(流水保留,仅删主数据)"""
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        row = (
            await session.execute(
                select(PositionRow).where(
                    PositionRow.account_id == acct,
                    PositionRow.stock_code == stock_code,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True


__all__ = [
    "Position",
    "DeltaBaseline",
    "aggregate_positions",
    "recalc_position",
    "capture_delta",
    "get_all_positions",
    "get_position",
    "upsert_position",
    "delete_position",
]
