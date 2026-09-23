"""ORM 模型(v2.1)

从 app.db 直接 import Base(避免循环导入)
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# ============================================================
# === v2.1:llm_api_keys 表(P1.4 实施) ===
# ============================================================

class LlmApiKey(Base):
    """LLM API Key 加密存储(provider 是主键)"""
    __tablename__ = "llm_api_keys"

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    encrypted_key: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def __repr__(self) -> str:
        return f"<LlmApiKey provider={self.provider} configured=True>"


# ============================================================
# === v1.5:llm_settings 表 ===
# ============================================================

class LlmSettings(Base):
    """LLM 设置(单行,记录当前激活 provider)"""
    __tablename__ = "llm_settings"

    id: Mapped[int] = mapped_column(default=1, primary_key=True)
    active_provider: Mapped[str] = mapped_column(String, default="deepseek")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


# ============================================================
# === v2.2:cost_settings 表(GB-001 IR-4 交易费用) ===
# ============================================================

class CostSettings(Base):
    """交易费用设置(单行,id=1,GB-001 IR-4)

    enabled=False 时双口径展示关闭,代价/盈亏完全不含费用(保持旧版行为)。
    """
    __tablename__ = "cost_settings"

    id: Mapped[int] = mapped_column(default=1, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    commission_rate: Mapped[str] = mapped_column(String, default="0.00025")  # 万2.5
    min_commission: Mapped[str] = mapped_column(String, default="5.00")       # 最低佣金
    stamp_tax_rate: Mapped[str] = mapped_column(String, default="0.0005")     # 卖出印花税
    transfer_fee_rate: Mapped[str] = mapped_column(String, default="0.00001")  # 过户费
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


# ============================================================
# === MVP 核心:transactions / watchlist / trade_scores ===
# ============================================================

class Transaction(Base):
    """交易流水表(P2.1 实施)

    v2.1 §4.1.1 / backend-arch §6.1
    """
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)  # 'buy' / 'sell'
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    # 价格:Decimal 存为字符串(精度保护,backend-arch §12.5)
    price: Mapped[str] = mapped_column(String, nullable=False)  # 3 位小数
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now
    )

    # 关联评分(1:1)
    score: Mapped["TradeScore | None"] = relationship(
        "TradeScore", back_populates="transaction", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_transactions_code", "stock_code"),
        Index("idx_transactions_date", "trade_date"),
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.id} {self.action} {self.stock_code}@{self.price}>"


class Watchlist(Base):
    """自选股表(P2.1 实施)

    v2.1 §4.3.5
    """
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")  # manual / diagnosis
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)  # 特别关注星标(v0.5)

    def __repr__(self) -> str:
        return f"<Watchlist {self.stock_code}>"


class TradeScore(Base):
    """评分 + AI 评语表(P2.1 实施)

    v2.1 §4.3.2 / backend-arch §6.1
    """
    __tablename__ = "trade_scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transactions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)  # 0~100
    # 5 维度评分明细:JSON {"集中度": 15, "价格合理性": 12, ...}
    score_breakdown: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    ai_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_status: Mapped[str] = mapped_column(String, default="pending")  # pending / success / failed / no_key
    # v1.5 多 Provider 标签
    ai_provider: Mapped[str] = mapped_column(String, default="deepseek")
    ai_model: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # v1.8 评语价值反馈
    feedback: Mapped[str | None] = mapped_column(String, nullable=True)  # useful / useless / null
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    transaction: Mapped["Transaction"] = relationship(
        "Transaction", back_populates="score"
    )

    __table_args__ = (
        Index("idx_trade_scores_trade", "trade_id"),
    )

    def __repr__(self) -> str:
        return f"<TradeScore trade_id={self.trade_id} score={self.score}>"


# ============================================================
# === v0.4.0:持仓表(主数据,从流水聚合翻转为持仓出发) ===
# ============================================================

class Position(Base):
    """持仓表(v0.4.0 主数据)

    股民真实持仓:手动录入 / 截图导入 / 流水同步维护。
    流水是事件记录(复盘用),持仓由 recalc_position 保证一致:
      持仓 = 导入基准(delta) + 全部流水聚合
    """
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String, nullable=True)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    # 总成本(金额):Decimal 存为字符串(精度保护,与 Transaction.price 一致)
    total_cost: Mapped[str] = mapped_column(String, nullable=False)
    # 已实现盈亏(卖出流水累计)
    realized_pnl: Mapped[str] = mapped_column(String, default="0.00", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def __repr__(self) -> str:
        return f"<Position {self.stock_code} {self.shares}股 @成本={self.total_cost}>"


# ============================================================
# === v2.0:截图识别临时记录(P8.1 实施) ===
# ============================================================

class ScreenshotRecord(Base):
    """截图识别临时记录(backend-arch §6.1 v2.0)

    用户确认后才入库 transactions / watchlist。
    source: ocr_llm(主路径)/ manual_paste(降级)
    status: pending / confirmed / rejected
    """
    __tablename__ = "screenshot_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_items: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    screenshot_type: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="ocr_llm")
    status: Mapped[str] = mapped_column(String, default="pending")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_screenshot_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<ScreenshotRecord {self.id} status={self.status}>"


# ============================================================
# === v0.2:资金流表(E) ===
# ============================================================

class FundFlow(Base):
    """单只股票的资金流入流出事件(E,backend-arch §7.x)

    mock 数据:每分钟 1 条(small_amount 中小单 / medium 中单 / large 大单 / super 特大单)
    SSE 推送给前端实时滚动。
    """
    __tablename__ = "fund_flow"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)  # in / out
    amount: Mapped[str] = mapped_column(String, nullable=False)  # 万元
    category: Mapped[str] = mapped_column(String, nullable=False)  # small/medium/large/super
    source: Mapped[str] = mapped_column(String, default="mock")  # mock/eastmoney/sina
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_fund_flow_code_time", "stock_code", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<FundFlow {self.stock_code} {self.direction} {self.amount}万 @ {self.timestamp}>"


# ============================================================
# === v2.3:复盘记录表(一键复盘持久化,per (股票, 窗口) UPSERT) ===
# ============================================================

class ReplayRecord(Base):
    """股票复盘记录表(v2.3 一键复盘)

    同一 (stock_code, window) 多次复盘只保留最新一条(UNIQUE 约束 + UPSERT)。
    window 取值:1d / 3d / 5d / 10d / 20d / 60d(交易日口径)。
    cache_key 派生:`replay:{stock}:{window_days}:{latest_tx_id}` — 新流水自动失效。
    """
    __tablename__ = "replay_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    window: Mapped[str] = mapped_column(String, nullable=False)  # '1d' / '3d' / ...
    # 评分聚合
    score_avg: Mapped[str | None] = mapped_column(String, nullable=True)  # Decimal-as-string
    dimension_avg: Mapped[str] = mapped_column(Text, nullable=False)  # JSON: {集中度: 12, ...}
    top_issues: Mapped[str] = mapped_column(Text, nullable=False)  # JSON: [{dim, score, hint}, ...]
    # 流水快照(本次复盘窗口内的流水 + 持仓快照,供"对比历史"用)
    summary_snapshot: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    # LLM
    ai_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_status: Mapped[str] = mapped_column(String, default="success")  # success / failed / no_key
    ai_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 缓存失效键:窗口内最新流水 id(0 = 窗口无流水)
    latest_tx_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (
        # 同一 (股票, 窗口) 多次复盘只保留最新一条
        Index("uq_replay_stock_window", "stock_code", "window", unique=True),
    )

    def __repr__(self) -> str:
        return f"<ReplayRecord {self.stock_code} {self.window} score={self.score_avg}>"


# ============================================================
# === v1.5:止损表(P5.1 实施) ===
# ============================================================

class StopLoss(Base):
    """止损设置表(backend-arch §6.1 v1.5)

    stock_code 唯一(每只股票仅 1 个止损设置)
    价格字符串(精度保护,与 Transaction.price 一致)
    """
    __tablename__ = "stop_losses"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    stop_loss_price: Mapped[str] = mapped_column(String, nullable=False)  # 3 位小数
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_sound: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_desktop: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_vibrate: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    def __repr__(self) -> str:
        return f"<StopLoss {self.stock_code} {self.stop_loss_price}>"


# ============================================================
# === v2.4:每日 AI 分析持久化(P0 一键复盘演进) ===
# ============================================================

class DailyAnalysis(Base):
    """每日 AI 分析持久化表(v2.4)

    用户每次点 "开始分析" / "重新分析",把当次结果 UPSERT 到 (stock_code, analysis_date)。
    - analysis_date = K 线最新交易日(语义:对哪天的行情做分析),fallback today
    - 同一天多次生成 UPSERT 覆盖最新(created_at 首写时间,updated_at 最新)
    - 用于后续历史查看 / 方向胜率分析(P1)
    """
    __tablename__ = "daily_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    analysis_date: Mapped[date] = mapped_column(Date, nullable=False)
    # 5 维度均值(Decimal-as-string 精度保护)
    score_avg: Mapped[str | None] = mapped_column(String, nullable=True)
    # JSON 字符串:d {集中度: 12, 价格合理性: 8, ...}
    dimension_avg: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON 字符串:[{dim, score, hint}, ...] 前 3 低分维度
    top_issues: Mapped[str] = mapped_column(Text, nullable=False)
    # LLM view:bullish / bearish / neutral / null(LLM 失败)
    ai_view: Mapped[str | None] = mapped_column(String, nullable=True)
    # LLM 评语全文(用于历史查看)— 旧版单字符串;新版存 rationale 单句
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v2.5:LLM 操作参考结构化 JSON 全文(6 字段 + 可选 t_strategy);
    # 老行 nullable=True → 前端读不到时降级为空对象
    ai_advice_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v2.5.2:完整技术指标 JSON(compute_indicators 输出)— 历史存档/复盘
    indicators_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v2.5.2:LLM 解读完整对象 JSON(view / viewReason / trend / volumeNote / keyLevels /
    # positionStatus / adviceRole / advice / riskWarning)— 历史存档/复盘
    ai_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v2.5.2:信号胜率 JSON(compute_signal_winrate 输出)— 可空(K 线不足时 None)
    signal_winrate_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v2.5.2:当时实时报价相对昨收涨跌幅(百分比小数)— 0.005 = +0.5%
    quote_change_pct: Mapped[str | None] = mapped_column(String, nullable=True)
    # v2.5.2:用户持仓角色 empty/profit/loss
    position_status: Mapped[str | None] = mapped_column(String, nullable=True)
    # v2.5.2:基于持仓成本的盈亏百分比(0.05=+5%)— Decimal-as-string
    cost_basis_pct: Mapped[str | None] = mapped_column(String, nullable=True)
    # 当时实时报价(精度保护)
    current_price: Mapped[str | None] = mapped_column(String, nullable=True)
    # K 线最新交易日(冗余便于查询;与 analysis_date 相同)
    latest_kline_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (
        # 同 (股票, 日期) 多次分析只保留最新一条
        Index(
            "uq_daily_stock_date",
            "stock_code",
            "analysis_date",
            unique=True,
        ),
        # 历史查询按日期倒序
        Index("idx_daily_stock_date_desc", "stock_code", "analysis_date"),
    )

    def __repr__(self) -> str:
        return f"<DailyAnalysis {self.stock_code} {self.analysis_date} view={self.ai_view}>"


# ============================================================
# === v2.6:盘后选股(screener)模块 ===
# ============================================================


class IndexConstituent(Base):
    """沪深300 / 中证500 成分股静态表(v2.6 选股模块)

    初始化脚本:`scripts/init_index_constituents.py`(可重复执行)。
    数据源:东方财富 / 新浪公开接口(guide data-source §5)。
    """
    __tablename__ = "index_constituents"

    id: Mapped[int] = mapped_column(primary_key=True)
    index_code: Mapped[str] = mapped_column(String, nullable=False)  # "000300.SH" / "000905.SH"
    stock_code: Mapped[str] = mapped_column(String, nullable=False)  # "600519.SH"
    stock_name: Mapped[str] = mapped_column(String, nullable=False)
    added_at: Mapped[date] = mapped_column(Date, default=date.today)

    __table_args__ = (
        # 同一股票在同一指数中只出现一次
        UniqueConstraint("index_code", "stock_code", name="uq_index_stock"),
        Index("idx_index_code", "index_code"),
    )

    def __repr__(self) -> str:
        return f"<IndexConstituent {self.index_code} {self.stock_code} {self.stock_name}>"


class ScreenerRun(Base):
    """一次盘后选股批次(v2.6)

    每日(交易日)15:30 后由后台调度器跑一次,落库一批 ScreenerPick。
    run_date 唯一(同一天最多 1 个批次,可手动重跑覆盖)。
    """
    __tablename__ = "screener_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now
    )
    # 评分公式版本(便于回溯 + 阈值变更后追溯)
    scoring_version: Mapped[str] = mapped_column(String, default="v1.0")
    # 候选池大小(沪深300 + 中证500 去重)
    pool_size: Mapped[int] = mapped_column(Integer, default=0)
    # Top N 入库数(默认 20)
    total_picks: Mapped[int] = mapped_column(Integer, default=0)
    # 跑批耗时(秒)— 调优参考
    elapsed_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 备注(失败原因 / 降级提示)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("run_date", name="uq_screener_run_date"),
        Index("idx_screener_runs_date", "run_date"),
    )

    def __repr__(self) -> str:
        return f"<ScreenerRun {self.run_date} picks={self.total_picks} pool={self.pool_size}>"


class ScreenerPick(Base):
    """选股 Top N 中的一条(v2.6)

    每条记录该候选股的综合分 + 各因子明细,供前端展示与 LLM 喂入。
    """
    __tablename__ = "screener_picks"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("screener_runs.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..N
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    stock_name: Mapped[str] = mapped_column(String, nullable=False)
    # 综合得分(0~100)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # 各因子明细(便于前端"为什么被选中"展示 + LLM 喂入)
    main_net_inflow_yi: Mapped[float | None] = mapped_column(Float, nullable=True)  # 板块主力净流入(亿元)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)  # 量比(今日量 / 5日均量)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # 当日涨跌幅(%)
    turnover_proxy: Mapped[float | None] = mapped_column(Float, nullable=True)  # 成交额(亿元)
    consecutive_up_days: Mapped[int] = mapped_column(Integer, default=0)  # 连涨天数
    sector: Mapped[str | None] = mapped_column(String, nullable=True)  # 所属行业
    sector_inflow_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 板块资金榜排名
    # 触发条件 chip(JSON list,供前端展示"为什么被选中")
    triggered_rules: Mapped[str] = mapped_column(Text, default="[]")
    # v2.6.1:本地规则拼接的入选理由(1-2 句中文)— 跑批时生成,NULL 表示旧 run 未补算
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    fundamental_filter_status = Column(String, nullable=True)  # 'passed' / 'kicked' / NULL

    __table_args__ = (
        Index("idx_screener_picks_run", "run_id"),
        # 历史查询某只股票历次入选
        Index("idx_screener_picks_code_date", "stock_code"),
    )

    def __repr__(self) -> str:
        return f"<ScreenerPick run={self.run_id} rank={self.rank} {self.stock_code} score={self.score:.1f}>"


class ScreenerLlmPick(Base):
    """用户主动触发的 LLM 评选结果(v2.6)

    同一 run_id 一天只允许 1 次评选(幂等保护,防重复烧 LLM)。
    picks_json 存 [{rank, stock_code, view, highlights, risks, action}, ...] 共 5 只。
    """
    __tablename__ = "screener_llm_picks"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("screener_runs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now
    )
    # LLM 标识
    model: Mapped[str] = mapped_column(String, nullable=False)
    # 5 只标的的完整结果(JSON 字符串)
    picks_json: Mapped[str] = mapped_column(Text, nullable=False)
    # 摘要(整体一句话总结)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # token 用量 + 估算成本(便于限额)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 失败时存错误
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 状态:success / failed
    status: Mapped[str] = mapped_column(String, default="success")

    def __repr__(self) -> str:
        return f"<ScreenerLlmPick run={self.run_id} model={self.model} status={self.status}>"


# ============================================================
# === v2.6:盘后选股 — 观察池(watchlist) ===
# ============================================================


class ScreenerWatchlist(Base):
    """观察池(v2.6)— 用户从选股页标记的标的

    UNIQUE(stock_code) — 同一只股只能标一次(重复点击 = 取消)
    标选后由后台/懒加载补全 screener_watchlist_daily 逐日 K 线记录。
    """
    __tablename__ = "screener_watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    stock_name: Mapped[str] = mapped_column(String, nullable=False)
    marked_at: Mapped[date] = mapped_column(Date, nullable=False)
    # 标记日收盘价(精度保护 Decimal-as-string)
    marked_close: Mapped[str | None] = mapped_column(String, nullable=True)
    # 标记日涨跌幅(字符串,小数表示:0.05 = +5%)
    marked_change_pct: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active / closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    # 关联 daily records(级联删除)
    daily_records: Mapped[list["ScreenerWatchlistDaily"]] = relationship(
        "ScreenerWatchlistDaily",
        back_populates="watchlist",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ScreenerWatchlist {self.stock_code} marked={self.marked_at} status={self.status}>"


class ScreenerWatchlistDaily(Base):
    """观察池逐日 K 线记录(v2.6)— 标记后每天的股价快照

    数据来源:首次访问观察池时按需拉 60 日 K 线(直连新浪),逐日入库。
    pct_from_marked = (close - marked_close) / marked_close,小数表示
    UNIQUE(watchlist_id, trade_date)— 同一天只有一条
    """
    __tablename__ = "screener_watchlist_daily"

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("screener_watchlist.id", ondelete="CASCADE"),
        nullable=False,
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open_price: Mapped[str] = mapped_column(String, nullable=False)
    high_price: Mapped[str] = mapped_column(String, nullable=False)
    low_price: Mapped[str] = mapped_column(String, nullable=False)
    close_price: Mapped[str] = mapped_column(String, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    # 相对标记日的累计涨跌幅(小数:0.05 = +5%);NULL 表示标记日当日无 close
    pct_from_marked: Mapped[str | None] = mapped_column(String, nullable=True)

    watchlist: Mapped["ScreenerWatchlist"] = relationship(
        "ScreenerWatchlist", back_populates="daily_records"
    )

    __table_args__ = (
        UniqueConstraint("watchlist_id", "trade_date", name="uq_watchlist_trade_date"),
        Index("idx_watchlist_daily_date", "watchlist_id", "trade_date"),
    )

    def __repr__(self) -> str:
        return f"<ScreenerWatchlistDaily {self.watchlist_id} {self.trade_date} pct={self.pct_from_marked}>"


# ============================================================
# === 改动 A:screener 事件因子当日缓存 ===
# ============================================================

class EventFactorCache(Base):
    """screener 事件因子当日缓存 (改动 A)

    - key: trade_date (当日 1 次, 跨日失效)
    - 写表条件: ifind 拉取成功 (失败不写)
    """
    __tablename__ = "event_factor_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    event_keywords_json: Mapped[str] = mapped_column(Text, nullable=False)
    stock_codes_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ifind_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (
        Index("idx_event_factor_cache_trade_date", "trade_date"),
    )

    def __repr__(self) -> str:
        return f"<EventFactorCache {self.trade_date} calls={self.ifind_calls}>"