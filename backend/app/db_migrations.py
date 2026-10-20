"""数据库数据迁移(P3.5.1:stock_code 6 位 → 带市场后缀)

幂等:重复执行安全(带后缀的行跳过)。启动时在 create_all 后执行。
"""
import logging

import sqlalchemy as sa
from sqlalchemy import text

from app.core.stock_code import normalize_code
from app.db import engine

logger = logging.getLogger("app.db_migrations")

MIGRATIONS = []


def migration(fn):
    MIGRATIONS.append(fn)
    return fn


async def _normalize_table(conn, table: str) -> int:
    """把表里所有纯 6 位 stock_code 补为带后缀格式,返回迁移行数"""
    rows = (await conn.execute(text(f"SELECT id, stock_code FROM {table}"))).all()
    fixed = 0
    for row_id, code in rows:
        if "." in code:  # 已带后缀
            continue
        normalized = normalize_code(code)
        if normalized is None:
            logger.warning("[migrate] %s id=%s code=%s 无法识别市场,跳过", table, row_id, code)
            continue
        await conn.execute(
            text(f"UPDATE {table} SET stock_code=:n WHERE id=:id"),
            {"n": normalized, "id": row_id},
        )
        fixed += 1
    if fixed:
        logger.info("[migrate] %s: %s 行补市场后缀", table, fixed)
    return fixed


@migration
async def stock_code_with_market(conn) -> None:
    """transactions / watchlist 的 stock_code 补市场后缀"""
    for table in ("transactions", "watchlist"):
        try:
            await _normalize_table(conn, table)
        except Exception as e:
            logger.warning("[migrate] %s 迁移失败: %s", table, e)


async def run_migrations() -> None:
    """启动时调用(create_all 之后)"""
    async with engine.begin() as conn:
        for fn in MIGRATIONS:
            await fn(conn)
    logger.info("数据迁移完成(%s 个迁移)", len(MIGRATIONS))


async def ensure_schema() -> None:
    """schema 漂移自检:补建**缺失的表**(不动已存在的表)

    **为什么需要**:`alembic upgrade head` 只保证「迁移链上的变更已应用」,
    发现不了「迁移已应用、但表后来被手工删掉」这类漂移。
    2026-10-20 实测:`data.db` 有 31 张表独缺 `kline_cache`,
    而 `alembic_version` 已在 head —— 于是 `upgrade head` 认为无事可做,
    K 线接口与整条分析链路全部 500(`no such table: kline_cache`)。

    **做法**:`Base.metadata.create_all(checkfirst=True)` 默认只建缺失的表,
    已存在的表一个字节都不动。因此可以在 alembic 之后安全调用:
    alembic 保证「已存在的表结构是最新的」,create_all 负责「补上被删的表」。
    列级漂移仍归 alembic 管(create_all 不会给已存在的表加列)。

    **边界**:只补 ORM 里声明过的表。若某表只存在于迁移而不在 ORM
    (如历史遗留),本函数不覆盖 —— 那属于迁移链问题,不是漂移。
    """
    from app.models.orm import Base  # 局部导入:避免循环依赖

    async with engine.begin() as conn:
        inspector = await conn.run_sync(lambda c: sa.inspect(c))
        existing = set(await conn.run_sync(lambda c: sa.inspect(c).get_table_names()))
        expected = set(Base.metadata.tables.keys())
        missing = sorted(expected - existing)
        if not missing:
            logger.info("schema 自检:表结构完整(%s 张表)", len(existing))
            return
        logger.warning(
            "schema 自检:发现缺失表 %s —— 正在补建(迁移已应用但表被删的漂移)",
            ", ".join(missing),
        )
        await conn.run_sync(Base.metadata.create_all)
        logger.info("schema 自检:已补建 %s 张缺失表", len(missing))
