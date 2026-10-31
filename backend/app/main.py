"""买股工具室后端入口(MVP v2.1)"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.annual_report import router as annual_report_router
from app.api.backtest import router as backtest_router
from app.api.battle_plan import router as battle_plan_router
from app.api.calculator import router as calculator_router
from app.api.accounts import router as accounts_router
from app.api.assistant import router as assistant_router
from app.api.intraday_review import router as intraday_review_router
from app.modules.analysis.api import router as multi_agent_router
from app.modules.notify.api import router as notify_router
from app.api.onboarding import router as onboarding_router
from app.modules.paper_trading.api import router as paper_trading_router
from app.modules.alert.api import router as price_alerts_router
from app.modules.signal.api import router as signals_router
from app.modules.analysis.workflow_api import router as workflow_router
from app.api.cost_settings import router as cost_settings_router
from app.api.diagnose import router as diagnose_router
from app.api.events import router as events_router
from app.api.fund_flow import router as fund_flow_router
from app.api.holdings_health import router as holdings_health_router
from app.api.kline import router as kline_router
from app.api.llm_keys import router as llm_keys_router
from app.api.market import router as market_router
from app.api.market import sector_router
from app.modules.portfolio.api_positions import router as positions_router
from app.api.provider_stats import router as provider_stats_router
from app.api.quotes import router as quotes_router
from app.api.rebalance import router as rebalance_router
from app.api.reflection_context import router as reflection_context_router
from app.api.risk_report import router as risk_report_router
from app.api.score_calibration import router as score_calibration_router
from app.api.screenshot import router as screenshot_router
from app.modules.screener.api import router as screener_router
from app.api.stock import router as stock_router
from app.api.stop_losses import router as stop_losses_router
from app.modules.portfolio.api_transactions import router as transactions_router
from app.core.config import settings
from app.core.logging import configure_logging, logger

from app import __version__
from app.db import engine

# 配置日志(启动时一次);同时接管标准库 logging(uvicorn / sqlalchemy / alembic)
configure_logging()

# 后台调度任务句柄:必须持有强引用,否则可能被 GC 提前回收
# (表现为"调度器跑着跑着就没了"),且关停时无法优雅 cancel
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    """启动后台任务并登记句柄(供关停时 cancel)。"""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


async def _warmup_market_snapshot() -> None:
    """预热全市场快照缓存(失败不阻断启动)

    全 A 股快照需要翻 56 页(约 3~5 秒)。放在启动后台预热,
    避免首页第一次请求干等 5 秒才渲染出市场情绪卡。
    """
    try:
        from app.data.market_snapshot import fetch_market_snapshot

        rows = await fetch_market_snapshot()
        logger.info("全市场快照预热完成: {} 只", len(rows))
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — 预热失败不影响启动
        logger.warning("全市场快照预热失败(已忽略): {}", e)


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
        logger.error("alembic upgrade 失败:\n{}\n{}", proc.stdout, proc.stderr)
        raise RuntimeError(f"alembic upgrade head failed (code={proc.returncode})")
    logger.info("alembic upgrade head OK: {}", proc.stdout.strip())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭钩子(v0.2:用 Alembic 替代 create_all)"""
    import os as _os

    # 0. 二进制快照备份(GB-001 防丢失:启动前把旧库完整复制一份,失败不阻断启动)
    if not _os.environ.get("PYTEST_CURRENT_TEST"):
        from app.api.admin import create_db_snapshot

        try:
            snap = await asyncio.to_thread(create_db_snapshot)
            if snap:
                logger.info("启动快照备份: {}", snap)
            else:
                logger.warning("启动快照备份失败(已忽略,继续启动)")
        except Exception as e:
            logger.warning("启动快照备份异常(已忽略): {}", e)

    # 1. Alembic 迁移(v0.2 起取代 create_all;新表 / 字段变更通过 alembic revision 自动生成)
    try:
        await _run_alembic_upgrade()
    except Exception as e:
        logger.error(f"Alembic 启动失败: {e}")
        raise

    # 2. 历史数据裁剪(fund_flow 调度器每分钟写约 150 条,无上限会撑爆本地库)
    #    失败不阻断启动:数据多留一天不影响功能
    if not _os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            from app.services.retention import run_retention

            stats = await run_retention()
            if stats.get("deleted"):
                logger.info(
                    f"启动数据裁剪: 删除 {stats['deleted']} 条, fund_flow 剩余 {stats['remaining']} 条"
                )
        except Exception as e:
            logger.warning(f"启动数据裁剪异常(已忽略): {e}")

    # 2.5 schema 漂移自检:补建缺失的表
    #     alembic upgrade head 发现不了「迁移已应用、但表被手工删掉」这类漂移
    #     (实测 2026-10-20:库里有 31 张表独缺 kline_cache,版本号却在 head,
    #      导致 K 线与整条分析链路全部 500)。此处用 create_all(checkfirst=True)
    #      补建缺失表,已存在的表一个字节不动。
    if not _os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            from app.db_migrations import ensure_schema

            await ensure_schema()
        except Exception as e:
            logger.warning(f"schema 自检异常(已忽略): {e}")

    # 3. 资金流新浪调度器(v0.3.2:真实数据,无 mock)— 后台任务,每 60s 拉一次 3 个市场排行
    # 测试环境跳过(测试 conftest 不期望后台无限循环)
    if not _os.environ.get("PYTEST_CURRENT_TEST"):
        from app.services.fund_flow_service import start_sina_scheduler
        from app.modules.paper_trading.scheduler import start_paper_scheduler
        from app.modules.alert.scheduler import start_price_alert_scheduler
        from app.services.sector_fund_flow_service import start_sector_scheduler
        from app.modules.analysis.workflow_scheduler import start_workflow_scheduler
        from app.services.quote_poller import start_quote_poller

        _spawn(start_sina_scheduler(interval_sec=60))
        # v0.4.1:板块资金异动检测(60s 拉一次,异动 publish)
        _spawn(start_sector_scheduler(interval_sec=60))
        # 阶段1:价格提醒扫描(60s 一次,交易时段内)
        _spawn(start_price_alert_scheduler(interval_sec=60))
        # 秒级盯盘行情轮询(2s 一轮,交易时段内;快照经 SSE 推前端)
        _spawn(start_quote_poller(interval_sec=2))
        # 盘中持仓信号(快信号跟行情帧;慢信号每 60s 重算一次触发价)
        from app.modules.signal.scheduler import start_signal_scheduler

        _spawn(start_signal_scheduler(interval_sec=60))
        # 阶段3:模拟盘收盘后净值快照
        _spawn(start_paper_scheduler(interval_sec=1800))
        # 阶段4:三段式 Agent(盘前 08:30 / 盘中 11:30,14:50)
        _spawn(start_workflow_scheduler(interval_sec=60))
        # v2.6:盘后选股调度器(每日 15:30 工作日自动跑批)
        from app.modules.screener.service import start_screener_scheduler

        _spawn(start_screener_scheduler())

        # v0.5.0:全市场快照预热(56 页分页约 3~5s)
        #   不预热的话,首页第一次拉 /market/sentiment 要干等 5 秒才出情绪卡。
        #   放到后台跑,首个用户请求通常已命中 60s 缓存。
        _spawn(_warmup_market_snapshot())

    logger.info(f"买股工具室后端启动 — v{__version__},数据库={settings.database_url}")
    yield

    # 关停:先停后台调度器(否则它们可能与 engine.dispose 抢写 → database is locked)
    for task in list(_BACKGROUND_TASKS):
        task.cancel()
    if _BACKGROUND_TASKS:
        await asyncio.gather(*_BACKGROUND_TASKS, return_exceptions=True)
    _BACKGROUND_TASKS.clear()
    await engine.dispose()
    logger.info("买股工具室后端已关闭")


