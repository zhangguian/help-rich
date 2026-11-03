"""持仓主数据 service(v0.5.0 事件溯源重构 / v0.11 摊薄成本口径)

v0.5.0(方案B·每笔流水存持仓快照)设计:
- positions 表 = 基准(base_*) + 当前状态(shares / total_cost / realized_pnl)
- transactions 每笔带自己的 after 快照(shares_after / total_cost_after / realized_after)

真相公式:
    当前持仓 = 基准(base_*) + 其后所有 id > base_tx_id 的流水
               按 (trade_date, trade_time, id) 顺序逐笔应用
               (时间点未知(NULL)排在同日有时间者之前 → 存量流水顺序不变)

任何一笔流水的增 / 删 / 改 → 从基准全量重放链尾 → 重写所有受影响快照 + 持仓行。
因为基准是「导入那一刻的真实持仓」,历史流水不会被重复计算。

═══════════════════════════════════════════════════════════════════════
v0.11 成本口径:改为**券商摊薄口径**(净投入追踪)
═══════════════════════════════════════════════════════════════════════

券商持仓页显示的「成本价」= **摊薄成本** = 累计净投入 ÷ 当前持股数:

    摊薄成本 = (累计买入金额 − 累计卖出金额) ÷ 持股数

本模块的 `total_cost` 从 v0.11 起就是这个「净投入」(摊薄总额):
- 买入:净投入 += 成交价 × 股数
- 卖出:净投入 −= 成交价 × 股数(按成交价回收,不是按成本冲减)
- 卖出确认的已实现 = (成交价 − 卖出前摊薄成本) × 股数

⚠️ v0.10 及以前用的是「加权平均剩余成本」(卖出按均价等比例冲减),
展示时又用 `(total_cost − realized_pnl) ÷ shares` 反推摊薄成本。
当基准里带了券商给的**累计已实现盈亏**(base_realized_pnl ≠ 0)时,
这个反推会把已实现**二次扣减** —— 正是「成本和券商对不上」的根因:
    豫能控股:基准净投入 9346.80、已实现 1293.00
    → 旧口径摊薄成本 = (6231.20 + 50.60) ÷ 400 = 15.704(券商 18.940)
    → 新口径摊薄成本 = 7574.80 ÷ 400 = 18.937 ✓
直接追踪净投入,摊薄成本与券商**恒等**,不再靠反推。

纯函数职责划分(backend-arch §5.1):
- `apply_transaction` / `replay_chain`:纯计算,零 IO
- `recalc_position` / `upsert_position`:落库路径

v0.4.0 旧模型(已作废):
    持仓 = delta(持仓行现值 − 从 0 开始的流水聚合) + 全部流水聚合
    → 导入快照已含历史流水效果,流水又在其上重放一遍 = 双算
    → 华天科技 002185 卖出 100 股时少冲成本 1058.72 元,均价从 16.959 掉到 15.900
"""
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select

from app.db import async_session
from app.models.orm import Position as PositionRow
from app.models.orm import Transaction


@dataclass
class Position:
    """单只股票的持仓汇总(兼容旧接口:avg_cost / total_cost / realized_pnl)

    v0.11:`total_cost` = **摊薄总额(净投入)**,`avg_cost` = 摊薄成本价
    (= 券商持仓页显示的「成本价」)。语义见模块文档。
    """

    stock_code: str
    stock_name: str | None = None
    shares: int = 0
    # 摊薄总额(净投入)= 累计买入金额 − 累计卖出金额
    total_cost: Decimal = field(default_factory=lambda: Decimal("0"))
    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    # 持仓行落库时间(v0.10:决策层「持有天数」的兜底起点口径)
    #
    # ⚠️ 这**不是**真实建仓日:截图导入的票,created_at = 快照导入日。
    # 精确起点见 `get_position_start()`(优先取最早流水日期)。
    created_at: datetime | None = None

    @property
    def avg_cost(self) -> Decimal:
        """摊薄成本价(券商口径:净投入 ÷ 持股数)"""
        if self.shares <= 0:
            return Decimal("0")
        # 保留 3 位小数(与中国券商对齐)
        return (self.total_cost / self.shares).quantize(Decimal("0.001"))

    @property
    def total_cost_fmt(self) -> str:
        return format(self.total_cost.quantize(Decimal("0.01")), ".2f")


