"""pytest 全局配置:测试 DB 隔离(硬性,2026-08-04 加固)

必须在 import app.* 之前设置 DATABASE_URL,否则 app.db 用开发库。

防误清开发库(GB-001 数据丢失复盘):
- 若 DATABASE_URL 解析后落在仓库真实开发库(backend/data.db)上,直接 fail
- TEST_BACKUP_DIR 注入临时目录,避免测试把空备份写进仓库 backups/
"""
import os
import shutil
import uuid
from pathlib import Path

# 测试临时目录(2026-10 加固):
# 不用 tempfile.mkdtemp —— 它在 Windows 上会用 0o700 生成受限 DACL,
# 沙箱 / 受限令牌进程(CI、非交互会话、DSH sandbox)随后无法在其中建子目录,
# 导致 app.core.config 的 logs.mkdir 直接 PermissionError,整套测试 collect 失败。
# 改为在可写基目录下用普通 makedirs 派生(继承父目录 ACL),并允许环境变量覆盖。
_test_base = Path(os.environ.get("RICH_TEST_TMP") or (Path(__file__).resolve().parents[1] / ".pytest_tmp"))
_test_base.mkdir(parents=True, exist_ok=True)
_tmp = _test_base / f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}"
_tmp.mkdir(parents=True, exist_ok=True)
_test_db = _tmp / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db}"
os.environ["LOG_DIR"] = str(_tmp / "logs")
os.environ["TEST_BACKUP_DIR"] = str(_tmp / "backups")


def _ensure_isolated() -> None:
    """硬性校验:任何情况下测试库都不得指向开发库 data.db"""
    import re

    url = os.environ.get("DATABASE_URL", "")
    m = re.search(r"sqlite(\+aiosqlite)?:///(.*)", url)
    path = Path(m.group(2)) if m else None
    if path is None:
        raise RuntimeError(f"DATABASE_URL 无法解析为文件路径: {url!r}")
    resolved = str(path.resolve()).lower().replace("\\", "/")
    dev_db = str((Path(__file__).resolve().parents[1] / "data.db")).lower().replace("\\", "/")
    if resolved == dev_db or resolved.endswith("/rich/data.db"):
        raise RuntimeError(
            f"测试数据库指向开发库,拒绝执行(防误清数据): {path} "
            f"(DATABASE_URL={url})"
        )


_ensure_isolated()


def _cleanup_tmp() -> None:
    """测试结束清理本次运行的临时目录;设 RICH_KEEP_TEST_TMP=1 可保留现场。"""
    import atexit

    if os.environ.get("RICH_KEEP_TEST_TMP") != "1":
        atexit.register(shutil.rmtree, _tmp, True)


_cleanup_tmp()


