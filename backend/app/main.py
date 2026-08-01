"""盘后诊股室后端入口(MVP v2.1)"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.calculator import router as calculator_router
from app.api.llm_keys import router as llm_keys_router
from app.api.positions import router as positions_router
from app.api.quotes import router as quotes_router
from app.api.transactions import router as transactions_router
from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.db import Base, engine
from app.db_migrations import run_migrations

# 配置日志(启动时一次)
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭钩子

    v2.1:P1.4 阶段直接 create_all 建表(Alembic 还没启用,P2.1 才切换)。
    """
    # 1. 创建所有表(临时方案,正式用 Alembic 见 backend-arch §6.4)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. 数据迁移(P3.5.1:stock_code 补市场后缀,幂等)
    await run_migrations()

    logger.info(f"盘后诊股室后端启动 — v0.1.0,数据库={settings.database_url}")
    yield
    await engine.dispose()


app = FastAPI(
    title="盘后诊股室",
    version="0.1.0",
    description="个人股票 AI 诊断 Agent — 本地 Web 工具(MVP)",
    lifespan=lifespan,
)

# 注册路由
app.include_router(admin_router, prefix="/api")
app.include_router(calculator_router, prefix="/api")
app.include_router(llm_keys_router, prefix="/api")
app.include_router(transactions_router, prefix="/api")
app.include_router(positions_router, prefix="/api")
app.include_router(quotes_router, prefix="/api")