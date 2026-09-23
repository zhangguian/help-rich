"""pytest 全局配置:测试 DB 隔离(硬性,2026-08-04 加固)

必须在 import app.* 之前设置 DATABASE_URL,否则 app.db 用开发库。

防误清开发库(GB-001 数据丢失复盘):
- 若 DATABASE_URL 解析后落在仓库真实开发库(backend/data.db)上,直接 fail
- TEST_BACKUP_DIR 注入临时目录,避免测试把空备份写进仓库 backups/
"""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="rich-pytest-"))
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


from contextlib import contextmanager, ExitStack
from unittest.mock import AsyncMock, MagicMock, patch


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
