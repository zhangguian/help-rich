"""watchlist.is_favorite 特别关注标记(v0.5)

Revision ID: c5d6e7f8a9b0
Revises: b4c2d1e6f7a8
Create Date: 2026-08-03 21:00:00.000000

自选股标的星标收藏字段:
- 默认 False
- 前端 Star 按钮点击切换
- 顶级 Tab 「⭐ 关注」按 is_favorite=True 过滤
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c2d1e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "watchlist",
        sa.Column("is_favorite", sa.Boolean, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("watchlist", "is_favorite")
