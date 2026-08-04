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