# ============================================================
# 事件溯源:链状态 + 流水规格 + 纯重放
# ============================================================

@dataclass(frozen=True)
class ChainState:
    """链上某一点(或基准)的持仓状态

    v0.11:`total_cost` = 摊薄总额(净投入),不是加权平均剩余成本。
    """

    shares: int = 0
    # 摊薄总额(净投入)= 累计买入金额 − 累计卖出金额
    total_cost: Decimal = field(default_factory=lambda: Decimal("0"))
    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))

    @property
    def avg_cost(self) -> Decimal:
        """未量化的摊薄成本价(重放内部用,避免 3 位量化累计误差)"""
        if self.shares <= 0:
            return Decimal("0")
        return self.total_cost / self.shares


@dataclass(frozen=True)
class TxSpec:
    """流水规格(纯数据,便于试算与重放)"""
    id: int
    trade_date: date
    action: str
    shares: int
    price: Decimal
    stock_name: str | None = None
    # 时间节点(HH:MM:SS);None = 未知(存量流水 / 截图导入 / 用户留空)
    trade_time: time | None = None


def chain_sort_key(
    trade_date: date,
    trade_time: time | None,
    tx_id: int,
) -> tuple:
    """链全序键:(交易日, 时间点, id)

    ⚠️ 这是成本链的**唯一**排序口径 —— 链重放 / 试算 / 校验 / 「交易前持仓」
    四处必须共用它,否则会出现「校验顺序 ≠ 重放顺序」的错位(历史上踩过)。

    时间点未知(None)排在同日**有时间的流水之前**:
    - 存量流水全是 NULL → 相对顺序与引入时间节点前(按 id)完全一致,
      任何历史持仓成本都不受影响;
    - 同一用户录的「09:35 卖」一定排在「14:00 买」之前 —— 盘中次序可表达。
    """
    return (trade_date, trade_time or time.min, tx_id)


def _spec_sort_key(spec: TxSpec) -> tuple:
    return chain_sort_key(spec.trade_date, spec.trade_time, spec.id)


class PositionChainError(ValueError):
    """链重放失败(如卖出超过当时持仓)—— 由 API 层转 422"""


def apply_transaction(
    state: ChainState,
    action: str,
    shares: int,
    price: Decimal,
) -> ChainState:
    """纯函数:摊薄口径(净投入追踪)应用一笔交易

    买:shares += n;净投入 += price × n
    卖:已实现盈亏 += (price − 摊薄成本) × n;净投入 −= price × n(按成交价回收)

    ⚠️ 摊薄成本 = 净投入 ÷ 股数,**卖出后会变**(低于成本卖 → 摊薄成本抬高),
    这正是券商「摊薄成本价」的行为。均价用**未量化**的 net_invested / shares ——
    量化到 3 位再回乘会累计误差。
    """
    if shares <= 0:
        raise PositionChainError(f"交易股数必须 > 0,实际 {shares}")
    if price <= 0:
        raise PositionChainError(f"交易价格必须 > 0,实际 {price}")

    if action == "buy":
        return ChainState(
            shares=state.shares + shares,
            total_cost=state.total_cost + price * shares,
            realized_pnl=state.realized_pnl,
        )

    if action != "sell":
        raise PositionChainError(f"未知交易方向: {action!r}")

    if state.shares <= 0:
        raise PositionChainError(
            f"卖出 {shares} 股时无持仓(基准/前序流水为 0 股)"
        )
    if shares > state.shares:
        raise PositionChainError(
            f"卖出 {shares} 股超过当时持仓 {state.shares} 股"
        )

    avg = state.avg_cost
    realized = (price - avg) * shares
    new_shares = state.shares - shares
    return ChainState(
        shares=new_shares,
        # 按成交价回收净投入(不是按成本等比例冲减)→ 摊薄成本随卖出价变化
        total_cost=state.total_cost - price * shares,
        realized_pnl=state.realized_pnl + realized,
    )


def replay_chain(
    base: ChainState,
    specs: list[TxSpec],
) -> tuple[ChainState, list[tuple[TxSpec, ChainState]]]:
    """纯函数:从基准重放一串流水

    Returns:
        (最终状态, [(流水, 应用完它之后的状态), ...])

    Raises:
        PositionChainError: 卖出超过当时持仓
    """
    state = base
    snapshots: list[tuple[TxSpec, ChainState]] = []
    for spec in specs:
        state = apply_transaction(state, spec.action, spec.shares, spec.price)
        snapshots.append((spec, state))
    return state, snapshots


