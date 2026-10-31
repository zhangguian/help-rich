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


# ============================================================
# === K 线异动行为标注(四信号:主力异动 / 低吸 / 锁仓 / 高抛) ===
# ============================================================
#
# 定位:**日线级别的形态回溯标注** —— 回答「历史上某天出现了什么可观测事实」。
# 与 `modules/signal/engine.py`(盘中实时推送)是**两回事**,不要混。
#
# 铁律(与项目既有判定层一致):
# - 缺数据 → 该信号不产出,**绝不编数字**
# - 每条信号必须带**数值依据**(reason 里写清实测值)
# - 只用**当日及之前**的数据 → 可回测、可复现
# - 文案只陈述事实,**不预测涨跌**(项目红线)

# 判定所需的最少 K 线根数(不足 → 该票不产出标注)
# 为什么固定 120:K 线图拉 300 根、找股模块拉 120 根,
# 固定下限 + 尾窗口径 → 同一只票在两处得出**同一批信号**(闭环成立)
BEHAVIOR_MIN_KLINE_COUNT = 120

# 回传给前端的标注最大回看天数(避免响应体过大)
#
# ⚠️ **单位是「日历天」,不是「K 线根数」**(2026-10-31 实测修复):
# 旧值 60 天 → 找股页(120 根 K 线 ≈ 168 日历天)列出的信号有 61%
# 在 K 线上根本不存在(找股页有、K 线上找不到)。
# 现在两条路径都按**日历天**过滤,统一走
# `app/services/behavior_signal_service.py::filter_markers_by_window`。
BEHAVIOR_MARKERS_LOOKBACK_DAYS = 120

# 每类分组在 /latest 响应里返回的明细条数上限(真实总数靠 count 披露)
BEHAVIOR_SCREENER_GROUP_PAGE_N = 60

# --- 主力异动(main_force_move) ---
# 当日超大单净额 > 0 且 主力净占比 ≥ 阈值 且 涨幅 ≥ 阈值 且 放量
#
# ⚠️ **阈值收紧的原因**(真机实测 2026-10-30 全市场 5574 只):
# 初版(50% / 1% / 量比 1.3)在大盘普涨日会命中 908/1121 = 81% 的命中记录,
# **区分度太低** —— 几乎每只涨得多的票都成"主力异动",等于没筛。
# 收紧后(65% / 2% / 量比 1.5)只有资金参与度明显更高的票才命中。
BEHAVIOR_MAIN_FORCE_MIN_R0X_RATIO = 65.0   # 主力净占比 r0x_ratio(%)
BEHAVIOR_MAIN_FORCE_MIN_CHANGE_PCT = 2.0   # 当日涨跌幅(%)
BEHAVIOR_MAIN_FORCE_MIN_VOLUME_RATIO = 1.5  # 量比(vs 前 5 日均量)

# 「强」参考线 —— 与上面的**判定线**分开,用于强度分级与连续强度系数
# 判定线只管「算不算命中」,强线管「命中之后有多强」。
# 连续系数取四个维度的**过线进度**(刚过判定线 = 0, 达到强线 = 1)的均值,
# 这样强弱是连续变化的,不会因为「都算强」而并列同分。
BEHAVIOR_MAIN_FORCE_STRONG_R0X_RATIO = 85.0    # 主力净占比强线(%)
BEHAVIOR_MAIN_FORCE_STRONG_CHANGE_PCT = 7.0    # 涨跌幅强线(%)
BEHAVIOR_MAIN_FORCE_STRONG_VOLUME_RATIO = 3.0  # 量比强线
BEHAVIOR_MAIN_FORCE_STRONG_R0_NET_YI = 5.0      # 超大单净额强线(亿元)
# 强度进度(0~1)≥ 该值 → 强度等级「强」
# ⚠️ 等级与打分**同源**(都基于强度进度),避免出现
# 「等级写着强、分数却排在一般后面」的自相矛盾。
# 0.6 是实测调出来的:真机全市场 455 条主力异动里,进度 ≥ 0.6 的约占三成
# —— 门槛再低(0.45)会让七成都标「强」,徽标就廉价了。
BEHAVIOR_MAIN_FORCE_STRONG_PROGRESS = 0.6

