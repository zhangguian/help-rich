"""fund_flow 保留策略支撑索引

Revision ID: a1c2d3e4f506
Revises: 37d7fbee1cbe
Create Date: 2026-10-17

背景:`fund_flow` 由调度器每 60s 写入约 150 行(3 个市场 × Top50),
无上限时本地库实测膨胀到 234 万行 / 348MB,而前端只读每只股票最近 30 条。
新增 `fund_flow` 单列 timestamp 索引,让保留策略裁剪
(DELETE ... WHERE stock_code = ? AND id NOT IN (最近 N 条))
能用索引而不是全表扫描。

注意:本迁移只加索引,不删数据 —— 裁剪由 `app/services/retention.py`
在应用启动时执行(见 settings.fund_flow_keep_per_stock)。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a1c2d3e4f506"
down_revision: Union[str, None] = "37d7fbee1cbe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等:索引可能已由手工补建过
    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='fund_flow'"
        )
    }
    if "idx_fund_flow_timestamp" not in existing:
        op.create_index("idx_fund_flow_timestamp", "fund_flow", ["timestamp"])


def downgrade() -> None:
    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='fund_flow'"
        )
    }
    if "idx_fund_flow_timestamp" in existing:
        op.drop_index("idx_fund_flow_timestamp", table_name="fund_flow")
