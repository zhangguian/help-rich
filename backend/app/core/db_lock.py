"""SQLite 全局写锁(v1.1)

问题:SQLite 默认单写锁,多个 async session 同时写会卡住;
aiosqlite 是"伪异步",底层还是同步 sqlite3。
FastAPI 多 BackgroundTasks 并发时,写入会排队。

解决方案:asyncio.Lock 全局写锁。
"""
import asyncio
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

# 全局写锁:同一时刻只允许 1 个写入
db_write_lock = asyncio.Lock()


async def safe_write(operation: Callable[[], Awaitable[T]]) -> T:
    """所有写入 SQLite 的操作前必须获取锁。

    示例:
        async with db_write_lock:
            await transaction_repo.create(payload)
    或:
        async def _do_create():
            return await transaction_repo.create(payload)
        return await safe_write(_do_create)
    """
    async with db_write_lock:
        return await operation()


__all__ = ["db_write_lock", "safe_write"]