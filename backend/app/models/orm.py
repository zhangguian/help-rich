"""ORM 模型(v2.1)

从 app.db 直接 import Base(避免循环导入)
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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
# === v0.2.1:K 线缓存表(D) ===
# ============================================================

class KlineCache(Base):
    """单只股票日 K 线缓存(D,TradingView Lightweight Charts)

    MVP:首次请求时 mock 生成 + 落库;v0.2.2 接 akshare/yahoo 真实数据源替换 mock。
    """
    __tablename__ = "kline_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False, default="daily")  # daily/weekly/60min
    open_price: Mapped[str] = mapped_column(String, nullable=False)
    high_price: Mapped[str] = mapped_column(String, nullable=False)
    low_price: Mapped[str] = mapped_column(String, nullable=False)
    close_price: Mapped[str] = mapped_column(String, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String, default="mock")  # mock/akshare/yahoo
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_kline_code_period_date", "stock_code", "period", "trade_date"),
    )

    def __repr__(self) -> str:
        return f"<KlineCache {self.stock_code} {self.period} {self.trade_date}>"


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