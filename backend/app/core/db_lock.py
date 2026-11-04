"""SQLite 全局写锁(v1.1)

问题:SQLite 默认单写锁,多个 async session 同时写会卡住;
aiosqlite 是"伪异步",底层还是同步 sqlite3。
FastAPI 多 BackgroundTasks 并发时,写入会排队。

解决方案:asyncio.Lock 全局写锁。

⚠️ **锁不是万能的**:有些写路径没走这个锁(如 K 线批量落库、各种 repo 的直接 commit),
撞上了 SQLite 仍会抛 `database is locked`。所以 `safe_write` 里加了**短暂重试** ——
宁可多等零点几秒,也不要让用户正在做的操作直接 500。
"""
import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError

T = TypeVar("T")

# 全局写锁:同一时刻只允许 1 个写入
db_write_lock = asyncio.Lock()

# 撞锁重试:次数 × 间隔(递增)
LOCK_RETRY_TIMES = 3
LOCK_RETRY_BASE_DELAY = 0.15


def _is_lock_error(exc: BaseException) -> bool:
    """是不是 SQLite 写锁冲突(而不是真正的 SQL 错误)"""
    if not isinstance(exc, OperationalError):
        return False
    msg = str(getattr(exc, "orig", exc)).lower()
    return "locked" in msg or "busy" in msg


async def safe_write(operation: Callable[[], Awaitable[T]]) -> T:
    """所有写入 SQLite 的操作前必须获取锁。

    示例:
        async with db_write_lock:
            await transaction_repo.create(payload)
    或:
        async def _do_create():
            return await transaction_repo.create(payload)
        return await safe_write(_do_create)

    撞上别的写路径(没走这把锁)时,短暂退避后重试,而不是把 500 甩给用户。
    """
    async with db_write_lock:
        last: OperationalError | None = None
        for attempt in range(LOCK_RETRY_TIMES):
            try:
                return await operation()
            except OperationalError as e:
                if not _is_lock_error(e):
                    raise
                last = e
                if attempt == LOCK_RETRY_TIMES - 1:
                    break
                await asyncio.sleep(LOCK_RETRY_BASE_DELAY * (attempt + 1))
        if last is not None:
            raise last
        raise RuntimeError("safe_write: 未执行任何写入")


__all__ = ["db_write_lock", "safe_write"]