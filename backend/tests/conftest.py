"""pytest 全局配置:测试 DB 隔离

必须在 import app.* 之前设置 DATABASE_URL,否则 app.db 用开发库。
"""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="rich-pytest-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp / 'test.db'}"
os.environ["LOG_DIR"] = str(_tmp / "logs")