# ============================================================
# 纯函数:流水聚合(v0.4.0 遗留,仅供窗口化复盘 replay_service 使用)
# ============================================================

def aggregate_positions(
    transactions: list[Transaction],
    strict: bool = True,
    keep_zero: bool = True,
) -> list[Position]:
    """纯函数:从流水列表**从 0 开始**聚合持仓

    ⚠️ 这不是持仓真相(持仓真相 = 基准 + 链尾重放,见 recalc_position)。
    仅用于「窗口化复盘」这类本来就该从 0 起算的场景。

    strict: 默认 True 校验 sell <= 当前持仓(纯流水场景保护);
      False 跳过校验(允许 sell 超过聚合结果)。
    keep_zero: 默认 True 过滤掉 shares <= 0 的股票;
      False 不过滤(需要返回供 delta 计算)。
    """
    by_code: dict[str, Position] = {}
    sorted_tx = sorted(
        transactions,
        key=lambda t: chain_sort_key(t.trade_date, getattr(t, "trade_time", None), t.id),
    )

    for tx in sorted_tx:
        if tx.stock_code not in by_code:
            by_code[tx.stock_code] = Position(
                stock_code=tx.stock_code,
                stock_name=tx.stock_name,
            )
        pos = by_code[tx.stock_code]
        if tx.stock_name:
            pos.stock_name = tx.stock_name

        price = Decimal(tx.price)
        if tx.action == "buy":
            pos.shares += tx.shares
            pos.total_cost += price * tx.shares
        elif tx.action == "sell":
            if strict and tx.shares > pos.shares:
                raise ValueError(
                    f"卖出 {tx.shares} 股超过持仓 {pos.shares} 股 "
                    f"(stock={tx.stock_code}, tx_id={tx.id})"
                )
            # ⚠️ 用**未量化**的摊薄成本算已实现(与 ChainState.avg_cost 同口径),
            # 量化到 3 位再回乘会累计误差。
            realized_per_share = price - (pos.total_cost / pos.shares)
            pos.realized_pnl += realized_per_share * tx.shares
            # 摊薄口径:按成交价回收净投入
            pos.total_cost -= price * tx.shares
            pos.shares -= tx.shares

    if keep_zero:
        return [p for p in by_code.values() if p.shares > 0]
    return list(by_code.values())


def _lenient_flow_realized(txs: list[Transaction]) -> Decimal:
    """从 0 起算流水的已实现盈亏(宽松口径:允许卖出超过聚合)

    仅用于「用户没给已实现盈亏、且该票没有持仓行」时的兜底。
    """
    state = ChainState()
    for tx in sorted(
        txs,
        key=lambda t: chain_sort_key(
            t.trade_date, getattr(t, "trade_time", None), t.id
        ),
    ):
        price = Decimal(tx.price)
        if tx.action == "buy":
            state = ChainState(
                state.shares + tx.shares,
                state.total_cost + price * tx.shares,
                state.realized_pnl,
            )
        else:
            avg = state.avg_cost
            state = ChainState(
                state.shares - tx.shares,
                # 摊薄口径:按成交价回收净投入
                state.total_cost - price * tx.shares,
                state.realized_pnl + (price - avg) * tx.shares,
            )
    return state.realized_pnl


# ============================================================
# 持仓表读写 + 链重放(v0.5.0 主数据路径)
# ============================================================

def _row_to_position(row: PositionRow) -> Position:
    return Position(
        stock_code=row.stock_code,
        stock_name=row.stock_name,
        shares=row.shares,
        total_cost=Decimal(row.total_cost),
        realized_pnl=Decimal(row.realized_pnl),
        created_at=row.created_at,
    )


def _spec_of(tx: Transaction) -> TxSpec:
    return TxSpec(
        id=tx.id,
        trade_date=tx.trade_date,
        action=tx.action,
        shares=tx.shares,
        price=Decimal(tx.price),
        stock_name=tx.stock_name,
        trade_time=getattr(tx, "trade_time", None),
    )