app = FastAPI(
    title="买股工具室",
    version=__version__,
    description="个人股票投资辅助工具 — 本地 Web 工具(MVP)",
    lifespan=lifespan,
)


def _cors_origins() -> list[str]:
    """CORS 允许来源。

    注意:`allow_origins=["*"]` 与 `allow_credentials=True` 不可同时使用
    —— 带凭证请求的响应头不允许 `*`,浏览器会直接拒绝整个响应。
    本项目无 cookie 鉴权,因此默认走"通配 + 不带凭证";
    一旦需要凭证,必须显式配置 FRONTEND_ORIGINS 白名单。
    """
    raw = settings.cors_allow_origins.strip()
    if not raw or raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


_origins = _cors_origins()

# CORS(MVP 单机自用):dev server 通常是 127.0.0.1:5173
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # 通配来源时必须关闭 credentials,否则浏览器拒绝;白名单模式才允许带凭证
    allow_credentials="*" not in _origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(admin_router, prefix="/api")
app.include_router(annual_report_router, prefix="/api")
app.include_router(calculator_router, prefix="/api")
app.include_router(notify_router, prefix="/api")
app.include_router(price_alerts_router, prefix="/api")
app.include_router(signals_router, prefix="/api")
app.include_router(backtest_router, prefix="/api")
app.include_router(battle_plan_router, prefix="/api")
app.include_router(intraday_review_router, prefix="/api")
app.include_router(assistant_router, prefix="/api")
app.include_router(paper_trading_router, prefix="/api")
app.include_router(multi_agent_router, prefix="/api")
app.include_router(workflow_router, prefix="/api")
app.include_router(accounts_router, prefix="/api")
app.include_router(onboarding_router, prefix="/api")
app.include_router(cost_settings_router, prefix="/api")
app.include_router(diagnose_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(fund_flow_router, prefix="/api")
app.include_router(holdings_health_router, prefix="/api")
app.include_router(kline_router, prefix="/api")
app.include_router(llm_keys_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(sector_router, prefix="/api")
app.include_router(stop_losses_router, prefix="/api")
app.include_router(transactions_router, prefix="/api")
app.include_router(positions_router, prefix="/api")
app.include_router(provider_stats_router, prefix="/api")
app.include_router(quotes_router, prefix="/api")
app.include_router(rebalance_router, prefix="/api")
app.include_router(reflection_context_router, prefix="/api")
app.include_router(risk_report_router, prefix="/api")
app.include_router(score_calibration_router, prefix="/api")
app.include_router(screenshot_router, prefix="/api")
app.include_router(screener_router, prefix="/api")
app.include_router(stock_router, prefix="/api")