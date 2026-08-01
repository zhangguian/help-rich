"""v0.2.1:K 线缓存表(D)"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kline_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("period", sa.String, nullable=False, default="daily"),
        sa.Column("open_price", sa.String, nullable=False),
        sa.Column("high_price", sa.String, nullable=False),
        sa.Column("low_price", sa.String, nullable=False),
        sa.Column("close_price", sa.String, nullable=False),
        sa.Column("volume", sa.Integer, nullable=True, default=0),
        sa.Column("source", sa.String, nullable=True, default="mock"),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "idx_kline_code_period_date",
        "kline_cache",
        ["stock_code", "period", "trade_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_kline_code_period_date", table_name="kline_cache")
    op.drop_table("kline_cache")