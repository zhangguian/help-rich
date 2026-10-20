"""阶段3:模拟盘

Revision ID: d4e5f6071829
Revises: c3d4e5f60718
Create Date: 2026-10-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6071829"
down_revision: Union[str, None] = "c3d4e5f60718"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False, server_default="默认模拟账户"),
        sa.Column("initial_capital", sa.String(), nullable=False),
        sa.Column("cash", sa.String(), nullable=False),
        sa.Column("realized_pnl", sa.String(), nullable=False, server_default="0"),
        sa.Column("total_fees", sa.String(), nullable=False, server_default="0"),
        sa.Column("auto_follow", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "paper_order",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("stock_code", sa.String(), nullable=False),
        sa.Column("stock_name", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("price", sa.String(), nullable=False),
        sa.Column("fee", sa.String(), nullable=False, server_default="0"),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False, server_default="manual"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["paper_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_paper_order_account_date", "paper_order", ["account_id", "trade_date"])

    op.create_table(
        "paper_position",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("stock_code", sa.String(), nullable=False),
        sa.Column("stock_name", sa.String(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.String(), nullable=False),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["paper_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_paper_position_account_code", "paper_position", ["account_id", "stock_code"]
    )

    op.create_table(
        "paper_equity_snapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("total_equity", sa.String(), nullable=False),
        sa.Column("cash", sa.String(), nullable=False),
        sa.Column("market_value", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["paper_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_paper_equity_account_date", "paper_equity_snapshot", ["account_id", "snapshot_date"]
    )


def downgrade() -> None:
    op.drop_index("idx_paper_equity_account_date", table_name="paper_equity_snapshot")
    op.drop_table("paper_equity_snapshot")
    op.drop_index("idx_paper_position_account_code", table_name="paper_position")
    op.drop_table("paper_position")
    op.drop_index("idx_paper_order_account_date", table_name="paper_order")
    op.drop_table("paper_order")
    op.drop_table("paper_account")
