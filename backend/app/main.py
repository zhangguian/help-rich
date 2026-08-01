"""买股工具室后端入口(MVP v2.1)"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.annual_report import router as annual_report_router
from app.api.calculator import router as calculator_router
from app.api.diagnose import router as diagnose_router
from app.api.events import router as events_router
from app.api.fund_flow import router as fund_flow_router
from app.api.holdings_health import router as holdings_health_router
from app.api.kline import router as kline_router
from app.api.llm_keys import router as llm_keys_router
from app.api.market import router as market_router
from app.api.positions import router as positions_router
from app.api.provider_stats import router as provider_stats_router
from app.api.quotes import router as quotes_router
from app.api.rebalance import router as rebalance_router
from app.api.risk_report import router as risk_report_router
from app.api.screenshot import router as screenshot_router
from app.api.stop_losses import router as stop_losses_router
from app.api.transactions import router as transactions_router
from app.core.config import settings
from app.core.logging import configure_logging, logger
from app.db import engine

# 配置日志(启动时一次)
configure_logging()
logger = logging.getLogger(__name__)


async def _run_alembic_upgrade() -> None:
    """在 lifespan 中跑 alembic upgrade head(同步子进程,避开 Windows asyncio 子进程问题)"""
    import subprocess
    import sys

    def _run():
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(Path(__file__).resolve().parents[1]),  # backend 目录
            capture_output=True,
            text=True,
            check=False,
        )

    proc = await asyncio.to_thread(_run)
    if proc.returncode != 0:
        logger.error("alembic upgrade 失败:\n%s\n%s", proc.stdout, proc.stderr)
        raise RuntimeError(f"alembic upgrade head failed (code={proc.returncode})")
    logger.info("alembic upgrade head OK: %s", proc.stdout.strip())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭钩子(v0.2:用 Alembic 替代 create_all)"""
    # 1. Alembic 迁移(v0.2 起取代 create_all;新表 / 字段变更通过 alembic revision 自动生成)
    try:
        await _run_alembic_upgrade()
    except Exception as e:
        logger.error("Alembic 启动失败: %s", e)
        raise

    # 2. 资金流新浪调度器(v0.3.2:真实数据,无 mock)— 后台任务,每 60s 拉一次 3 个市场排行
    # 测试环境跳过(测试 conftest 不期望后台无限循环)
    import os as _os

    if not _os.environ.get("PYTEST_CURRENT_TEST"):
        from app.services.fund_flow_service import start_sina_scheduler
        from app.services.sector_fund_flow_service import start_sector_scheduler

        import asyncio as _asyncio

        _asyncio.create_task(start_sina_scheduler(interval_sec=60))
        # v0.4.1:板块资金异动检测(60s 拉一次,异动 publish)
        _asyncio.create_task(start_sector_scheduler(interval_sec=60))

    logger.info(f"买股工具室后端启动 — v0.2.0,数据库={settings.database_url}")
    yield
    await engine.dispose()


app = FastAPI(
    title="买股工具室",
    version="0.1.0",
    description="个人股票投资辅助工具 — 本地 Web 工具(MVP)",
    lifespan=lifespan,
)

# CORS(MVP 单机自用,允许前端 dev server 任意源)
# 生产部署时改为前端域名白名单
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发期允许所有 origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(admin_router, prefix="/api")
app.include_router(annual_report_router, prefix="/api")
app.include_router(calculator_router, prefix="/api")
app.include_router(diagnose_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(fund_flow_router, prefix="/api")
app.include_router(holdings_health_router, prefix="/api")
app.include_router(kline_router, prefix="/api")
app.include_router(llm_keys_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(stop_losses_router, prefix="/api")
app.include_router(transactions_router, prefix="/api")
app.include_router(positions_router, prefix="/api")
app.include_router(provider_stats_router, prefix="/api")
app.include_router(quotes_router, prefix="/api")
app.include_router(rebalance_router, prefix="/api")
app.include_router(risk_report_router, prefix="/api")
app.include_router(screenshot_router, prefix="/api")