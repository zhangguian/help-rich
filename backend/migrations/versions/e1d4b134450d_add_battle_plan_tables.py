"""add battle plan tables

Revision ID: e1d4b134450d
Revises: f6a7b8c9d0e1
Create Date: 2026-10-21 23:11:14.865075

阶段9「每日作战计划」持久化:
- battle_plans        : 生成日唯一的日报(outlook / review / meta 三段 JSON)
- battle_plan_items   : 逐票预案(触发价 / 触发条件 / 依据 / 失效条件 / 兑现状态)

**幂等**:先 `sa.inspect(bind).has_table(...)` 再建表 —— `kline_cache` 曾因
"迁移已应用但表被删"导致 `alembic upgrade head` 直接失败,本项目沿用同一防御。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1d4b134450d"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("battle_plans"):
        op.create_table(
            "battle_plans",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("plan_date", sa.String, nullable=False),
            sa.Column("outlook_json", sa.Text, nullable=True),
            sa.Column("review_json", sa.Text, nullable=True),
            sa.Column("meta_json", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
            sa.Column("updated_at", sa.DateTime, nullable=True),
        )
        # 与 ORM 的 `unique=True, index=True` 对齐:同名**唯一索引**
        # (不是「唯一约束 + 同名普通索引」——同名不同义会让 alembic autogenerate 误报差异)
        op.create_index("ix_battle_plans_plan_date", "battle_plans", ["plan_date"], unique=True)

    if not inspector.has_table("battle_plan_items"):
        op.create_table(
            "battle_plan_items",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("plan_id", sa.Integer, sa.ForeignKey("battle_plans.id"), nullable=False),
            sa.Column("plan_date", sa.String, nullable=False),
            sa.Column("stock_code", sa.String, nullable=False),
            sa.Column("stock_name", sa.String, nullable=True),
            sa.Column("item_kind", sa.String, nullable=False),
            sa.Column("direction", sa.String, nullable=False),
            sa.Column("label", sa.String, nullable=False),
            sa.Column("trigger_price", sa.Float, nullable=True),
            sa.Column("trigger_condition", sa.Text, nullable=False),
            sa.Column("basis_json", sa.Text, nullable=True),
            sa.Column("invalid_if", sa.Text, nullable=True),
            sa.Column("status_now", sa.String, nullable=False),
            sa.Column("source", sa.String, nullable=True),
            sa.Column("fulfillment", sa.String, nullable=False, server_default="pending"),
            sa.Column("fulfillment_note", sa.Text, nullable=True),
        )
        op.create_index("ix_battle_plan_items_plan_id", "battle_plan_items", ["plan_id"])
        op.create_index("ix_battle_plan_items_plan_date", "battle_plan_items", ["plan_date"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("battle_plan_items"):
        op.drop_table("battle_plan_items")
    if inspector.has_table("battle_plans"):
        op.drop_table("battle_plans")