async def _load_chain(
    session,
    code: str,
    account_id: int,
) -> tuple[PositionRow | None, ChainState, list[TxSpec], list[Transaction]]:
    """加载某股票的基准 + 链尾流水 + 全部流水行

    Returns:
        (持仓行 or None, 基准状态, 链尾规格(已按 (trade_date, id) 排序), 全部流水行)
    """
    row = (
        await session.execute(
            select(PositionRow).where(
                PositionRow.account_id == account_id,
                PositionRow.stock_code == code,
            )
        )
    ).scalar_one_or_none()

    tx_rows = list(
        (
            await session.execute(
                select(Transaction)
                .where(
                    Transaction.account_id == account_id,
                    Transaction.stock_code == code,
                )
                .order_by(Transaction.trade_date, Transaction.id)
            )
        )
        .scalars()
        .all()
    )
    # 链的权威顺序 = 全序键(交易日, 时间点, id);SQL 的 order_by 只是预排序,
    # 真正的口径在 Python 侧统一(链重放 / 校验 / 交易前持仓共用同一个 key)。
    tx_rows.sort(key=lambda t: _spec_sort_key(_spec_of(t)))

    if row is None:
        base = ChainState()
        base_tx_id = 0
    else:
        base = ChainState(
            shares=row.base_shares,
            total_cost=Decimal(row.base_total_cost),
            realized_pnl=Decimal(row.base_realized_pnl),
        )
        base_tx_id = row.base_tx_id

    chain = [_spec_of(t) for t in tx_rows if t.id > base_tx_id]
    return row, base, chain, tx_rows


def _write_snapshots(tx_rows: list[Transaction], snaps: list[tuple[TxSpec, ChainState]]) -> None:
    """把重放结果写回每笔流水的 after 快照(不在链里的清空)"""
    by_id = {spec.id: state for spec, state in snaps}
    for tx in tx_rows:
        state = by_id.get(tx.id)
        if state is None:
            tx.shares_after = None
            tx.total_cost_after = None
            tx.realized_after = None
        else:
            tx.shares_after = state.shares
            tx.total_cost_after = str(state.total_cost.quantize(Decimal("0.01")))
            tx.realized_after = str(state.realized_pnl.quantize(Decimal("0.01")))


def _replay_chain_into_row(
    base: ChainState,
    base_tx_id: int,
    tx_rows: list[Transaction],
) -> ChainState:
    """把基准之上的活链重放到基准上,并把每笔的 after 快照写回

    - 链 = id > base_tx_id 的流水(按 (trade_date, id) 排序,取自 tx_rows 的原顺序)
    - 不在链里的流水(id <= base_tx_id)= 已被基准吸收 → 快照清空
    """
    chain = [_spec_of(t) for t in tx_rows if t.id > base_tx_id]
    final, snaps = replay_chain(base, chain)
    _write_snapshots(tx_rows, snaps)
    return final


