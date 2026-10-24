"""cost event sourcing: snapshot columns + baseline columns

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f123
Create Date: 2026-10-24 10:30:00.000000

阶段 11「成本价同步逻辑重构(方案B·每笔流水存持仓快照)」:

- transactions 新增 `shares_after` / `total_cost_after` / `realized_after`
  → 每笔流水自己记下「应用完我之后」的持仓快照(事件溯源)
- positions 新增 `base_shares` / `base_total_cost` / `base_realized_pnl` / `base_tx_id`
  → 基准(导入/手动录入那一刻的真实持仓)+ 已吸收流水 id 上界

真相公式(新):
    当前持仓 = 基准(base_*) + 其后所有 id > base_tx_id 的流水
               按 (trade_date, id) 顺序逐笔加权平均应用

旧公式(作废):
    当前持仓 = delta(持仓行现值 − 从 0 开始的流水聚合) + 全部流水聚合
    → 导入的快照已含历史流水效果,流水又被重放一遍 = 双算

**回填策略**(存量数据不猜、不改):
- positions.base_* = 该行现值;base_tx_id = 该股票最大流水 id
  → 历史流水全部视为「已被基准吸收」,持仓值保持不变
  → 成本价由用户在 App 持仓编辑页手动修正(基准即真相)
- 有流水但没有持仓行的股票:补一行 base=(0, 0, 流水口径已实现盈亏),
  base_tx_id = 最大流水 id,shares=0 → 该票不显示在持仓列表,已实现盈亏不丢
- transactions 的快照列保持 NULL(存量流水不在新链里,快照无意义)

**幂等**:先 `sa.inspect(bind)` 检查列/表是否存在再改。
"""
from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TX_SNAPSHOT_COLS = (
    ("shares_after", sa.Integer(), True),
    ("total_cost_after", sa.String(), True),
    ("realized_after", sa.String(), True),
)

_POS_BASE_COLS = (
    ("base_shares", sa.Integer(), False, "0"),
    ("base_total_cost", sa.String(), False, "0.00"),
    ("base_realized_pnl", sa.String(), False, "0.00"),
    ("base_tx_id", sa.Integer(), False, "0"),
)


def _add_missing_columns(table: str, cols) -> None:
    """给已存在的表补列(幂等)

    SQLite 不允许 ADD COLUMN ... NOT NULL 且无默认值 → 必须带 server_default。
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return
    existing = {c["name"] for c in inspector.get_columns(table)}
    for col in cols:
        name, col_type, nullable = col[0], col[1], col[2]
        server_default = col[3] if len(col) > 3 else None
        if name in existing:
            continue
        op.add_column(
            table,
            sa.Column(name, col_type, nullable=nullable, server_default=server_default),
        )


def _flow_realized_pnl(rows) -> Decimal:
    """从 0 开始重放流水的已实现盈亏(旧 aggregate_positions 的宽松口径)

    卖出超过当前持仓时不抛错(允许负股数),与旧 aggregate_positions(strict=False) 一致。
    """
    shares = 0
    cost = Decimal("0")
    realized = Decimal("0")
    for tx in sorted(rows, key=lambda r: (r.trade_date, r.id)):
        price = Decimal(tx.price)
        if tx.action == "buy":
            shares += tx.shares
            cost += price * tx.shares
        else:
            avg = (cost / shares) if shares > 0 else Decimal("0")
            realized += (price - avg) * tx.shares
            cost -= avg * tx.shares
            shares -= tx.shares
    return realized


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1) 加列
    _add_missing_columns("transactions", _TX_SNAPSHOT_COLS)
    _add_missing_columns("positions", _POS_BASE_COLS)

    inspector = sa.inspect(bind)
    if not inspector.has_table("positions") or not inspector.has_table("transactions"):
        return

    pos_rows = list(bind.execute(sa.text("SELECT * FROM positions")).mappings())
    tx_rows = list(bind.execute(sa.text("SELECT * FROM transactions")).mappings())

    # 2) 按 (account_id, stock_code) 分组流水
    by_key: dict[tuple, list] = {}
    for tx in tx_rows:
        key = (tx["account_id"], tx["stock_code"])
        by_key.setdefault(key, []).append(tx)

    max_tx_id: dict[tuple, int] = {
        key: max((r["id"] for r in rows), default=0) for key, rows in by_key.items()
    }

    # 3) 回填 positions.base_*
    for row in pos_rows:
        key = (row["account_id"], row["stock_code"])
        bind.execute(
            sa.text(
                "UPDATE positions SET base_shares=:sh, base_total_cost=:tc, "
                "base_realized_pnl=:pnl, base_tx_id=:btx WHERE id=:id"
            ),
            {
                "sh": row["shares"],
                "tc": row["total_cost"],
                "pnl": row["realized_pnl"],
                "btx": max_tx_id.get(key, 0),
                "id": row["id"],
            },
        )

    # 4) 有流水但没有持仓行 → 补基准行(shares=0,不进持仓列表)
    existing_keys = {(r["account_id"], r["stock_code"]) for r in pos_rows}
    for key, rows in by_key.items():
        if key in existing_keys:
            continue
        realized = _flow_realized_pnl(rows)
        latest = max(rows, key=lambda r: r["id"])
        bind.execute(
            sa.text(
                "INSERT INTO positions (account_id, stock_code, stock_name, shares, "
                "total_cost, realized_pnl, base_shares, base_total_cost, "
                "base_realized_pnl, base_tx_id, created_at, updated_at) "
                "VALUES (:acct, :code, :name, 0, '0.00', :pnl, 0, '0.00', :pnl, :btx, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "acct": key[0],
                "code": key[1],
                "name": latest.get("stock_name"),
                "pnl": str(realized.quantize(Decimal("0.01"))),
                "btx": max_tx_id.get(key, 0),
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, cols in (("transactions", _TX_SNAPSHOT_COLS), ("positions", _POS_BASE_COLS)):
        if not inspector.has_table(table):
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for col in cols:
            name = col[0]
            if name in existing:
                op.drop_column(table, name)
