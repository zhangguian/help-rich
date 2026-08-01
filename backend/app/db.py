"""异步数据库连接(SQLAlchemy 2 async + aiosqlite)"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM model 的基类(暂时为空,P2.1 才加 Transaction / Watchlist / TradeScore)"""
    pass


engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入用"""
    async with async_session() as session:
        yield session


__all__ = ["Base", "engine", "async_session", "get_db"]