async def recalc_position(
    stock_code: str,
    account_id: int | None = None,
) -> Position | None:
    """流水变动后重算该股票持仓(一致性核心)

    流程:基准 + 链尾全量重放 → 重写每笔快照 → 更新持仓行。

    - 基准来自 positions.base_*(导入/手动录入那一刻的真实持仓)
    - 链尾 = id > base_tx_id 的流水,按 (trade_date, id) 排序
    - 基准吸收的流水(id <= base_tx_id)不参与重放,快照置空
    - 清仓(shares <= 0)**保留持仓行**(shares=0),已实现盈亏不丢

    Raises:
        PositionChainError: 链重放失败(如卖出超过当时持仓)
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        row, base, chain, tx_rows = await _load_chain(session, stock_code, acct)
        base_tx_id = row.base_tx_id if row is not None else 0

        final = _replay_chain_into_row(base, base_tx_id, tx_rows)

        total_cost = max(Decimal("0"), final.total_cost)
        realized = final.realized_pnl  # 已实现盈亏允许为负,不做 max(0, …)

        latest_name = next(
            (t.stock_name for t in reversed(tx_rows) if t.stock_name), None
        )

        if row is None:
            if not chain:
                # 无基准无流水 → 没有持仓可言
                await session.commit()
                return None
            row = PositionRow(
                account_id=acct,
                stock_code=stock_code,
                stock_name=latest_name,
                shares=final.shares,
                total_cost=str(total_cost.quantize(Decimal("0.01"))),
                realized_pnl=str(realized.quantize(Decimal("0.01"))),
                base_shares=base.shares,
                base_total_cost=str(base.total_cost.quantize(Decimal("0.01"))),
                base_realized_pnl=str(base.realized_pnl.quantize(Decimal("0.01"))),
                base_tx_id=0,
            )
            session.add(row)
        else:
            row.shares = final.shares
            row.total_cost = str(total_cost.quantize(Decimal("0.01")))
            row.realized_pnl = str(realized.quantize(Decimal("0.01")))
            if latest_name:
                row.stock_name = latest_name

        await session.commit()
        await session.refresh(row)
        return _row_to_position(row)


async def upsert_position(
    stock_code: str,
    shares: int,
    cost_price: Decimal,
    stock_name: str | None = None,
    account_id: int | None = None,
    realized_pnl: Decimal | None = None,
    base_date: date | None = None,
) -> Position:
    """手动录入 / 截图导入:**重置基准**(以用户提供为准)

    语义(v0.5.0):
    - base_* = 用户提供的股数 / 每股成本价 / 已实现盈亏(缺省沿用当前累计)
    - base_tx_id = 基准已吸收的流水 id 上界
    - 被吸收的流水不再参与重放 → 历史流水不会被重复计算(旧双算 bug 的根治点)

    v0.11 摊薄口径:
    - `cost_price` = 券商持仓页的**摊薄成本价** → base_total_cost = 摊薄总额(净投入)
    - 基准的已实现盈亏(base_realized_pnl)**独立**存放,不从摊薄总额里扣
      → 录入的摊薄成本价就是展示的摊薄成本价,不会被二次扣减

    base_date(可选)= **这份持仓快照是哪一天的**:
    - 给了 → 只吸收 trade_date <= base_date 的流水(该快照里已经包含的效果),
            base_date 之后的流水**留在链里继续生效**。
            典型场景:券商 10-21 快照 + App 10-22/10-23 又记了两笔 → 锚到 10-21,
            那两笔仍然是「活链」(可改可删、每笔带 after 快照)。
    - 不给 → 吸收该股票现有全部流水(= 快照就是此刻的真实持仓)。

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

        tx_rows = list(
            (
                await session.execute(
                    select(Transaction).where(
                        Transaction.account_id == acct,
                        Transaction.stock_code == stock_code,
                    )
                )
            )
            .scalars()
            .all()
        )

        if base_date is not None:
            # 只吸收基准日期(含)之前的流水
            absorbed = [t for t in tx_rows if t.trade_date <= base_date]
            max_tx_id = max((t.id for t in absorbed), default=0)
        else:
            max_tx_id = max((t.id for t in tx_rows), default=0)

        total_cost = (Decimal(str(cost_price)) * int(shares)).quantize(Decimal("0.01"))

        # 已实现盈亏:用户显式给 > 沿用当前累计(有行用行值,无行用流水口径)
        if realized_pnl is not None:
            base_pnl = Decimal(str(realized_pnl)).quantize(Decimal("0.01"))
        elif row is not None:
            base_pnl = Decimal(row.realized_pnl)
        else:
            base_pnl = _lenient_flow_realized(tx_rows).quantize(Decimal("0.01"))

        if row is None:
            row = PositionRow(
                account_id=acct,
                stock_code=stock_code,
                stock_name=stock_name,
                shares=int(shares),
                total_cost=str(total_cost),
                realized_pnl=str(base_pnl),
                base_shares=int(shares),
                base_total_cost=str(total_cost),
                base_realized_pnl=str(base_pnl),
                base_tx_id=max_tx_id,
            )
            session.add(row)
        else:
            # 重置基准
            row.shares = int(shares)
            row.total_cost = str(total_cost)
            row.realized_pnl = str(base_pnl)
            row.base_shares = int(shares)
            row.base_total_cost = str(total_cost)
            row.base_realized_pnl = str(base_pnl)
            row.base_tx_id = max_tx_id
            if stock_name:
                row.stock_name = stock_name

        # 基准之上的活链(base_tx_id 之后的流水)必须重放到新基准上,
        # 否则「锚到历史快照」会把基准之后的交易效果一起抹掉。
        final = _replay_chain_into_row(
            ChainState(int(shares), total_cost, base_pnl),
            max_tx_id,
            tx_rows,
        )
        row.shares = final.shares
        row.total_cost = str(max(Decimal("0"), final.total_cost).quantize(Decimal("0.01")))
        row.realized_pnl = str(final.realized_pnl.quantize(Decimal("0.01")))

        await session.commit()
        await session.refresh(row)
        return _row_to_position(row)


