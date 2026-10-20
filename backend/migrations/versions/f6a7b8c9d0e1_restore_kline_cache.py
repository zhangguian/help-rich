"""修复:补回缺失的 kline_cache 表(幂等)

**背景**
`kline_cache` 由迁移 `a9b8c7d6e5f4` 创建,但 2026-10-20 实测发现:
现网 `data.db` 里 31 张表独缺 `kline_cache`,而 `alembic_version` 已在 head
(`e5f60718293a`)。即"迁移已应用,但表后来被删"——
alembic 认为无事可做,启动时 `upgrade head` 不会自愈,于是:

    sqlalchemy.exc.OperationalError: no such table: kline_cache

K 线接口与整条分析链路(指标计算 / AI 解读 / 分时图)全部 500。

**修法**
本迁移幂等补表:
- 表不存在 → 按 `a9b8c7d6e5f4` 完全相同的结构建表 + 建索引
- 表已存在(从零跑全链时会被 a9b8c7d6e5f4 先建出来)→ 跳过建表,
  仅确保索引存在

这样既修好现存库,又不会破坏"全新库按序跑迁移"的路径。

**教训**
schema 漂移(迁移已应用 / 表被删)不会被 `alembic upgrade head` 发现。
若这类问题反复出现,应补一个"启动期 schema 自检 + 自动补建"的守卫,
而不是每次手写补偿迁移。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f60718293a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "idx_kline_code_period_date"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("kline_cache"):
        op.create_table(
            "kline_cache",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("stock_code", sa.String, nullable=False),
            sa.Column("trade_date", sa.Date, nullable=False),
            sa.Column("period", sa.String, nullable=False, default="daily"),
            sa.Column("open_price", sa.String, nullable=False),
            sa.Column("high_price", sa.String, nullable=False),
            sa.Column("low_price", sa.String, nullable=False),
            sa.Column("close_price", sa.String, nullable=False),
            sa.Column("volume", sa.Integer, nullable=True, default=0),
            sa.Column("source", sa.String, nullable=True, default="sina"),
            sa.Column("updated_at", sa.DateTime, nullable=True),
        )
    # 索引幂等补建
    existing = {ix["name"] for ix in inspector.get_indexes("kline_cache")}
    if _INDEX_NAME not in existing:
        op.create_index(
            _INDEX_NAME,
            "kline_cache",
            ["stock_code", "period", "trade_date"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("kline_cache"):
        return
    existing = {ix["name"] for ix in inspector.get_indexes("kline_cache")}
    if _INDEX_NAME in existing:
        op.drop_index(_INDEX_NAME, table_name="kline_cache")
    op.drop_table("kline_cache")
