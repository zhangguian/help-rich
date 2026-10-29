"""add battle_plan_pool table

Revision ID: e2f3a4b5c6d7
Revises: d9e0f1a2b3c4
Create Date: 2026-10-25 21:40:00.000000

作战计划 v2:全市场滚动池的持久化。

- battle_plan_pool : 滚动池成员状态(在池 / 已剔除 / 连续未达预期天数 / 幂等键)

**为什么单独建表**:滚动池是**跨天实体**,它的记忆(连续未达预期天数)
必须活过日报重生成;而 `battle_plan_items` 会被 `replace_items` 整体覆盖。
两者生命周期不同,混在一张表里会互相污染。

**幂等**:先 `sa.inspect(bind).has_table(...)` 再建表 —— 本项目沿用同一防御
(`kline_cache` 曾因「迁移已应用但表被删」导致 `alembic upgrade head` 直接失败)。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d9e0f1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("battle_plan_pool"):
        op.create_table(
            "battle_plan_pool",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("stock_code", sa.String, nullable=False),
            sa.Column("stock_name", sa.String, nullable=True),
            sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("joined_on", sa.String, nullable=False),
            sa.Column("miss_streak", sa.Integer, nullable=False, server_default="0"),
            sa.Column("last_evaluated_on", sa.String, nullable=True),
            sa.Column("last_status", sa.String, nullable=True),
            sa.Column("last_score", sa.Float, nullable=True),
            sa.Column("last_reason", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
            sa.Column("updated_at", sa.DateTime, nullable=True),
        )
        # 与 ORM 的 `unique=True, index=True` 对齐:同名**唯一索引**
        # (不是「唯一约束 + 同名普通索引」——同名不同义会让 alembic autogenerate 误报差异)
        op.create_index(
            "ix_battle_plan_pool_stock_code",
            "battle_plan_pool",
            ["stock_code"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("battle_plan_pool"):
        op.drop_table("battle_plan_pool")
