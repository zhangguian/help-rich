"""结构化日志(§12.4.1)

使用 loguru,JSON 格式输出,每天轮转,保留 30 天。
"""
import sys
from pathlib import Path

from loguru import logger

from app.core.config import settings

LOG_DIR = Path(settings.log_dir)
LOG_DIR.mkdir(parents=True, exist_ok=True)


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

    return logger


__all__ = ["configure_logging", "logger"]