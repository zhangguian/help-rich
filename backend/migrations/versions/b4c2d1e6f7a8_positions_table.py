"""positions 持仓主数据表(v0.4.0)

Revision ID: b4c2d1e6f7a8
Revises: f1a2b3c4d5e6
Create Date: 2026-08-01 02:30:00.000000

持仓从"流水聚合的影子"翻转为"主数据":
- 新表 positions(stock_code 唯一 / shares / total_cost / realized_pnl)
- backfill:从现有 transactions 聚合生成初始持仓,不丢数据
"""
from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c2d1e6f7a8"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _aggregate_from_transactions(conn: sa.Connection) -> list[dict]:
    """从全部流水聚合持仓(加权平均法,与 position_service.aggregate_positions 同规则)"""
    rows = conn.execute(
        sa.text("SELECT stock_code, stock_name, action, shares, price, trade_date, id "
                "FROM transactions ORDER BY trade_date, id")
    ).fetchall()
    by_code: dict[str, dict] = {}

    def avg_cost(pos: dict) -> Decimal:
        if pos["shares"] <= 0:
            return Decimal("0")
        return pos["total_cost"] / pos["shares"]

    for row in rows:
        stock_code, stock_name, action, shares, price, _td, _id = row
        pos = by_code.setdefault(
            stock_code,
            {"stock_name": stock_name, "shares": 0, "total_cost": Decimal("0"),
             "realized_pnl": Decimal("0")},
        )
        if stock_name:
            pos["stock_name"] = stock_name
        p = Decimal(str(price))
        if action == "buy":
            pos["shares"] += int(shares)
            pos["total_cost"] += p * int(shares)
        elif action == "sell":
            if pos["shares"] >= int(shares):
                pos["realized_pnl"] += (p - avg_cost(pos)) * int(shares)
                pos["total_cost"] -= avg_cost(pos) * int(shares)
                pos["shares"] -= int(shares)
    return [
        {"stock_code": code, "stock_name": pos["stock_name"], "shares": pos["shares"],
         "total_cost": str(pos["total_cost"].quantize(Decimal("0.01"))),
         "realized_pnl": str(pos["realized_pnl"].quantize(Decimal("0.01")))}
        for code, pos in by_code.items() if pos["shares"] > 0
    ]


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False, unique=True),
        sa.Column("stock_name", sa.String, nullable=True),
        sa.Column("shares", sa.Integer, nullable=False),
        sa.Column("total_cost", sa.String, nullable=False),
        sa.Column("realized_pnl", sa.String, nullable=False, server_default="0.00"),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    # backfill:从现有流水聚合初始持仓(幂等:已有 positions 的股票跳过)
    bind = op.get_bind()
    positions = _aggregate_from_transactions(bind)
    for p in positions:
        exists = bind.execute(
            sa.text("SELECT 1 FROM positions WHERE stock_code = :c"),
            {"c": p["stock_code"]},
        ).fetchone()
        if exists:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO positions (stock_code, stock_name, shares, total_cost, realized_pnl) "
                "VALUES (:code, :name, :shares, :cost, :pnl)"
            ),
            {"code": p["stock_code"], "name": p["stock_name"], "shares": p["shares"],
             "cost": p["total_cost"], "pnl": p["realized_pnl"]},
        )


def downgrade() -> None:
    op.drop_table("positions")
