"""transactions.trade_time 交易时间节点(持仓侧「录入流水 + 时间节点」)

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f70812
Create Date: 2026-11-02 16:40:00.000000

流水新增「时间点」字段:
- 只加**可空**列,存量流水一律 NULL(= 时间未知,不回填、不编造)
- 用途 ①:同日流水的成本链排序键 (trade_date, trade_time, id)
- 用途 ②:「交易时机」评分维度的时段输入
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f70812"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("trade_time", sa.Time(), nullable=True),
    )


def downgrade() -> None:
    # SQLite 不支持直接 DROP COLUMN,需 batch 模式重建表
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("trade_time")
