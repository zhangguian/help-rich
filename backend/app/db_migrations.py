"""数据库数据迁移(P3.5.1:stock_code 6 位 → 带市场后缀)

幂等:重复执行安全(带后缀的行跳过)。启动时在 create_all 后执行。
"""
import logging

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
            logger.warning("[migrate] %s id=%s code=%r 无法识别市场,跳过", table, row_id, code)
            continue
        await conn.execute(
            text(f"UPDATE {table} SET stock_code=:n WHERE id=:id"),
            {"n": normalized, "id": row_id},
        )
        fixed += 1
    if fixed:
        logger.info("[migrate] %s: %d 行补市场后缀", table, fixed)
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
    logger.info("数据迁移完成(%d 个迁移)", len(MIGRATIONS))
