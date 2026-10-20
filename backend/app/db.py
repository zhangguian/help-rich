"""异步数据库连接(SQLAlchemy 2 async + aiosqlite)

2026-10 加固:
- 开 WAL:读写不互相阻塞(WAL 下读不挡写、写不挡读),配合 busy_timeout
  显著降低多 session 并发时的 `database is locked`
- busy_timeout:遇到写锁自动等待而不是立刻抛异常
- synchronous=NORMAL:WAL 下的安全推荐值,牺牲极端情况下的最后一点持久性
  换取显著更低的 fsync 开销(本地单机工具可接受)
"""
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM model 的基类"""


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _is_memory_db(url: str) -> bool:
    return ":memory:" in url or "mode=memory" in url


def _install_sqlite_pragmas(engine) -> None:
    """每次新建连接时下发 PRAGMA(PRAGMA 是连接级的,不能只设一次)。"""

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):  # pragma: no cover - 引擎钩子
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")  # 10s
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA cache_size=-20000")  # 约 20MB page cache
        finally:
            cursor.close()


_engine_kwargs: dict = {"echo": False, "future": True}

if _is_sqlite(settings.database_url):
    _engine_kwargs["connect_args"] = {"timeout": 30}
    if not _is_memory_db(settings.database_url):
        # aiosqlite 默认 NullPool(每请求新建连接)。文件库改用小连接池复用,
        # 配合 WAL + busy_timeout 降低锁竞争;内存库必须 NullPool(否则多连接
        # 各自看到不同的 :memory: 库)。
        _engine_kwargs["poolclass"] = AsyncAdaptedQueuePool
        _engine_kwargs["pool_size"] = 5
        _engine_kwargs["max_overflow"] = 5
        _engine_kwargs["pool_pre_ping"] = True
        _engine_kwargs["pool_recycle"] = 3600

engine = create_async_engine(settings.database_url, **_engine_kwargs)

if _is_sqlite(settings.database_url):
    _install_sqlite_pragmas(engine)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入用"""
    async with async_session() as session:
        yield session


__all__ = ["Base", "engine", "async_session", "get_db"]