from contextlib import contextmanager, ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    """会话开始时把测试库迁移到 head(仅一次)。

    为什么不用 `Base.metadata.create_all`:
      app lifespan 启动时会跑 `alembic upgrade head`。若这里用 create_all 建表,
      `alembic_version` 会是空表,alembic 便以为所有迁移都没跑过,尝试重建已存在的表
      → `alembic upgrade head failed`,进而 300+ 个用 TestClient 的用例全灭。
    因此测试库与生产库走**同一条**迁移路径,schema 天然一致,且 lifespan 的那次调用成为 no-op。

    顺带修掉:各 repo 测试文件各自定义 `_create_tables`,能否建表取决于文件字母序,
    字母序靠前的文件会在别人建表之前跑,报 `no such table`。集中到这里后与顺序无关。
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(backend_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ},  # DATABASE_URL 已由 conftest 顶部注入,子进程继承
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"测试库 alembic upgrade head 失败(code={proc.returncode}):\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    yield


@pytest.fixture(autouse=True)
def _reset_process_state():
    """每个测试前后清空进程级全局状态与库表(2026-10 新增,修复跨测试污染)。

    本项目多处用模块级 dict 做 TTL 缓存 / 单例仓储,在 uvicorn 单进程里是合理的,
    但 pytest 全程复用同一个进程与同一个测试库 —— 上一个测试写入的数据/缓存
    会被下一个测试读到,表现为"单跑全绿、一起跑红"。历史症状:
      - test_daily_analysis::TestWinrateAPI(samples 被别的用例的 seed 覆盖)
      - test_positions_api / test_positions_v040 一组用例(跨文件后失败)

    只清业务表,保留 alembic_version(迁移状态)。
    """
    _clear_global_state()
    _truncate_tables()
    yield
    _clear_global_state()


def _truncate_tables() -> None:
    """清空测试库全部业务表(保留 alembic_version)。

    刻意不做 schema 操作:表结构由各测试的 app 侧 create_all / 迁移建立,
    这里只删数据,避免每个测试重建 schema 的开销。
    """
    if not _test_db.exists():
        return

    import sqlite3

    try:
        conn = sqlite3.connect(_test_db)
    except Exception:  # pragma: no cover - 连不上就跳过,不要因此让测试全灭
        return
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name != 'alembic_version'"
            )
        ]
        if tables:
            conn.execute("PRAGMA foreign_keys=OFF")
            for table in tables:
                conn.execute(f'DELETE FROM "{table}"')
            conn.commit()

        # 重建默认账户(id=1)。
        # 生产库由迁移 e5f60718293a 保证 account id=1 恒存在;测试库是空 schema,
        # 而 positions/transactions 的 account_id 外键默认值为 1,
        # 不播种就会 FOREIGN KEY constraint failed。
        if "account" in tables:
            conn.execute(
                "INSERT INTO account (id, name, kind, is_default, created_at, updated_at) "
                "VALUES (1, '默认账户', 'broker', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
            conn.commit()
    except Exception:  # pragma: no cover
        pass
    finally:
        conn.close()


def _clear_global_state() -> None:
    """清空已知的模块级缓存;模块被 monkeypatch 掉时静默跳过。"""
    # 1) 胜率内存缓存(自带 clear_winrate_cache 钩子)
    try:
        from app.services import daily_analysis_service

        clear = getattr(daily_analysis_service, "clear_winrate_cache", None)
        if clear:
            clear()
    except Exception:
        pass

    # 2) 板块 K 线模块级缓存
    try:
        from app.services import sector_kline_service

        getattr(sector_kline_service, "_cache", {}).clear()
    except Exception:
        pass

    # 3) 事件总线:清掉上一个测试注册的订阅者与积压事件
    try:
        from app.services.event_bus import event_bus

        for attr in ("_subscribers", "_callback_subscribers"):
            container = getattr(event_bus, attr, None)
            if hasattr(container, "clear"):
                container.clear()
    except Exception:
        pass

    # 4) LLM Provider 实例缓存(类级 dict,跨测试存活)
    #    历史症状:test_llm_api::test_switch_provider 全量跑时被前序测试
    #    留在缓存里的旧 client 影响,单跑却绿。
    try:
        from app.llm.factory import provider_factory

        provider_factory.clear_cache()
    except Exception:
        pass

    # 5) 通知去重/限流器(模块级单例,冷却状态会跨测试泄漏)
    try:
        from app.modules.notify.dedupe import limiter

        limiter.reset()
    except Exception:
        pass

    # 6) 选股权重缓存
    try:
        from app.modules.screener.weight_service import invalidate_cache

        invalidate_cache()
    except Exception:
        pass


@contextmanager
def mock_thsifind(
    trending_news: list[dict] | None = None,
    news: list[dict] | None = None,
    notices: list[dict] | None = None,
    securities: list[dict] | None = None,
    fail_on: set[str] | None = None,
):
    """Mock thsifind 工具栏, 用于所有 ifind 相关测试.

    容错: Task 2 写入时, ifind_events/news/fundamentals 模块可能尚未存在
    (Task 3/9/13 才创建). patch 路径不存在时静默跳过, 避免早跑 fixture 报错.

    Args:
        trending_news: search_trending_news 返回值(默认空 list)
        news: search_news 返回值
        notices: search_notice 返回值
        securities: search_securities 返回值(默认 [{'stock_code': '600519.SH', 'hit': True}])
        fail_on: 哪些工具名模拟失败, e.g. {'search_trending_news'}
    """
    fail_on = fail_on or set()
    m = MagicMock()

    def _maybe_fail(name):
        def _raise(*a, **kw):
            raise RuntimeError(f"mocked ifind failure: {name}")
        return _raise

    m.search_trending_news = (
        _maybe_fail("search_trending_news")
        if "search_trending_news" in fail_on
        else AsyncMock(return_value=trending_news if trending_news is not None else [])
    )
    m.search_news = (
        _maybe_fail("search_news")
        if "search_news" in fail_on
        else AsyncMock(return_value=news if news is not None else [])
    )
    m.search_notice = (
        _maybe_fail("search_notice")
        if "search_notice" in fail_on
        else AsyncMock(return_value=notices if notices is not None else [])
    )
    m.search_securities = (
        _maybe_fail("search_securities")
        if "search_securities" in fail_on
        else AsyncMock(return_value=securities if securities is not None else [
            {"stock_code": "600519.SH", "hit": True, "name": "贵州茅台"},
        ])
    )
    m.get_security_indicators = MagicMock(return_value={})
    m.get_stock_summary = MagicMock(return_value={})

    patches = [
        ("app.data.ifind_events", "_search_trending_news", m.search_trending_news),
        ("app.data.ifind_news", "_search_news", m.search_news),
        ("app.data.ifind_news", "_search_notice", m.search_notice),
        ("app.data.ifind_fundamentals", "_search_securities", m.search_securities),
    ]

    with ExitStack() as stack:
        for module_path, attr, mock_obj in patches:
            try:
                stack.enter_context(patch(f"{module_path}.{attr}", mock_obj))
            except (AttributeError, ModuleNotFoundError):
                # 模块尚未创建 (Task 3/9/13 才落地), 跳过此 patch
                pass
        yield m
