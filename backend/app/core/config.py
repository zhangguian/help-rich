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

    # CORS
    # "*" = 开发期允许任意来源(此时必须关闭 credentials,见 main.py)
    # 逗号分隔白名单,例如 "http://127.0.0.1:5173,http://localhost:5173"
    cors_allow_origins: str = "*"

    # 数据保留策略
    # fund_flow 每分钟写约 150 条,前端只读每只股票最近 30 条;
    # 不裁剪会让本地库无限膨胀(实测可达数百 MB),因此按"每只股票最近 N 条"截断
    fund_flow_keep_per_stock: int = 500
    # 裁剪后是否执行 VACUUM 回收空间(会短暂锁库,默认仅启动时执行一次)
    retention_vacuum: bool = True

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


# ============================================================
# === 作战计划 v2:全市场滚动池(选股 universe + 池记忆) ===
# ============================================================

# 滚动池容量 —— 全市场选出的部分(持仓 ∪ ★关注 另外单独全覆盖,不占池席位)
POOL_LIMIT = 5

# 连续多少天未达预期 → 剔除出池
POOL_MISS_THRESHOLD = 3

# universe 闸门:主板非 ST 且成交额达标(亿元)
POOL_MIN_AMOUNT_YI = 1.0

# 次新股阈值:上市不足 60 个交易日 → 剔除
# 判定方式 = 日 K 的**实际根数**(新浪返回上市以来全部日 K,不足 60 根即新股)
POOL_NEW_LISTING_TRADING_DAYS = 60

# 快照粗筛后进入 4 因子精排的候选数(精排要拉 K 线,不能全市场拉)
POOL_PRECANDIDATE_LIMIT = 80

# 精排阶段的 K 线根数(量比 / 连涨天数 / 5 日最大跌幅)
POOL_RANK_KLINE_COUNT = 60

# 精排阶段拉 K 线的并发(沿用 screener 的并发档)
POOL_RANK_KLINE_CONCURRENCY = 16