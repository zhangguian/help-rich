"""v0.11:K 线异动行为标注(四信号)相关表

- `fund_flow_daily_cache`:个股逐日资金流缓存(DB 优先,避免每次开 K 线图都打外网)
- `behavior_signal_run` / `behavior_signal_pick`:找股批次与命中记录
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b3c4d5e6f708"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fund_flow_daily_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("net_amount", sa.String, nullable=False, server_default="0"),
        sa.Column("r0_net", sa.String, nullable=False, server_default="0"),
        sa.Column("r0x_ratio", sa.String, nullable=True),
        sa.Column("r0_ratio", sa.String, nullable=True),
        sa.Column("turnover", sa.String, nullable=True),
        sa.Column("change_ratio", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=True, server_default="sina"),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index(
        "idx_flow_daily_code_date",
        "fund_flow_daily_cache",
        ["stock_code", "trade_date"],
    )

    op.create_table(
        "behavior_signal_run",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("generated_at", sa.DateTime, nullable=False),
        sa.Column("pool_size", sa.Integer, nullable=False, server_default="0"),
        sa.Column("main_board_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("non_st_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("after_filters_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("candidates_considered", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_picks", sa.Integer, nullable=False, server_default="0"),
        sa.Column("elapsed_sec", sa.Float, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
    )

    op.create_table(
        "behavior_signal_pick",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, nullable=False),
        sa.Column("run_date", sa.Date, nullable=False),
        sa.Column("stock_code", sa.String, nullable=False),
        sa.Column("stock_name", sa.String, nullable=True),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("signal_date", sa.Date, nullable=False),
        sa.Column("days_ago", sa.Integer, nullable=False, server_default="0"),
        sa.Column("score", sa.Float, nullable=False, server_default="0"),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("metrics_json", sa.Text, nullable=True),
        sa.Column("change_pct", sa.Float, nullable=True),
    )
    op.create_index("idx_behavior_pick_run", "behavior_signal_pick", ["run_id", "score"])
    op.create_index(
        "idx_behavior_pick_code", "behavior_signal_pick", ["stock_code", "run_date"]
    )


def downgrade() -> None:
    op.drop_index("idx_behavior_pick_code", table_name="behavior_signal_pick")
    op.drop_index("idx_behavior_pick_run", table_name="behavior_signal_pick")
    op.drop_table("behavior_signal_pick")
    op.drop_table("behavior_signal_run")
    op.drop_index("idx_flow_daily_code_date", table_name="fund_flow_daily_cache")
    op.drop_table("fund_flow_daily_cache")
