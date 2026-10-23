"""add intraday review table

Revision ID: b7c8d9e0f123
Revises: e1d4b134450d
Create Date: 2026-10-22 22:10:00.000000

阶段 T2「盘中复盘」持久化:
- intraday_review : 交易日 × 档位(11:30 / 14:00)唯一,存整份复盘 JSON

**幂等**:先 `sa.inspect(bind).has_table(...)` 再建表 —— 本项目沿用同一防御
(`kline_cache` 曾因「迁移已应用但表被删」导致 `alembic upgrade head` 直接失败)。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f123"
down_revision: Union[str, None] = "e1d4b134450d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("intraday_review"):
        op.create_table(
            "intraday_review",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("trade_date", sa.String, nullable=False),
            sa.Column("slot", sa.String, nullable=False),
            sa.Column("payload_json", sa.Text, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=True),
            # 同日同档唯一 → 重跑覆盖(幂等),不产生第二行
            sa.UniqueConstraint(
                "trade_date", "slot", name="uq_intraday_review_date_slot"
            ),
        )
        op.create_index(
            "ix_intraday_review_trade_date", "intraday_review", ["trade_date"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("intraday_review"):
        op.drop_table("intraday_review")
