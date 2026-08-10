"""盘后选股 picks.reason 入选理由字段(v2.6.1)

Revision ID: j2e3f4g5h6i7
Revises: i1d2e3f4g5h6
Create Date: 2026-08-09 23:55:00.000000

新增 1 列(nullable):
- reason TEXT — 本地规则拼接的入选理由(1-2 句中文);跑批时由 build_reason() 生成
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "j2e3f4g5h6i7"
down_revision: Union[str, None] = "i1d2e3f4g5h6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("screener_picks", sa.Column("reason", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("screener_picks", "reason")