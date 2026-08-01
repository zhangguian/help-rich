"""Alembic 迁移环境配置(v0.2)

- 从 app.core.settings 读 database_url
- 异步驱动 URL → 同步 URL(alembic sync engine)
- target_metadata = Base.metadata(让 autogenerate 工作)
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app.db import Base

# 导入所有 ORM model,确保 metadata 注册(autogenerate 才能识别)
from app.models import orm  # noqa: F401

# Alembic Config
config = context.config

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# URL 优先级:os.environ["DATABASE_URL"] > alembic.ini > settings
# (测试环境 conftest 通过 os.environ 注入,覆盖 .env 默认值)
import os as _os

if _os.environ.get("DATABASE_URL"):
    _db_url = _os.environ["DATABASE_URL"]
else:
    from app.core.config import settings

    _db_url = settings.database_url

# 转换 async URL → sync URL(alembic 同步引擎)
if _db_url.startswith("sqlite+aiosqlite:///"):
    _db_url = _db_url.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
config.set_main_option("sqlalchemy.url", _db_url)

# target_metadata 供 autogenerate 使用
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """offline 模式:仅输出 SQL,不连 DB"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 限制
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """online 模式:实际执行 SQL"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER TABLE 限制
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()