async def load_chain_context(
    stock_code: str,
    account_id: int | None = None,
) -> tuple[ChainState, list[TxSpec], list[Transaction], int]:
    """某只票的「基准 + 活链 + 全部流水」公开入口。

    返回:
        (基准状态, 活链规格(id > base_tx_id, 已按链全序排序), 全部流水行, 基准吸收上界)

    活链规格与全部流水行同序 —— 做T历史等「逐笔成本」分析按这个顺序走。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        row, base, chain, tx_rows = await _load_chain(session, stock_code, acct)
    return base, chain, tx_rows, (row.base_tx_id if row is not None else 0)


async def get_all_positions(
    account_id: int | None = None,
    include_closed: bool = False,
) -> list[Position]:
    """读 positions 表(主数据)。account_id 省略 = 只看默认账户。

    include_closed=False(默认):只返回仍有持仓的股票(shares > 0)——
    与 v0.4.0「清仓即删行」的对外表现一致(v0.5.0 改为保留行以留存已实现盈亏)。
    """
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
    out = [_row_to_position(r) for r in rows]
    if not include_closed:
        out = [p for p in out if p.shares > 0]
    return out


async def get_position(
    stock_code: str,
    account_id: int | None = None,
    include_closed: bool = False,
) -> Position | None:
    """读 positions 表单条。account_id 省略 = 只看默认账户。

    include_closed=False(默认):已清仓(shares <= 0)返回 None —— 与旧行为一致。
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
    if row is None:
        return None
    if not include_closed and row.shares <= 0:
        return None
    return _row_to_position(row)


async def position_before_trade(
    stock_code: str,
    tx_id: int,
    account_id: int | None = None,
) -> Position | None:
    """目标交易**之前**该股票的持仓(基准 + 链尾前缀重放)

    给诊断服务用:判断「这笔交易之前的仓位/成本」,必须走链重放而不是
    「从 0 开始聚合全部流水」(旧 aggregate_positions 会漏掉导入基准)。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        _row, base, chain, tx_rows = await _load_chain(session, stock_code, acct)
        target = next((t for t in tx_rows if t.id == tx_id), None)
        if target is None:
            return None
        # 前缀 = 严格排在目标之前的那些笔(同一套全序键,不能各用各的)
        target_key = chain_sort_key(
            target.trade_date, getattr(target, "trade_time", None), target.id
        )
        prefix = [spec for spec in chain if _spec_sort_key(spec) < target_key]
        state, _ = replay_chain(base, prefix)
        name = next(
            (t.stock_name for t in reversed(tx_rows) if t.stock_name), None
        )

    if state.shares <= 0:
        return None
    return Position(
        stock_code=stock_code,
        stock_name=name,
        shares=state.shares,
        total_cost=state.total_cost,
        realized_pnl=state.realized_pnl,
    )


async def shares_available_at(
    stock_code: str,
    trade_date: date,
    account_id: int | None = None,
) -> int:
    """在给定交易日可卖出的股数(基准 + 该日及之前的链尾重放)

    新流水 id 恒大于既有 id → 同日排序它排最后,所以「该日及之前」的链尾
    就是它落位时的前置状态。卖出校验必须看这个数,而不是当前最终持仓:
    用户补录一笔更早日期的卖出时,两者不一样。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        _row, base, chain, _tx_rows = await _load_chain(session, stock_code, acct)
        prefix = [spec for spec in chain if spec.trade_date <= trade_date]
        state, _ = replay_chain(base, prefix)
    return max(state.shares, 0)


