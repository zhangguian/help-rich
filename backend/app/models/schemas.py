"""Pydantic schemas(API 契约,v2.1)

详细端点说明见 `docs/api-contract/api-contract.md`
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# === 健康检查 ===
# ============================================================

class HealthResponse(BaseModel):
    status: str


# ============================================================
# === LLM Key 管理(v2.1) ===
# ============================================================

class LlmKeysStatus(BaseModel):
    """GET /api/llm/keys 返回"""
    deepseek: bool = False
    minimax: bool = False
    doubao: bool = False


class LlmKeysUpdate(BaseModel):
    """PUT /api/llm/keys body"""
    deepseek: str = ""
    minimax: str = ""
    doubao: str = ""


class LlmTestRequest(BaseModel):
    """POST /api/llm/test body"""
    provider: Literal["deepseek", "minimax", "doubao"]


class LlmTestResponse(BaseModel):
    """POST /api/llm/test 响应"""
    ok: bool
    latency_ms: Optional[int] = None
    error: Optional[str] = None


class LlmProviderItem(BaseModel):
    """GET /api/llm/providers 单项"""
    name: str
    model: str
    configured: bool


class LlmProvidersOut(BaseModel):
    """GET /api/llm/providers 响应"""
    items: list[LlmProviderItem]


class LlmSettingsOut(BaseModel):
    """GET/POST /api/llm/settings 响应"""
    active_provider: str


# ============================================================
# === 交易流水(P2.1 实施) ===
# ============================================================

class PositionCreate(BaseModel):
    """POST /api/positions body(v0.4.0 手动录入/截图导入持仓)

    每股成本价口径:shares × cost_price = total_cost
    """
    stock_code: str
    shares: int = Field(gt=0)
    cost_price: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    stock_name: Optional[str] = None

    @field_validator("stock_code")
    @classmethod
    def _normalize_stock_code(cls, v: str) -> str:
        from app.core.stock_code import normalize_code

        normalized = normalize_code(v)
        if normalized is None:
            raise ValueError("股票代码格式应为 6 位数字或带市场后缀(如 600519.SH)")
        return normalized


class ClearPositionRequest(BaseModel):
    """POST /api/positions/{code}/clear body(v0.4.1 一键清仓 / P-stop-loss-v2)

    price: 清仓卖出价(默认前端调时取实时行情,传 0/不传则视为用当前行情)
    note: 备注(默认"一键清仓")
    """
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    note: Optional[str] = None


class TransactionCreate(BaseModel):
    """POST /api/transactions body

    stock_code: 接受 600519 / 600519.SH / sh600519,统一存规范格式 600519.SH
    """
    stock_code: str
    action: Literal["buy", "sell"]
    shares: int = Field(gt=0)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    trade_date: date
    stock_name: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=200)

    @field_validator("stock_code")
    @classmethod
    def _normalize_stock_code(cls, v: str) -> str:
        from app.core.stock_code import normalize_code

        normalized = normalize_code(v)
        if normalized is None:
            raise ValueError("股票代码格式应为 6 位数字或带市场后缀(如 600519.SH)")
        return normalized


class TransactionUpdate(BaseModel):
    """PATCH /api/transactions/{id} body(只能改 note / shares / price)"""
    shares: Optional[int] = Field(default=None, gt=0)
    price: Optional[Decimal] = Field(default=None, gt=0, max_digits=10, decimal_places=3)
    note: Optional[str] = Field(default=None, max_length=200)


class TransactionOut(BaseModel):
    """GET /api/transactions 返回 + POST 响应"""
    id: int
    stock_code: str
    stock_name: Optional[str] = None
    action: Literal["buy", "sell"]
    shares: int
    price: str  # 字符串保精度
    trade_date: date
    note: Optional[str] = None
    score: Optional[int] = None  # 由 score_repo 关联填充
    created_at: datetime

    @classmethod
    def from_orm_with_score(cls, tx, score: Optional[int] = None) -> "TransactionOut":
        """从 ORM 对象构造 + 关联 score"""
        return cls(
            id=tx.id,
            stock_code=tx.stock_code,
            stock_name=tx.stock_name,
            action=tx.action,
            shares=tx.shares,
            price=tx.price,
            trade_date=tx.trade_date,
            note=tx.note,
            score=score,
            created_at=tx.created_at,
        )

    class Config:
        from_attributes = True


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int


# ============================================================
# === 自选股(P2.1) ===
# ============================================================

class WatchlistAdd(BaseModel):
    """POST /api/watchlist body"""
    stock_code: str
    stock_name: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=200)

    @field_validator("stock_code")
    @classmethod
    def _normalize_stock_code(cls, v: str) -> str:
        from app.core.stock_code import normalize_code

        normalized = normalize_code(v)
        if normalized is None:
            raise ValueError("股票代码格式应为 6 位数字或带市场后缀(如 600519.SH)")
        return normalized


class WatchlistOut(BaseModel):
    """GET /api/watchlist 返回"""
    stock_code: str
    stock_name: Optional[str] = None
    source: str
    note: Optional[str] = None
    added_at: datetime
    is_favorite: bool = False  # v0.5 特别关注

    class Config:
        from_attributes = True


class WatchlistFavoriteUpdate(BaseModel):
    """PATCH /api/watchlist/{code} body(v0.5 特别关注)"""
    is_favorite: bool


class WatchlistListOut(BaseModel):
    items: list[WatchlistOut]


# ============================================================
# === 诊断输出(P4.4 / api-contract §1.5) ===
# ============================================================

class DiagnoseOut(BaseModel):
    """GET /api/diagnose/{trade_id} 响应

    status: pending(未出) / success / no_key / failed
    """
    trade_id: int
    status: str
    score: Optional[int] = None
    breakdown: Optional[dict] = None  # {"集中度": 15, ...}
    ai_comment: Optional[str] = None
    ai_status: Optional[str] = None


class FeedbackUpdate(BaseModel):
    """PUT /api/diagnose/{trade_id}/feedback body(P4.9)"""
    feedback: Optional[Literal["useful", "useless"]] = None


# ============================================================
# === 年度账单(P6.1 / v0.2 预留) ===
# ============================================================

class AnnualReportOut(BaseModel):
    """GET /api/annual-report/{year} 响应"""
    year: int
    realized_profit: str
    realized_loss: str
    net_pnl: str
    closed_count: int
    win_rate: float
    top5_profit: list[dict]
    top5_loss: list[dict]
    no_transactions: bool = False  # v0.4.0:无流水时前端提示"导入持仓或录入流水"


# ============================================================
# === 截图识别(P8 / api-contract §1.6) ===
# ============================================================

class ScreenshotParseOut(BaseModel):
    """POST /api/screenshot/upload 与 parse-paste 响应"""
    record_id: int
    items: list[dict]
    screenshot_type: Optional[str] = None
    ocr_text: Optional[str] = None


class ScreenshotPendingItem(BaseModel):
    """GET /api/screenshot/pending 单项"""
    record_id: int
    items: list[dict]
    screenshot_type: Optional[str] = None
    source: str
    uploaded_at: datetime


class ScreenshotConfirmRequest(BaseModel):
    """POST /api/screenshot/{id}/confirm body(可编辑后确认)"""
    items: list[dict]
    screenshot_type: str


class ScreenshotPasteRequest(BaseModel):
    """POST /api/screenshot/parse-paste body(降级路径)"""
    raw_json: str


# ============================================================
# === 错误响应统一格式 ===
# ============================================================

class ApiError(BaseModel):
    code: str
    message: str
    detail: Optional[dict] = None