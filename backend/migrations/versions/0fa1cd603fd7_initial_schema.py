"""initial schema

Revision ID: 0fa1cd603fd7
Revises: 
Create Date: 2026-08-01 20:19:46.306712

迁移自 v0.2 之前的 create_all 模式,初次切 Alembic 时 stamp head 标记。
后续加新表 / 字段:alembic revision --autogenerate -m "..."
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0fa1cd603fd7"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # llm_api_keys(v2.1)
    op.create_table(
        "llm_api_keys",
        sa.Column("provider", sa.String, primary_key=True),
        sa.Column("encrypted_key", sa.String, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    # llm_settings(v1.5)
    op.create_table(
        "llm_settings",
        sa.Column("id", sa.Integer, primary_key=True, default=1),
        sa.Column("active_provider", sa.String, nullable=True, default="deepseek"),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    # transactions(P2.1)
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False),
        sa.Column("stock_name", sa.String, nullable=True),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("shares", sa.Integer, nullable=False),
        sa.Column("price", sa.String, nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("idx_transactions_code", "transactions", ["stock_code"])
    op.create_index("idx_transactions_date", "transactions", ["trade_date"])

    # watchlist(P2.1)
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False, unique=True),
        sa.Column("stock_name", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=True, default="manual"),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("added_at", sa.DateTime, nullable=True),
    )

    # trade_scores(P2.1)
    op.create_table(
        "trade_scores",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "trade_id",
            sa.Integer,
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("score_breakdown", sa.Text, nullable=False),
        sa.Column("ai_comment", sa.Text, nullable=True),
        sa.Column("ai_status", sa.String, nullable=True, default="pending"),
        sa.Column("ai_provider", sa.String, nullable=True, default="deepseek"),
        sa.Column("ai_model", sa.String, nullable=True),
        sa.Column("ai_latency_ms", sa.Integer, nullable=True),
        sa.Column("feedback", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )
    op.create_index("idx_trade_scores_trade", "trade_scores", ["trade_id"])

    # stop_losses(P5.1)
    op.create_table(
        "stop_losses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("stock_code", sa.String, nullable=False, unique=True),
        sa.Column("stop_loss_price", sa.String, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=True, default=True),
        sa.Column("notify_sound", sa.Boolean, nullable=True, default=True),
        sa.Column("notify_desktop", sa.Boolean, nullable=True, default=True),
        sa.Column("notify_vibrate", sa.Boolean, nullable=True, default=True),
        sa.Column("last_triggered_at", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )

    # screenshot_records(P8.1)
    op.create_table(
        "screenshot_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("file_path", sa.String, nullable=True),
        sa.Column("ocr_text", sa.Text, nullable=True),
        sa.Column("raw_response", sa.Text, nullable=True),
        sa.Column("parsed_items", sa.Text, nullable=False),
        sa.Column("screenshot_type", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=True, default="ocr_llm"),
        sa.Column("status", sa.String, nullable=True, default="pending"),
        sa.Column("uploaded_at", sa.DateTime, nullable=True),
        sa.Column("confirmed_at", sa.DateTime, nullable=True),
    )
    op.create_index("idx_screenshot_status", "screenshot_records", ["status"])


def downgrade() -> None:
    op.drop_index("idx_screenshot_status", table_name="screenshot_records")
    op.drop_table("screenshot_records")
    op.drop_table("stop_losses")
    op.drop_index("idx_trade_scores_trade", table_name="trade_scores")
    op.drop_table("trade_scores")
    op.drop_table("watchlist")
    op.drop_index("idx_transactions_date", table_name="transactions")
    op.drop_index("idx_transactions_code", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("llm_settings")
    op.drop_table("llm_api_keys")