"""account.cash_available: 账户可用资金

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-10-24 13:30:00.000000

背景(正T / 反T 方向判定):

做 T 有两个方向,资金约束完全不同:
- **反T(先卖后买 · 高抛低吸)**:先卖老仓拿现金,回落再买回 → 不需要额外资金
- **正T(先买后卖 · 低吸高抛)**:先买入 → **必须占用买入资金**

反T 的股数上限由「底仓可动量」决定,正T 除此之外还要被「可用资金 ÷ 买价」
卡一道 —— 所以正T 若拿不到资金,就算不出股数。

为什么落在 `account` 表而不是新建单行表:
- 「资金」天然是**账户级**属性(不是全局设置,也不是某只票的属性)
- 已有多账户模型(`account` 表,阶段5),挂在账户上天然支持多账户隔离
- 新建单行表会与多账户模型打架:多出来的账户就没有资金字段

NULL 语义:**未填写**(不是 0)。判定层据此给 `None` + degraded,
不把「没填」当成「没钱」—— 这两个结论对用户的含义完全不同。

**幂等**:先 `sa.inspect(bind)` 检查列是否存在再改。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("account"):
        return
    existing = {c["name"] for c in inspector.get_columns("account")}
    if "cash_available" in existing:
        return
    # nullable,无默认值 → 存量行一律 NULL(= 未填写)
    op.add_column("account", sa.Column("cash_available", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("account"):
        return
    existing = {c["name"] for c in inspector.get_columns("account")}
    if "cash_available" not in existing:
        return
    op.drop_column("account", "cash_available")