# --- 低吸信号(dip_buy) ---
# 主力净额由负转正 + 下影线实体 + 回踩 MA20 + 缩量或平量
BEHAVIOR_DIP_MIN_MAIN_NET_YI = 0.0         # 主力净额(亿元)转正后的下限
BEHAVIOR_DIP_MIN_SHADOW_BODY_RATIO = 1.5   # 下影 ≥ 实体 × 该系数
BEHAVIOR_DIP_MAX_MA20_DEVIATION_PCT = 3.0  # |close-ma20|/ma20 ≤ 该值(%)
BEHAVIOR_DIP_MAX_VOLUME_RATIO = 1.0        # 量比 ≤ 该值(缩量或平量)

# --- 锁仓信号(lock_position) ---
# 连续 N 日主力净额持续为正 + 期间横盘 + 期间缩量
BEHAVIOR_LOCK_MIN_DAYS = 5                 # 连续主力净流入天数
BEHAVIOR_LOCK_MIN_TOTAL_NET_YI = 0.5       # 累计主力净流入(亿元)
BEHAVIOR_LOCK_MAX_RANGE_PCT = 8.0          # 期间振幅(%)≤ 该值 = 横盘
BEHAVIOR_LOCK_MAX_VOLUME_RATIO = 0.9       # 期间均量 / 前 5 日均量 ≤ 该值 = 缩量

# --- 高抛信号(distribute) ---
# 主力净额由正转负 + 上影线冲高回落 + 近 M 日高位 + 放量
BEHAVIOR_DISTRIBUTE_MAX_MAIN_NET_YI = 0.0  # 主力净额(亿元)转负后的上限
BEHAVIOR_DISTRIBUTE_MIN_SHADOW_BODY_RATIO = 1.5  # 上影 ≥ 实体 × 该系数
BEHAVIOR_DISTRIBUTE_HIGH_WINDOW = 20       # 「近 M 日高位」回看根数
BEHAVIOR_DISTRIBUTE_MAX_HIGH_DISTANCE_PCT = 5.0  # 距 M 日最高价 ≤ 该值(%)
# 放量阈值与主力异动对称(1.5):大盘普跌日同样会大量触发,阈值需一致收紧
BEHAVIOR_DISTRIBUTE_MIN_VOLUME_RATIO = 1.5  # 量比 ≥ 该值(放量)

# 均线回看窗口(低吸回踩 MA20 / 高抛高位判定共用)
BEHAVIOR_MA_WINDOW = 20

# --- 找股模块(behavior_screener) ---
# 全市场快照粗筛后进入逐票算信号的候选数上限
#
# ⚠️ **None = 不截断**(2026-10-31 修复):
# 旧的「取前 120」是**筛选维度与被筛目标的时间窗错配** ——
# 候选池按「当日资金异动强度」排序,打分对象却是历史窗口内的信号,
# 于是「20 天前有强信号、今天资金平淡」的票压根进不了池子。
# 成交额闸门(POOL_MIN_AMOUNT_YI)保留 —— 那是合理的业务闸门。
# 保留该参数供测试与小规模分级验证(传 300 / 600)。
BEHAVIOR_SCREENER_CANDIDATE_LIMIT: int | None = None
# 逐票拉 K 线 / 资金流历史的根数
BEHAVIOR_SCREENER_KLINE_COUNT = 120
BEHAVIOR_SCREENER_FLOW_COUNT = 120
# 逐票并发
BEHAVIOR_SCREENER_CONCURRENCY = 12
# 各信号类型的打分权重(与信号强度相乘得到综合分)
BEHAVIOR_SCREENER_KIND_WEIGHTS: dict[str, float] = {
    "main_force_move": 1.0,
    "dip_buy": 1.2,
    "lock_position": 1.1,
    "distribute": 0.9,
}
# 入库上限(每批最多存多少条命中记录)
BEHAVIOR_SCREENER_TOP_N = 60
# 资金流历史拉取超时(秒) —— 超时即降级,不拖慢 K 线主流程
BEHAVIOR_FUND_FLOW_TIMEOUT_SEC = 3.0
