"""配置(读取 .env)"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """盘后诊股室后端配置(v2.1:Key 不从 .env 读,从 SQLite 加密表读)"""

    # LLM API Keys(后端 v2.1 改造:不再从 settings 读)
    # 保留 .env 字段用于 v2.0 兼容(自动迁移到 SQLite)
    deepseek_api_key: str = ""
    minimax_api_key: str = ""
    doubao_api_key: str = ""
    llm_default_provider: str = "deepseek"

    # Fernet Key(v2.1:首次启动自动生成写入 .env)
    # 用于加密 SQLite 中的 API Key
    fernet_key: str = ""

    # 数据源
    akshare_enabled: bool = True

    # 数据库
    database_url: str = "sqlite+aiosqlite:///./data.db"

    # 日志
    log_dir: str = "./logs"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

# 确保 logs 目录存在
Path(settings.log_dir).mkdir(parents=True, exist_ok=True)