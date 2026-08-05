"""daily_analyses 每日 AI 分析持久化表(v2.4)

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-08-05 03:30:00.000000

每 (stock_code, analysis_date) 一条最新 AI 分析结果,UPSERT 覆盖。
- analysis_date = K 线最新交易日(语义:对哪天的行情做分析),fallback today
- 用于后续历史查看 / 方向胜率分析(P1)
- 与 replay_records(per stock × window)互不替代
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_analyses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False),
        sa.Column("analysis_date", sa.Date, nullable=False),
        sa.Column("score_avg", sa.String, nullable=True),
        sa.Column("dimension_avg", sa.Text, nullable=False),
        sa.Column("top_issues", sa.Text, nullable=False),
        sa.Column("ai_view", sa.String, nullable=True),
        sa.Column("ai_summary", sa.Text, nullable=True),
        sa.Column("current_price", sa.String, nullable=True),
        sa.Column("latest_kline_date", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    # 同 (股票, 日期) 多次分析只保留最新一条(UNIQUE 约束)
    op.create_index(
        "uq_daily_stock_date",
        "daily_analyses",
        ["stock_code", "analysis_date"],
        unique=True,
    )
    # 历史查询按日期倒序(普通索引)
    op.create_index(
        "idx_daily_stock_date_desc",
        "daily_analyses",
        ["stock_code", "analysis_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_daily_stock_date_desc", table_name="daily_analyses")
    op.drop_index("uq_daily_stock_date", table_name="daily_analyses")
    op.drop_table("daily_analyses")