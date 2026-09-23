"""配置(读取 .env)"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """买股工具室后端配置(v2.1:Key 不从 .env 读,从 SQLite 加密表读)"""

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
        # 环境变量优先于 .env(测试可注入 DATABASE_URL)
        env_priority=True,
    )


settings = Settings()

# 确保 logs 目录存在
Path(settings.log_dir).mkdir(parents=True, exist_ok=True)


# ============================================================
# === v2.6:盘后选股(screener)模块常量(集中可调) ===
# ============================================================

# 候选池:沪深 300 + 中证 500
SCREENER_POOL_INDEX_CODES = ("000300.SH", "000905.SH")

# 跑批调度时间(每个交易日 15:30 收盘后启动;周末/节假日不跑)
SCREENER_RUN_HOUR = 15
SCREENER_RUN_MINUTE = 30

# Top N 入库数
SCREENER_TOP_N = 20

# 评分公式版本(版本变更时落 screener_runs.scoring_version,便于回溯)
SCREENER_SCORING_VERSION = "v1.0"

# === 评分阈值(纯函数;调整后改 SCREENER_SCORING_VERSION 即可重算) ===

# main_net_inflow_score: 板块主力净流入(亿元) → 0..60
#   每 0.5 亿 +5 分,1.0 亿起 30 分,3.0 亿封顶 60 分
SCREENER_MAIN_INFLOW_THRESHOLD_YI = 1.0
SCREENER_MAIN_INFLOW_STEP_YI = 0.5
SCREENER_MAIN_INFLOW_POINTS_STEP = 5
SCREENER_MAIN_INFLOW_MAX = 60

# volume_ratio_score: 量比 → 0..40
SCREENER_VOLUME_RATIO_BREAKPOINTS = (1.5, 2.0, 3.0)  # 三档:20 + 10 + 10
SCREENER_VOLUME_RATIO_MAX = 40

# momentum_score: 涨幅 + 连涨 → 0..30
SCREENER_CHANGE_PCT_RANGE = (3.0, 7.0)  # [low, high] 内拿满分 20
SCREENER_MOMENTUM_BASELINE = 20
SCREENER_CONSECUTIVE_UP_BONUS = 10  # 连涨 ≥2 天 +10
SCREENER_MOMENTUM_MAX = 30

# sector_strength_score: 板块资金榜排名 → 0..25
SCREENER_SECTOR_TOP5_POINTS = 15
SCREENER_SECTOR_TOP6_20_POINTS = 8
SCREENER_SECTOR_CLUSTER_BONUS = 5  # 同板块多只入榜 +5
SCREENER_SECTOR_MAX = 25

# === 入库过滤(过不了连 Top N 都进不了) ===

SCREENER_MIN_AMOUNT_YI = 1.0        # 最小成交额(亿元),过滤流动性极差
SCREENER_MIN_SCORE = 30             # 综合分门槛
SCREENER_MAX_DROP_PCT_5D = -15.0    # 近 5 日跌幅超过 -15% 一律剔除(避雷)

# 改动 A: screener 事件因子加权 (iFinD 驱动)
SCREENER_EVENT_FACTOR_WEIGHT: int = 15
SCREENER_EVENT_KEYWORD_BLACKLIST: list[str] = ["ST", "*ST", "退市"]

# 改动 B: screener Top N 基本面兜底过滤
SCREENER_FUNDAMENTAL_FILTER_ENABLED: bool = True
SCREENER_FUNDAMENTAL_FILTER_QUERY: str = "扣非ROE>0 PE<行业中位数 剔除ST"
SCREENER_FUNDAMENTAL_KICKOUT_PENALTY: int = 30