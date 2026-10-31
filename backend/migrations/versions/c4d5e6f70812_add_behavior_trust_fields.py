"""v0.12:行为标注可信度加固 —— 批次表加 3 列

- `hit_counts_json`:每类**真实**命中数(闸 1 数字闸)
- `data_as_of`:本批数据中已收盘的最后交易日(闸 4 稳定闸)
- `is_intraday`:本批是否额外包含当日未收盘数据(闸 4 稳定闸)

三列全部 nullable / 有默认值 → 存量批次行不需要回填。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4d5e6f70812"
down_revision: Union[str, None] = "b3c4d5e6f708"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "behavior_signal_run",
        sa.Column("hit_counts_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "behavior_signal_run",
        sa.Column("data_as_of", sa.Date(), nullable=True),
    )
    op.add_column(
        "behavior_signal_run",
        sa.Column(
            "is_intraday",
            sa.Boolean(),
            nullable=True,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("behavior_signal_run", "is_intraday")
    op.drop_column("behavior_signal_run", "data_as_of")
    op.drop_column("behavior_signal_run", "hit_counts_json")