async def check_chain(
    stock_code: str,
    account_id: int | None = None,
    *,
    override: TxSpec | None = None,
    drop_id: int | None = None,
    insert: TxSpec | None = None,
) -> ChainState:
    """按给定改动试算链,失败抛 PositionChainError;返回改动后的最终状态

    用于「写库前先验算」:修改/新增流水时,先确认改完之后链仍然自洽
    (不会出现卖出超过当时持仓),再落库。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        _row, base, chain, _tx_rows = await _load_chain(session, stock_code, acct)

    specs = list(chain)
    if drop_id is not None:
        specs = [s for s in specs if s.id != drop_id]
    if override is not None:
        specs = [override if s.id == override.id else s for s in specs]
    if insert is not None:
        # 新流水 id 恒大于既有 id → 同日排序它排最后
        specs.append(replace(insert, id=insert.id or 2**62))
        # 排序键必须与链重放一致(全序键),否则「校验顺序 ≠ 重放顺序」
        specs.sort(key=_spec_sort_key)

    state, _ = replay_chain(base, specs)
    return state


async def is_absorbed(stock_code: str, tx_id: int, account_id: int | None = None) -> bool:
    """该流水是否已被导入基准吸收(id <= base_tx_id)

    已吸收的流水不参与重放,改/删它不会影响成本 → 明确拒绝并提示重新导入基准。
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
    if row is None:
        return False
    return tx_id <= row.base_tx_id


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


# ============================================================
# 账户可用资金(正T 测算用)
# ============================================================

async def get_cash_available(account_id: int | None = None) -> Decimal | None:
    """账户可用资金(元)。None = 未填写。

    只给跨域调用方(calculator 域)用 —— 跨域只能 import 本模块的 service。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID, account_repo

    return await account_repo.get_cash_available(account_id or DEFAULT_ACCOUNT_ID)


async def set_cash_available(
    value: Decimal | None, account_id: int | None = None
) -> bool:
    """写账户可用资金。传 None = 清空(= 未填写)。"""
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID, account_repo

    return await account_repo.set_cash_available(
        account_id or DEFAULT_ACCOUNT_ID, value
    )


# ============================================================
# 持仓起点(v0.10:决策层「持有天数」的取数口)
# ============================================================

# 起点来源:两种口径的文案必须不同,不能混为一谈
START_SOURCE_TRANSACTIONS = "transactions"  # 最早一笔流水 → 真实起点可追溯
START_SOURCE_SNAPSHOT = "snapshot"        # 持仓行落库日 → 快照导入日,真实建仓日未知


class PositionStart(NamedTuple):
    """持仓起点 + 其来源(来源决定文案口径)"""

    date: date
    source: str  # START_SOURCE_TRANSACTIONS | START_SOURCE_SNAPSHOT


async def get_position_start(
    stock_code: str, account_id: int | None = None
) -> PositionStart | None:
    """持仓起点 + 来源。优先级:最早流水日期 → 持仓行落库日。

    给决策层「持有天数」用。口径必须如实标注:
    - 有流水 → 最早一笔流水的 `trade_date`(活链起点,最准);
    - 无流水 → `positions.created_at` 的日期(**快照导入日,不是真实建仓日**);
    - 都没有 → None(调用方降级,不编数字)。

    ⚠️ `Position` **没有** `base_date` 字段——`base_date` 只是导入接口的入参
    (决定吸收哪些流水),从未落库,不得当作持仓起点使用。
    """
    from app.modules.portfolio.account_repository import DEFAULT_ACCOUNT_ID

    acct = account_id or DEFAULT_ACCOUNT_ID
    async with async_session() as session:
        earliest = await session.execute(
            select(Transaction.trade_date)
            .where(
                Transaction.account_id == acct,
                Transaction.stock_code == stock_code,
            )
            .order_by(Transaction.trade_date)
            .limit(1)
        )
        trade_day = earliest.scalar_one_or_none()
        if trade_day is not None:
            return PositionStart(date=trade_day, source=START_SOURCE_TRANSACTIONS)
        created = await session.execute(
            select(PositionRow.created_at)
            .where(
                PositionRow.account_id == acct,
                PositionRow.stock_code == stock_code,
            )
            .limit(1)
        )
        created_at = created.scalar_one_or_none()
        if created_at is None:
            return None
        return PositionStart(date=created_at.date(), source=START_SOURCE_SNAPSHOT)


__all__ = [
    "Position",
    "ChainState",
    "TxSpec",
    "PositionChainError",
    "chain_sort_key",
    "aggregate_positions",
    "apply_transaction",
    "replay_chain",
    "recalc_position",
    "get_all_positions",
    "get_position",
    "upsert_position",
    "delete_position",
    "position_before_trade",
    "shares_available_at",
    "is_absorbed",
    "get_cash_available",
    "set_cash_available",
    "get_position_start",
    "PositionStart",
    "START_SOURCE_TRANSACTIONS",
    "START_SOURCE_SNAPSHOT",
]
