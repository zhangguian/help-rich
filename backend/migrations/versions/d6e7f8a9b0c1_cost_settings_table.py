"""cost_settings 交易费用设置表(GB-001 IR-4)

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-04 02:00:00.000000

交易费用参数单行表:
- enabled 默认 False(双口径展示关闭,不含费用,保持旧版行为)
- 费率默认 A 股常见值:佣金万2.5 / 最低5元 / 印花税卖出0.05% / 过户费0.001%
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cost_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("commission_rate", sa.String, nullable=False, server_default="0.00025"),
        sa.Column("min_commission", sa.String, nullable=False, server_default="5.00"),
        sa.Column("stamp_tax_rate", sa.String, nullable=False, server_default="0.0005"),
        sa.Column("transfer_fee_rate", sa.String, nullable=False, server_default="0.00001"),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("cost_settings")
