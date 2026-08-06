"""daily_analyses 加 ai_advice_json 列(v2.5 结构化操作参考)

Revision ID: g9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-08-06 09:30:00.000000

- 新增 ai_advice_json TEXT NULL
  存 LLM 输出的完整结构化 advice:{rationale, price, position_pct, trigger,
  holding_window, not_action, t_strategy?}
- 老行该列 NULL → 前端读不到时降级为空对象,无破坏
- ai_summary 仍保留(存 rationale 单字符串,兼容历史展示)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "g9b0c1d2e3f4"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "daily_analyses",
        sa.Column("ai_advice_json", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("daily_analyses", "ai_advice_json")