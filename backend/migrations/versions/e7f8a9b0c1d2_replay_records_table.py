"""replay_records 一键复盘记录表(v2.3)

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-04 23:50:00.000000

每 (stock_code, window) 一条最新复盘记录,UPSERT 覆盖。
- window: 1d / 3d / 5d / 10d / 20d / 60d(交易日口径)
- latest_tx_id: 缓存失效键(窗口内最新流水 id)
- dimension_avg: 5 维度均值 JSON
- top_issues: Top 3 低分维度 JSON
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "replay_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False),
        sa.Column("window", sa.String, nullable=False),
        sa.Column("score_avg", sa.String, nullable=True),
        sa.Column("dimension_avg", sa.Text, nullable=False),
        sa.Column("top_issues", sa.Text, nullable=False),
        sa.Column("summary_snapshot", sa.Text, nullable=False),
        sa.Column("ai_comment", sa.Text, nullable=True),
        sa.Column("ai_status", sa.String, nullable=False, server_default="success"),
        sa.Column("ai_provider", sa.String, nullable=True),
        sa.Column("ai_model", sa.String, nullable=True),
        sa.Column("ai_latency_ms", sa.Integer, nullable=True),
        sa.Column("latest_tx_id", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    # 同 (股票, 窗口) 多次复盘 → UPSERT 覆盖(UNIQUE 约束)
    op.create_index(
        "uq_replay_stock_window",
        "replay_records",
        ["stock_code", "window"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_replay_stock_window", table_name="replay_records")
    op.drop_table("replay_records")