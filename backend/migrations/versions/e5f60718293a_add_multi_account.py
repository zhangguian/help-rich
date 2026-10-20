"""阶段5:多账户

Revision ID: e5f60718293a
Revises: d4e5f6071829
Create Date: 2026-10-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e5f60718293a"
down_revision: Union[str, None] = "d4e5f6071829"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) account 表
    op.create_table(
        "account",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False, server_default="默认账户"),
        sa.Column("kind", sa.String(), nullable=False, server_default="broker"),
        sa.Column("broker", sa.String(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # 固定 id=1 作为默认账户:存量持仓/流水全部回填到它
    op.execute(
        "INSERT INTO account (id, name, kind, is_default, created_at, updated_at) "
        "VALUES (1, '默认账户', 'broker', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )

    # 2) positions: 加 account_id,并把 stock_code 的全局唯一换成组合唯一。
    #    SQLite 的 batch_alter_table 会 *reflect* 现有表,把 stock_code 的
    #    UNIQUE 一起复制到新表,导致同一账户下仍不能重复持有同一只票。
    #    且 sqlite_autoindex 无法 DROP(系统索引)。
    #    正确做法:copy_from 显式声明目标表结构 —— 只保留组合唯一。
    op.add_column("positions", sa.Column("account_id", sa.Integer(), nullable=True))
    op.execute("UPDATE positions SET account_id = 1 WHERE account_id IS NULL")

    positions_new = sa.Table(
        "positions",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("stock_code", sa.String(), nullable=False),
        sa.Column("stock_name", sa.String(), nullable=True),
        sa.Column("shares", sa.Integer(), nullable=False),
        sa.Column("total_cost", sa.String(), nullable=False),
        sa.Column("realized_pnl", sa.String(), nullable=False, server_default="0.00"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"], ["account.id"], name="fk_positions_account", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("account_id", "stock_code", name="uq_position_account_code"),
        sa.Index("idx_positions_account", "account_id"),
    )
    # copy_from 的 MetaData 已声明索引/约束,batch 重建时会一并建好,无需再 create
    with op.batch_alter_table(
        "positions",
        copy_from=positions_new,
        recreate="always",
        table_kwargs={"sqlite_autoincrement": True},
    ) as _batch:
        pass

    # 3) transactions: 加 account_id + 索引
    op.add_column("transactions", sa.Column("account_id", sa.Integer(), nullable=True))
    op.execute("UPDATE transactions SET account_id = 1 WHERE account_id IS NULL")
    with op.batch_alter_table("transactions") as batch:
        batch.alter_column(
            "account_id",
            existing_type=sa.Integer(),
            nullable=False,
            server_default="1",
        )
        batch.create_foreign_key(
            "fk_transactions_account", "account", ["account_id"], ["id"], ondelete="CASCADE"
        )
    op.create_index(
        "idx_transactions_account", "transactions", ["account_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_transactions_account", table_name="transactions")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("fk_transactions_account", type_="foreignkey")
        batch.drop_column("account_id")

    with op.batch_alter_table("positions") as batch:
        batch.drop_constraint("uq_position_account_code", type_="unique")
        batch.drop_constraint("fk_positions_account", type_="foreignkey")
        batch.drop_column("account_id")

    op.drop_table("account")
