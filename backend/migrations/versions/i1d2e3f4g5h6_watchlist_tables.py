"""盘后选股 — 观察池 2 张表(v2.6)

Revision ID: i1d2e3f4g5h6
Revises: h0c1d2e3f4g5
Create Date: 2026-08-09 23:30:00.000000

新增 2 张表:
- screener_watchlist        用户从选股页标记的标的(UNIQUE stock_code)
- screener_watchlist_daily  标选后逐日 K 线记录(UNIQUE watchlist_id + trade_date)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "i1d2e3f4g5h6"
down_revision: Union[str, None] = "h0c1d2e3f4g5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "screener_watchlist",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False, unique=True),
        sa.Column("stock_name", sa.String, nullable=False),
        sa.Column("marked_at", sa.Date, nullable=False),
        sa.Column("marked_close", sa.String, nullable=True),
        sa.Column("marked_change_pct", sa.String, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "screener_watchlist_daily",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "watchlist_id",
            sa.Integer,
            sa.ForeignKey("screener_watchlist.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("open_price", sa.String, nullable=False),
        sa.Column("high_price", sa.String, nullable=False),
        sa.Column("low_price", sa.String, nullable=False),
        sa.Column("close_price", sa.String, nullable=False),
        sa.Column("volume", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pct_from_marked", sa.String, nullable=True),
        sa.UniqueConstraint("watchlist_id", "trade_date", name="uq_watchlist_trade_date"),
    )
    op.create_index(
        "idx_watchlist_daily_date",
        "screener_watchlist_daily",
        ["watchlist_id", "trade_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_watchlist_daily_date", table_name="screener_watchlist_daily")
    op.drop_table("screener_watchlist_daily")
    op.drop_table("screener_watchlist")