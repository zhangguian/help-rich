"""v0.2.1:新增资金流表(E)

- fund_flow:每只股票的资金流入流出事件
- 索引 (stock_code, timestamp) 供 SSE 历史拉取用
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "0fa1cd603fd7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fund_flow",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False),
        sa.Column("timestamp", sa.DateTime, nullable=False),
        sa.Column("direction", sa.String, nullable=False),
        sa.Column("amount", sa.String, nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=True, default="mock"),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("idx_fund_flow_code_time", "fund_flow", ["stock_code", "timestamp"])


def downgrade() -> None:
    op.drop_index("idx_fund_flow_code_time", table_name="fund_flow")
    op.drop_table("fund_flow")