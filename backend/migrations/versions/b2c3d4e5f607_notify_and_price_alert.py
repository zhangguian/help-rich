"""阶段1:通知渠道配置 + 价格提醒表

Revision ID: b2c3d4e5f607
Revises: a1c2d3e4f506
Create Date: 2026-10-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b2c3d4e5f607"
down_revision: Union[str, None] = "a1c2d3e4f506"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notify_channel_config",
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config_encrypted", sa.Text(), nullable=True),
        sa.Column("config_hint", sa.String(), nullable=True),
        sa.Column("last_ok_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("channel"),
    )

    op.create_table(
        "price_alert",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("stock_code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False, server_default=""),
        sa.Column("conditions_json", sa.Text(), nullable=False),
        sa.Column("cooldown_sec", sa.Integer(), nullable=False, server_default="1800"),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("channels_json", sa.Text(), nullable=True),
        sa.Column("triggered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_price_alert_code_enabled", "price_alert", ["stock_code", "enabled"]
    )

    op.create_table(
        "price_alert_trigger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=True),
        sa.Column("results_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="matched"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["alert_id"], ["price_alert.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_alert_trigger_alert_time", "price_alert_trigger", ["alert_id", "triggered_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_alert_trigger_alert_time", table_name="price_alert_trigger")
    op.drop_table("price_alert_trigger")
    op.drop_index("idx_price_alert_code_enabled", table_name="price_alert")
    op.drop_table("price_alert")
    op.drop_table("notify_channel_config")
