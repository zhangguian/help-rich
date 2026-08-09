"""daily_analyses 加 analysis snapshot 字段(v2.5.2 支持换浏览器回显)

Revision ID: g9b0c1d2e3f5
Revises: g9b0c1d2e3f4
Create Date: 2026-08-06 10:30:00.000000

新增 6 列(nullable,老行全 NULL → 前端降级显示):
- indicators_json TEXT      — compute_indicators 完整输出
- ai_json TEXT              — LLM 解读完整对象(view / viewReason / advice / riskWarning ...)
- signal_winrate_json TEXT  — compute_signal_winrate 输出
- quote_change_pct String   — 实时价相对昨收涨跌幅(小数)
- position_status String    — empty/profit/loss
- cost_basis_pct String     — 基于持仓成本的盈亏百分比(小数)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "g9b0c1d2e3f5"
down_revision: Union[str, None] = "g9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("daily_analyses", sa.Column("indicators_json", sa.Text, nullable=True))
    op.add_column("daily_analyses", sa.Column("ai_json", sa.Text, nullable=True))
    op.add_column("daily_analyses", sa.Column("signal_winrate_json", sa.Text, nullable=True))
    op.add_column("daily_analyses", sa.Column("quote_change_pct", sa.String, nullable=True))
    op.add_column("daily_analyses", sa.Column("position_status", sa.String, nullable=True))
    op.add_column("daily_analyses", sa.Column("cost_basis_pct", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("daily_analyses", "cost_basis_pct")
    op.drop_column("daily_analyses", "position_status")
    op.drop_column("daily_analyses", "quote_change_pct")
    op.drop_column("daily_analyses", "signal_winrate_json")
    op.drop_column("daily_analyses", "ai_json")
    op.drop_column("daily_analyses", "indicators_json")