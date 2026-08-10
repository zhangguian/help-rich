"""盘后选股(screener)模块新增 4 张表(v2.6)

Revision ID: h0c1d2e3f4g5
Revises: g9b0c1d2e3f5
Create Date: 2026-08-09 15:00:00.000000

新增 4 张表:
- index_constituents  沪深300 + 中证500 成分股静态表
- screener_runs       每日 15:30 后台跑批的批次
- screener_picks      每批次的 Top N 候选股(综合分 + 因子明细)
- screener_llm_picks  用户主动触发的 LLM 评选结果(每批次唯一)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "h0c1d2e3f4g5"
down_revision: Union[str, None] = "g9b0c1d2e3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) index_constituents
    op.create_table(
        "index_constituents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("index_code", sa.String, nullable=False),
        sa.Column("stock_code", sa.String, nullable=False),
        sa.Column("stock_name", sa.String, nullable=False),
        sa.Column("added_at", sa.Date, nullable=False),
        sa.UniqueConstraint("index_code", "stock_code", name="uq_index_stock"),
    )
    op.create_index("idx_index_code", "index_constituents", ["index_code"])

    # 2) screener_runs
    op.create_table(
        "screener_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("generated_at", sa.DateTime, nullable=False),
        sa.Column("scoring_version", sa.String, nullable=False, server_default="v1.0"),
        sa.Column("pool_size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_picks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("elapsed_sec", sa.Float, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.UniqueConstraint("run_date", name="uq_screener_run_date"),
    )
    op.create_index("idx_screener_runs_date", "screener_runs", ["run_date"])

    # 3) screener_picks
    op.create_table(
        "screener_picks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer,
            sa.ForeignKey("screener_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("stock_code", sa.String, nullable=False),
        sa.Column("stock_name", sa.String, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("main_net_inflow_yi", sa.Float, nullable=True),
        sa.Column("volume_ratio", sa.Float, nullable=True),
        sa.Column("change_pct", sa.Float, nullable=True),
        sa.Column("turnover_proxy", sa.Float, nullable=True),
        sa.Column("consecutive_up_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sector", sa.String, nullable=True),
        sa.Column("sector_inflow_rank", sa.Integer, nullable=True),
        sa.Column("triggered_rules", sa.Text, nullable=False, server_default="[]"),
    )
    op.create_index("idx_screener_picks_run", "screener_picks", ["run_id"])
    op.create_index(
        "idx_screener_picks_code_date", "screener_picks", ["stock_code"]
    )

    # 4) screener_llm_picks
    op.create_table(
        "screener_llm_picks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer,
            sa.ForeignKey("screener_runs.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("requested_at", sa.DateTime, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("picks_json", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="success"),
    )


def downgrade() -> None:
    op.drop_table("screener_llm_picks")
    op.drop_index("idx_screener_picks_code_date", table_name="screener_picks")
    op.drop_index("idx_screener_picks_run", table_name="screener_picks")
    op.drop_table("screener_picks")
    op.drop_index("idx_screener_runs_date", table_name="screener_runs")
    op.drop_table("screener_runs")
    op.drop_index("idx_index_code", table_name="index_constituents")
    op.drop_table("index_constituents")