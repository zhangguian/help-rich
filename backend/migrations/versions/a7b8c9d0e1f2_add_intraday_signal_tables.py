"""add intraday signal config & trigger tables

Revision ID: a7b8c9d0e1f2
Revises: e2f3a4b5c6d7
Create Date: 2026-10-29 23:40:00.000000

盘中持仓信号 · 桌面通知(ADR-0007):

- intraday_signal_config : 盘中信号配置(单行 id=1;阈值 / 开关 / 渠道 / 冷却 / 日限流)
- intraday_signal_trigger: 盘中信号触发流水(含 fingerprint → 跨重启去重)

**为什么指纹要落库**:`app/modules/notify/dedupe.py` 的限流器是**纯内存**的
(`NotifyLimiter._entries: dict`),后端一重启就清零 —— 同一价位的到价信号
会在重启后再弹一次。把指纹落 `intraday_signal_trigger` 并在查询时按
`notified=True` 过滤,即可做到"同一价位当日只提醒一次"且跨重启成立。

**幂等**:先 `sa.inspect(bind).has_table(...)` 再建表(沿用本项目同一防御)。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("intraday_signal_config"):
        op.create_table(
            "intraday_signal_config",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("velocity_window_sec", sa.Integer, nullable=False, server_default="60"),
            sa.Column("velocity_pct", sa.Float, nullable=False, server_default="1.5"),
            sa.Column("breakout_up_pct", sa.Float, nullable=False, server_default="5.0"),
            sa.Column("breakout_down_pct", sa.Float, nullable=False, server_default="-5.0"),
            sa.Column("enable_velocity", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("enable_breakout", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("enable_t_point", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("enable_buy_point", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("cooldown_sec", sa.Integer, nullable=False, server_default="600"),
            sa.Column("daily_limit", sa.Integer, nullable=False, server_default="5"),
            sa.Column("channels_json", sa.Text, nullable=True),
            sa.Column("updated_at", sa.DateTime, nullable=True),
        )

    if not inspector.has_table("intraday_signal_trigger"):
        op.create_table(
            "intraday_signal_trigger",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("stock_code", sa.String, nullable=False),
            sa.Column("stock_name", sa.String, nullable=True),
            sa.Column("kind", sa.String, nullable=False),
            sa.Column("level", sa.Float, nullable=True),
            sa.Column("value", sa.Float, nullable=True),
            sa.Column("title", sa.String, nullable=False),
            sa.Column("body", sa.Text, nullable=False),
            sa.Column("fingerprint", sa.String, nullable=False),
            sa.Column("notified", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
        op.create_index(
            "idx_intraday_signal_code_time",
            "intraday_signal_trigger",
            ["stock_code", "created_at"],
        )
        op.create_index(
            "idx_intraday_signal_fp",
            "intraday_signal_trigger",
            ["fingerprint", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("intraday_signal_trigger"):
        op.drop_table("intraday_signal_trigger")
    if inspector.has_table("intraday_signal_config"):
        op.drop_table("intraday_signal_config")
