"""结构化日志(§12.4.1)

使用 loguru,JSON 格式输出,每天轮转,保留 30 天。

同时提供 `intercept_standard_logging()`:把标准库 logging(含 uvicorn、
SQLAlchemy、第三方库)转发进 loguru。
项目内 `app/core/logging.py` 统一用 loguru,但 `app/main.py` 历史上误用
`logging.getLogger(__name__)`,那些 INFO 日志(alembic 结果、启动快照路径)
因无 handler 而被静默丢弃 —— 本函数用于兜住这类混用。
"""
import logging
import sys
from pathlib import Path

from loguru import logger

from app.core.config import settings

LOG_DIR = Path(settings.log_dir)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 这些第三方 logger 噪音大,统一降级到 WARNING
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "asyncio",
    "multipart",
    "watchfiles",
)


class _InterceptHandler(logging.Handler):
    """把标准库 LogRecord 转发到 loguru,保留 level 与调用栈深度。"""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - 胶水层
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 找真正的调用方(跳过 logging 自身帧)
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def intercept_standard_logging(level: int = logging.INFO) -> None:
    """接管标准库 logging,使 uvicorn / sqlalchemy 等日志进入 loguru 管道。

    幂等:重复调用不会叠加 handler。
    """
    root = logging.getLogger()
    root.handlers = [_InterceptHandler()]
    root.setLevel(level)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging() -> "logger":
    """配置结构化日志。应在 main.py startup 调用一次。"""
    # 移除 loguru 默认 handler,避免重复输出
    logger.remove()

    # 1) stderr(开发用,人类可读)
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <level>{message}</level>",
        level="INFO",
        colorize=True,
    )

    # 2) 文件(JSON,每天轮转,保留 30 天)
    logger.add(
        LOG_DIR / "rich-{time:YYYY-MM-DD}.log",
        format="{message}",
        serialize=True,  # JSON
        rotation="00:00",
        retention="30 days",
        level="DEBUG",
    )

    # 3) 接管标准库 logging(uvicorn 启动横幅、SQLAlchemy、alembic 等)
    intercept_standard_logging()

    return logger


__all__ = [
    "configure_logging",
    "intercept_standard_logging",
    "logger",
    "LOG_DIR",
]
