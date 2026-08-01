# 后端架构文档:买股工具室

**文档版本**:v2.1
**创建日期**:2026-07-31
**最后更新**:2026-08-01(v2.1 新增 Key UI 输入后端:llm_api_keys 表 + Fernet 加密 + GET/PUT/test 3 端点 + 启动不阻塞)
**文档状态**:已通过实战评审,准备实施

**配套文档**:
- `frontend-architecture.md`(前端架构)
- `data-source-guide.md`(数据源获取指南)
**配套文档**:
- `frontend-architecture.md`(前端架构)
- `project-book.md`(PM 项目书,Source of Truth)
- `ui-ux-design.md`(UI/UX 设计书)

---

## 第 1 章 总体定位

### 1.1 核心职责

买股工具室后端负责:
- **数据存储**:SQLite 持久化交易流水、止损设置、评分、watchlist
- **数据计算**:交易成本计算(纯函数)、评分算法(纯函数)
- **数据集成**:AkShare 行情抓取 + DeepSeek AI 评语
- **数据推送**:SSE 实时推送诊断结果
- **数据导出**:CSV/Excel/JSON 格式

### 1.2 进程模型

```
本机启动两个进程:
- backend:uvicorn :8000(FastAPI)
- frontend:Next.js :5173(开发模式)

启动顺序:先 backend,后 frontend
关闭:任一 Ctrl+C 即可(SQLite 文件锁自动释放)
```

### 1.3 与前端的关系

```
前端(只读)              后端(权威)
─────────────────      ───────────────
HTTP 请求      ────→   API 处理
SSE 订阅       ←────   主动推送
类型生成       ←────   OpenAPI 契约
错误展示       ←────   错误码定义
```

---

## 第 2 章 技术栈

| 项 | 技术 | 版本 |
|---|---|---|
| 运行时 | Python | 3.11+ |
| Web 框架 | FastAPI | 0.115.0 |
| ASGI 服务器 | Uvicorn | 0.32.0 |
| ORM | SQLAlchemy | 2.0.36(async) |
| SQLite 驱动 | aiosqlite | 0.20.0 |
| 数据校验 | Pydantic | 2.9.2 |
| 配置 | python-dotenv | 1.0.1 |
| HTTP 客户端 | httpx | 0.27.2 |
| 行情数据 | akshare | ≥1.13.0 |
| 测试 | pytest | 8.3.3 |
| 异步测试 | pytest-asyncio | 0.24.0 |
| 数值精度 | Python `decimal`(内置) | — |

---

## 第 3 章 目录结构

```
backend/
├── app/
│   ├── main.py                     # FastAPI 入口
│   ├── core/
│   │   ├── config.py               # 配置(读取 .env)
│   │   ├── cost_engine.py          # ⭐ 交易成本计算(纯函数)
│   │   ├── scorer.py               # ⭐ 评分函数(纯函数)
│   │   ├── decimal_helper.py       # Decimal 工具
│   │   └── prompts.py              # AI Prompt 模板
│   ├── api/
│   │   ├── deps.py                 # 依赖注入(DB session)
│   │   ├── transactions.py
│   │   ├── calculator.py
│   │   ├── positions.py
│   │   ├── diagnose.py             # 含 SSE + BackgroundTasks
│   │   ├── stop_loss.py            # v1.5 新增
│   │   ├── annual_report.py        # v1.5 新增
│   │   ├── watchlist.py
│   │   ├── events.py               # SSE 端点
│   │   └── admin.py                # 健康检查
│   ├── services/
│   │   ├── transaction_service.py
│   │   ├── position_service.py
│   │   ├── diagnose_service.py     # 评分 + AI 编排
│   │   ├── stop_loss_service.py
│   │   ├── annual_report_service.py
│   │   └── market_service.py       # AkShare 封装
│   ├── repositories/               # 数据访问层
│   │   ├── transaction_repo.py
│   │   ├── watchlist_repo.py
│   │   ├── stop_loss_repo.py
│   │   └── trade_score_repo.py
│   ├── data/
│   │   ├── base.py                 # DataSource 抽象类(v1.2 新增)
│   │   ├── unified.py              # UnifiedQuote 统一格式(v1.2 新增)
│   │   ├── eastmoney.py            # 东财原生 HTTP(v1.2 新增,MVP 用)
│   │   ├── sina.py                 # 新浪适配器(v1.2 新增,预留)
│   │   ├── chain.py                # 多源降级链(v0.2 用)
│   │   ├── akshare_client.py       # akshare 异步封装(MVP 全市场列表)
│   │   └── cache.py                # 本地 JSON 缓存
│   ├── llm/
│   │   ├── deepseek.py             # DeepSeek 客户端
│   │   └── sanitizer.py            # LLM 数据脱敏
│   ├── models/
│   │   ├── orm.py                  # SQLAlchemy 模型
│   │   └── schemas.py              # Pydantic schemas(API 契约)
│   └── db.py                       # 异步数据库连接
├── tests/
│   ├── test_cost_engine.py         # ⭐ 100% 覆盖
│   ├── test_scorer.py              # ⭐ 100% 覆盖
│   ├── test_calculator_api.py
│   ├── test_diagnose_api.py
│   └── test_stop_loss_api.py
├── scripts/
│   ├── seed_test_data.py           # 测试数据生成
│   └── migrate.py                  # 数据迁移
├── data.db                         # SQLite(运行时生成)
├── .env                            # 环境变量(不提交)
└── requirements.txt
```

---

## 第 4 章 分层架构

### 4.1 分层职责

| 层 | 职责 | 示例 |
|---|---|---|
| **API 层**(`app/api/`) | HTTP 接口 + 入参校验 + SSE 推送 | `POST /api/transactions` |
| **Service 层**(`app/services/`) | 业务编排,跨多个 Repository | `DiagnoseService.score_and_comment()` |
| **Repository 层**(`app/repositories/`) | 数据访问,封装 ORM | `TransactionRepo.list_by_stock()` |
| **Domain 层**(`app/core/`) | 纯函数,可单测 | `cost_engine.calculate_after_transaction()` |
| **Data 层**(`app/data/`) | 外部数据源 | `AkshareClient.get_quote(code)` |
| **LLM 层**(`app/llm/`) | AI 集成 | `DeepSeekClient.chat()` |

### 4.2 调用流向

```
HTTP 请求
  ↓
API 层(校验 + 异常处理 + SSE)
  ↓
Service 层(业务编排)
  ↓
Repository 层(数据访问)
  ↓
ORM / SQLite

(AI 场景)
Service 层
  ↓
LLM 层(DeepSeek)
  ↓
返回结果
```

### 4.3 依赖注入

```python
# api/deps.py
from typing import AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import async_session

async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        yield session

# api/transactions.py
from fastapi import Depends
from app.api.deps import get_db

@router.get("/transactions")
async def list_transactions(db: AsyncSession = Depends(get_db)):
    repo = TransactionRepo(db)
    return await repo.list_all()
```

### 4.4 纯函数与 IO 函数分离原则

- **Domain 层**(`core/`):**只**包含纯函数,无 IO、无副作用
- **其他层**:IO 函数,与外部世界交互

好处:核心算法 100% 可单测,无 mock 需求。

### 4.5 SQLite 全局写锁(v1.1 实战评审)

**问题**:SQLite 默认单写锁,多个 async session 同时写会卡住;aiosqlite 是"伪异步",底层还是同步 sqlite3。FastAPI 多 BackgroundTasks 并发时,写入会排队。

**解决方案**:

```python
# core/db_lock.py
import asyncio

# 全局写锁:同一时刻只允许 1 个写入
db_write_lock = asyncio.Lock()

async def safe_write(operation):
    """所有写入操作前获取锁"""
    async with db_write_lock:
        await operation()
```

**应用场景**:
- `POST /api/transactions`(录入流水)
- BackgroundTasks 中的 `trade_score_repo.upsert()`
- `POST /api/stop-losses`
- `transaction_repo.create()`

**读操作不加锁**(SQLite 读并发 OK)。

**Service 层使用示例**:

```python
# services/transaction_service.py
from app.core.db_lock import db_write_lock

async def create_transaction(payload):
    async def _do_create():
        transaction = await transaction_repo.create(payload)
        return transaction
    return await safe_write(_do_create)
```

### 4.6 并发安全核对清单(v1.4 新增)

> v1.1 只加了写锁,本次**逐路径复核**哪些写操作真的走了锁、哪些没走,以及锁外的并发隐患。

#### 4.6.1 写路径核对表

| # | 写操作 | 路径 | 是否走 `safe_write` | 结论 |
|---|---|---|---|---|
| 1 | 录入流水 | `POST /api/transactions` | ✅ 是(transaction_service) | 通过 |
| 2 | 写入评分 + AI 评语 | BackgroundTasks `score_and_notify` 中 `trade_score_repo.upsert()` | ⚠️ **否(v1.3 漏洞)** | **修复:包 safe_write** |
| 3 | 止损设置 | `POST /api/stop-losses` | ✅ 是 | 通过 |
| 4 | 止损触发标记 | `POST /api/stop-losses/{code}/triggered` | ⚠️ **否** | **修复:包 safe_write** |
| 5 | 加入/移除自选股 | `POST/DELETE /api/watchlist` | ⚠️ **否** | **修复:包 safe_write** |
| 6 | 缓存文件写入 | `JSONCache.set()`(行情缓存) | ⚠️ **否,且非 DB** | 见 4.6.2 原子写 |
| 7 | 数据导出(读) | 导出 CSV/JSON | ✅ 读操作,不加锁 | 通过 |

> **规则**:写 SQLite 的**所有**路径必须 `safe_write`;读操作自由。v1.1 漏了 2/4/5 三条路径,MVP 并发低风险不高,但单测要覆盖。

#### 4.6.2 缓存文件原子写(JSONCache)

**问题**:两个 BackgroundTask 并发写同一缓存文件,可能写坏 JSON(半截文件)。

**解决方案**:先写临时文件再 rename(原子操作):

```python
# data/cache.py
import tempfile, os

def _atomic_write(self, path: Path, content: str):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)  # 原子替换
    except BaseException:
        os.unlink(tmp)
        raise
```

#### 4.6.3 事件循环并发说明

- **单进程单事件循环**:FastAPI 所有协程跑在同一个 event loop 上,`asyncio.Queue`(EventBus)天然线程安全,无需加锁 ✅
- **akshare 同步调用**:经 `asyncio.to_thread` 放到线程池执行——**线程池内不碰 SQLite 写**(只做网络 IO),避免线程级竞争 ✅
- **SQLite 连接**:每个 `async_session` 独立连接,写锁在应用层串行化,不会触发 `database is locked`

#### 4.6.4 并发相关单测

```python
# tests/test_concurrency.py
@pytest.mark.asyncio
async def test_parallel_writes_serialized():
    """并发写 20 笔流水 + 评分,全部成功且无 database is locked"""
    async with asyncio.TaskGroup() as tg:
        for i in range(20):
            tg.create_task(create_transaction(payload_factory(i)))
    # 断言:20 条记录都在
```

---

## 第 5 章 核心模块技术设计

### 5.1 交易成本计算器(Domain 层)

```python
# app/core/cost_engine.py
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

def calculate_after_transaction(
    shares_before: int,
    cost_before: Decimal,
    action: Literal["buy", "sell"],
    tx_shares: int,
    tx_price: Decimal,
) -> dict:
    """加权平均法,纯函数"""
    if tx_shares <= 0:
        raise ValueError("tx_shares must be > 0")
    if tx_price <= 0:
        raise ValueError("tx_price must be > 0")
    
    total_cost_before = cost_before * shares_before
    
    if action == "buy":
        new_shares = shares_before + tx_shares
        new_total_cost = total_cost_before + tx_price * tx_shares
        new_cost = new_total_cost / new_shares
        realized_pnl = Decimal(0)
    elif action == "sell":
        if tx_shares > shares_before:
            raise ValueError(f"Insufficient shares: have {shares_before}")
        new_shares = shares_before - tx_shares
        new_cost = cost_before  # 剩余持仓成本不变
        new_total_cost = total_cost_before - tx_price * tx_shares
        realized_pnl = (tx_price - cost_before) * tx_shares
    
    return {
        "shares_after": new_shares,
        "cost_after": new_cost.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP) if new_shares else None,
        "total_cost_after": new_total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "realized_pnl": realized_pnl.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        "is_closed": new_shares == 0,
    }


def build_pnl_grid(
    cost_after: Decimal,
    shares_after: int,
    pct_range: int = 10,
) -> list:
    """21 档盈亏表,每 1% 一档"""
    rows = []
    for pct in range(-pct_range, pct_range + 1):
        factor = Decimal(1) + Decimal(pct) / Decimal(100)
        price = (cost_after * factor).quantize(Decimal("0.003"), rounding=ROUND_HALF_UP)
        mv = (price * shares_after).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        pnl = (mv - cost_after * shares_after).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rows.append({"pct": pct, "price": price, "market_value": mv, "pnl": pnl})
    return rows
```

### 5.2 评分系统(Domain 层)

```python
# app/core/scorer.py
from decimal import Decimal

def score_trade(
    trade: dict,
    position_before: dict,
    recent_trades: list,
    market_ctx: dict,
    is_in_watchlist: bool,
    all_positions: list,           # v1.3:用于 0 数据降级
) -> dict:
    """5 维度评分,纯函数"""
    breakdown = {}
    
    # 1. 集中度(0 数据降级)
    if len(all_positions) < 3:
        breakdown["集中度"] = 15
    else:
        ...
    
    # 2. 价格合理性
    # 3. 操作间隔(0 数据降级)
    # 4. 市场环境(v1.3 三档)
    # 5. 板块热度
    
    score = max(0, min(100, sum(breakdown.values())))
    return {"score": score, "score_breakdown": breakdown}
```

完整实现见 `project-book.md` 4.3.6。

### 5.3 AI 诊断(BackgroundTasks + SSE)

```python
# api/diagnose.py
from fastapi import BackgroundTasks

@router.post("/diagnose/{trade_id}")
async def trigger_diagnose(trade_id: int, background_tasks: BackgroundTasks):
    """立即返回 trade_id,评分异步推送"""
    background_tasks.add_task(diagnose_service.score_and_notify, trade_id)
    return {"trade_id": trade_id, "status": "pending"}


# services/diagnose_service.py(v1.5 改造:用 ProviderFactory)
import time
from app.llm.factory import ProviderFactory

async def score_and_notify(trade_id: int):
    """评分 + AI 评语,SSE 推送"""
    # 1. 计算评分(纯函数,~10ms)
    score_result = scorer.score_trade(...)
    await trade_score_repo.upsert(trade_id, score_result)
    # 2. SSE 推送评分
    await event_bus.publish({"event": "trade.scored", "trade_id": trade_id, "score": score_result})

    # 3. 取当前激活 provider(从 llm_settings 表)
    active = await llm_settings_repo.get_active()
    llm = ProviderFactory.get(active)

    # 4. 调用 LLM(~5-30s,记录延迟用于 A/B 对比)
    t0 = time.time()
    try:
        prompt = build_prompt(sanitize_for_llm(trade), score_result, is_in_watchlist)
        ai_comment = await llm.chat(system, prompt)
        latency_ms = int((time.time() - t0) * 1000)
    except Exception as e:
        await event_bus.publish({"event": "trade.failed", "trade_id": trade_id, "reason": str(e)})
        return

    # 5. 写评语(带 provider 标签,safe_write)
    async with db_write_lock:
        await trade_score_repo.update_ai_comment(
            trade_id, ai_comment,
            provider=llm.name, model=llm.model_name, latency_ms=latency_ms,
        )

    # 6. SSE 推送(带 provider 信息)
    await event_bus.publish({
        "event": "trade.commented",
        "trade_id": trade_id,
        "comment": ai_comment,
        "provider": llm.name,
        "model": llm.model_name,
        "latency_ms": latency_ms,
    })
```

### 5.4 AkShare 异步包装(v1.1 实战评审)**保留用于全市场列表**

**问题**:akshare 是**同步库**,底层 requests 阻塞;直接 `await akshare.xxx()` 会**阻塞整个事件循环**。

**解决方案**:`asyncio.to_thread` 包装同步调用。

**v1.2 调整**:MVP 阶段**混用策略**:
- **实时行情**:东财原生 HTTP(`eastmoney.py`,httpx 异步,**快且可控**)
- **全市场列表**:akshare(`akshare_client.py`,to_thread 包装,**开发快**)
- **统一格式**:所有数据源返回 `UnifiedQuote`(见 §5.5)

```python
# data/akshare_client.py
import asyncio
import akshare as ak

class AkshareClient:
    """AkShare 异步封装"""
    
    async def get_quote(self, code: str) -> dict:
        """用 asyncio.to_thread 包装同步 ak 调用,避免阻塞事件循环"""
        return await asyncio.to_thread(self._sync_get_quote, code)
    
    async def batch_get_quote(self, codes: list[str]) -> dict[str, dict]:
        """批量拉取,asyncio.gather 并发"""
        tasks = [self.get_quote(code) for code in codes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {
            code: result
            for code, result in zip(codes, results)
            if not isinstance(result, Exception)
        }
    
    def _sync_get_quote(self, code: str) -> dict:
        """同步实现,内部调用"""
        df = ak.stock_zh_a_spot_em()
        row = df[df['代码'] == code].iloc[0]
        return {
            "current_price": Decimal(str(row['最新价'])),
            "prev_close": Decimal(str(row['昨收'])),
            "today_change_pct": float(row['涨跌幅']),
            # ...
        }
```

**性能预算**:
- AkShare 单次调用:< 5s
- 批量(10 只):< 8s(并发)
- 超时:`asyncio.wait_for(self.get_quote(code), timeout=10)`

### 5.5 UnifiedQuote 映射层(v1.2 新增)

**问题**:数据源多(东财/新浪/腾讯/akshare),字段命名混乱(详见 `data-source-guide.md` §1)。如果不归一,业务层会重复写适配代码。

**解决方案**:所有数据源统一返回 `UnifiedQuote`,业务层只用这一种格式。

```python
# data/unified.py
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel

class UnifiedQuote(BaseModel):
    """所有数据源归一为内部统一格式"""
    code: str
    name: str
    current_price: Decimal
    prev_close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    change: Decimal
    change_pct: float
    volume: int
    amount: Decimal
    timestamp: datetime
    
    # 可选字段
    turnover_pct: float | None = None
    pe: float | None = None
    pb: float | None = None
```

```python
# data/base.py
from abc import ABC, abstractmethod

class DataSource(ABC):
    """数据源抽象,支持多源"""
    
    name: str  # "eastmoney" / "sina" / "tencent"
    
    @abstractmethod
    async def get_quote(self, code: str) -> UnifiedQuote: ...
    
    @abstractmethod
    async def get_quotes(self, codes: list[str]) -> list[UnifiedQuote]: ...
    
    @abstractmethod
    async def get_kline(
        self, code: str, period: str = "day", limit: int = 500
    ) -> list[dict]: ...
```

### 5.5.1 东财原生 HTTP 实现(v1.2 新增)

**参考**:`data-source-guide.md` §3.1

```python
# data/eastmoney.py
import httpx
from datetime import datetime
from decimal import Decimal
from app.data.base import DataSource
from app.data.unified import UnifiedQuote

class EastmoneyClient(DataSource):
    name = "eastmoney"
    BASE_URL = "https://push2his.eastmoney.com"
    
    def __init__(self):
        self._cookie: str | None = None
        self._cookie_expires_at: float = 0
    
    async def _ensure_cookie(self):
        """东财需要先访问首页拿 cookie,否则高峰期 401"""
        import time
        if self._cookie and time.time() < self._cookie_expires_at:
            return
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://quote.eastmoney.com/")
            self._cookie = resp.cookies.get("qgqp_b_id", "")
            self._cookie_expires_at = time.time() + 3600  # 1 小时
    
    async def get_quote(self, code: str) -> UnifiedQuote:
        """东财实时行情,基于 K 线接口倒数第二条"""
        await self._ensure_cookie()
        secid = self._to_secid(code)
        url = f"{self.BASE_URL}/api/qt/stock/kline/get"
        params = {
            "secid": secid, "klt": "1", "fqt": "1",
            "end": "20500101", "lmt": "2",  # 最近 2 条,倒数第二条是昨收
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, headers={
                "User-Agent": "Mozilla/5.0",
                "Cookie": self._cookie,
            }, timeout=10.0)
            data = resp.json()["data"]
            latest = data["klines"][-1].split(",")
            # 解析为 UnifiedQuote
            return UnifiedQuote(
                code=code,
                name=data["name"],
                current_price=Decimal(latest[2]),
                prev_close=Decimal(latest[1]),  # 昨收
                open=Decimal(latest[1]),
                high=Decimal(latest[3]),
                low=Decimal(latest[4]),
                change=Decimal(latest[2]) - Decimal(latest[1]),
                change_pct=float(latest[8]),
                volume=int(latest[5]),
                amount=Decimal(latest[6]),
                timestamp=datetime.now(),
            )
    
    def _to_secid(self, code: str) -> str:
        """600519.SH → 1.600519"""
        code, market = code.split(".")
        market_map = {"SH": "1", "SZ": "0", "BJ": "0"}
        return f"{market_map[market]}.{code}"
```

### 5.5.2 akshare 全市场列表(MVP)

```python
# data/akshare_client.py(MVP 阶段保留,只用于全市场列表)
import asyncio
import akshare as ak
from app.data.base import DataSource
from app.data.unified import UnifiedQuote

class AkshareClient(DataSource):
    name = "akshare"
    
    async def get_all_stocks(self) -> list[UnifiedQuote]:
        """全市场股票列表"""
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, lambda: ak.stock_zh_a_spot_em())
        return [
            UnifiedQuote(
                code=f"{row['市场']}.{row['代码']}",  # 标准化
                name=row["名称"],
                current_price=Decimal(str(row["最新价"])),
                prev_close=Decimal(str(row["昨收"])),
                # ...
            )
            for _, row in df.iterrows()
        ]
```

### 5.6 止损提醒 API

```python
# api/stop_loss.py
@router.post("/stop-losses")
async def create_stop_loss(payload: StopLossCreate, db = Depends(get_db)):
    return await safe_write(lambda: stop_loss_repo.upsert(db, payload))

@router.get("/stop-losses")
async def list_stop_losses(db = Depends(get_db)):
    return await stop_loss_repo.list_all(db)
```

止损检测**不在后端**(由前端 15 秒轮询 /api/positions 实现,见前端架构文档)。

### 5.7 年度账单

```python
# services/annual_report_service.py
async def get_annual_report(year: int):
    """年度复盘,聚合查询"""
    closed_positions = await transaction_repo.get_closed_positions_in_year(year)
    
    total_profit = sum(p.realized_pnl for p in closed_positions if p.realized_pnl > 0)
    total_loss = sum(p.realized_pnl for p in closed_positions if p.realized_pnl < 0)
    
    return {
        "year": year,
        "realized_profit": total_profit,
        "realized_loss": abs(total_loss),
        "net_pnl": total_profit + total_loss,
        "win_rate": len([p for p in closed_positions if p.realized_pnl > 0]) / len(closed_positions),
        "top5_profit": sorted(closed_positions, key=lambda p: -p.realized_pnl)[:5],
        "top5_loss": sorted(closed_positions, key=lambda p: p.realized_pnl)[:5],
    }
```

### 5.8 akshare 长期风险与对策(v1.4 新增)

> **风险本质**:akshare 是无官方维护的社区爬虫库,接口依赖上游网站(东财等)的页面结构,上游改版即挂。历史上 `stock_zh_a_spot_em` 已多次变更字段。

#### 5.8.1 风险分级(MVP 实际暴露面)

| 用途 | 数据源 | akshare 挂掉的影响 |
|---|---|---|
| 实时行情 | 东财原生 HTTP(`eastmoney.py`) | **无影响**(不走 akshare) |
| 全市场列表(代码联想) | akshare `stock_zh_a_spot_em` | 联想失效 → 手动输入代码仍可用 |
| 历史 K 线(v0.2) | 待定 | v0.2 再评估 |

> **MVP 已把 akshare 风险降到最低**:唯一依赖是"代码联想"这一**非关键路径**,主路径(流水/计算/诊断)全部不依赖。

#### 5.8.2 四层对策

**1. 版本锁定**
```
requirements.txt 锁定 akshare==x.y.z(精确版本,不用 >=)
升级必须:跑数据准确性测试(§13.3)+ 手工验证联想
```

**2. 封装隔离(已做)**
- 只允许 `data/akshare_client.py` 一处调用,业务层不感知
- 换实现只改一个文件

**3. 失败率监控**
- §12.4.2 已记录 akshare 调用成功率
- **新增规则**:连续失败率 > 20%(当日) → 日志告警 + 设置页显示"代码联想不可用,可手动输入"
- 数据源指南(`data-source-guide.md` §18)保留备选方案

**4. 替代路径(应急)**
- 全市场列表备选:东财全市场列表接口(`push2.eastmoney.com` 行情快照),与实时行情同源,已掌握鉴权方式(见 `data-source-guide.md` §3)
- 应急预案:MVP 阶段 `stock_zh_a_spot_em` 挂掉 → 直接切东财列表,1 小时内可完成

#### 5.8.3 定期体检(每季度)

1. 跑一次全市场列表拉取,确认成功率
2. 检查 akshare 是否有新版本、release notes 是否提到接口变更
3. 与东财列表抽样对账 10 只股票价格(沿用 §13.3 校验规则)

---

## 第 6 章 数据架构

### 6.1 SQLite 表

```sql
-- 交易流水
CREATE TABLE transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL,
  stock_name TEXT,
  action TEXT NOT NULL CHECK(action IN ('buy', 'sell')),
  shares INTEGER NOT NULL CHECK(shares > 0),
  price DECIMAL(10,3) NOT NULL CHECK(price > 0),
  trade_date DATE NOT NULL,
  note TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 自选股(MVP 阶段就建)
CREATE TABLE watchlist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL UNIQUE,
  stock_name TEXT,
  source TEXT DEFAULT 'manual',
  note TEXT,
  added_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 评分 + AI 评语(v1.5 加 ai_provider / ai_model / ai_latency_ms + feedback)
CREATE TABLE trade_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
  score INTEGER NOT NULL,
  score_breakdown TEXT NOT NULL,  -- JSON
  ai_comment TEXT,
  ai_status TEXT DEFAULT 'pending',  -- pending / success / failed
  ai_provider TEXT DEFAULT 'deepseek',  -- v1.5 新增:deepseek/minimax/doubao
  ai_model TEXT,                         -- v1.5 新增:deepseek-chat/abab6.5s-chat/...
  ai_latency_ms INTEGER,                 -- v1.5 新增:用于 A/B 对比
  feedback TEXT,                         -- v1.8 新增:useful/useless/null
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- LLM 设置(v1.5 新增):当前激活 provider(单行表)
CREATE TABLE llm_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),  -- 单行
  active_provider TEXT NOT NULL DEFAULT 'deepseek',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO llm_settings (id, active_provider) VALUES (1, 'deepseek');

-- LLM API Keys(v2.1 新增):加密存储(对应 §11.3)
CREATE TABLE llm_api_keys (
  provider TEXT PRIMARY KEY,            -- deepseek / minimax / doubao
  encrypted_key TEXT NOT NULL,          -- Fernet 密文(44 字节 base64)
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 止损设置(v1.5)
CREATE TABLE stop_losses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stock_code TEXT NOT NULL UNIQUE,
  stop_loss_price DECIMAL(10,3) NOT NULL CHECK(stop_loss_price > 0),
  enabled BOOLEAN DEFAULT 1,
  notify_sound BOOLEAN DEFAULT 1,
  notify_desktop BOOLEAN DEFAULT 1,
  notify_vibrate BOOLEAN DEFAULT 1,
  last_triggered_at DATE,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 截图识别临时记录(v2.0 新增):用户确认后才入库 transactions/watchlist
CREATE TABLE screenshot_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path TEXT,                     -- 主路径用(本地 ~/rich/uploads/{uuid}.jpg);降级路径 NULL
  ocr_text TEXT,                      -- PaddleOCR 提取的原始文本(主路径)
  raw_response TEXT,                  -- LLM 原始 JSON
  parsed_items TEXT NOT NULL,         -- 标准化 JSON
  screenshot_type TEXT,               -- position / transactions / watchlist
  source TEXT DEFAULT 'ocr_llm',      -- ocr_llm / manual_paste(降级)
  status TEXT DEFAULT 'pending',      -- pending / confirmed / rejected
  uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  confirmed_at DATETIME
);
```

### 6.2 索引

```sql
CREATE INDEX idx_transactions_code ON transactions(stock_code);
CREATE INDEX idx_transactions_date ON transactions(trade_date DESC);
CREATE INDEX idx_stop_losses_code ON stop_losses(stock_code);
CREATE INDEX idx_trade_scores_trade ON trade_scores(trade_id);
CREATE INDEX idx_screenshot_status ON screenshot_records(status);  -- v2.0 新增
```

### 6.3 ORM 模型

```python
# models/orm.py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime, date
from decimal import Decimal

class Base(DeclarativeBase):
    pass

class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str]
    stock_name: Mapped[str | None]
    action: Mapped[str]  # 'buy' / 'sell'
    shares: Mapped[int]
    price: Mapped[Decimal]
    trade_date: Mapped[date]
    note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

class TradeScore(Base):
    __tablename__ = "trade_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[int] = mapped_column(unique=True)
    score: Mapped[int]
    score_breakdown: Mapped[str]  # JSON
    ai_comment: Mapped[str | None]
    ai_status: Mapped[str] = mapped_column(default="pending")
    ai_provider: Mapped[str] = mapped_column(default="deepseek")  # v1.5
    ai_model: Mapped[str | None]                                   # v1.5
    ai_latency_ms: Mapped[int | None]                             # v1.5
    feedback: Mapped[str | None]                                   # v1.8
    # ...

class LlmSettings(Base):  # v1.5 新增
    __tablename__ = "llm_settings"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    active_provider: Mapped[str] = mapped_column(default="deepseek")
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now)

class StopLoss(Base):
    __tablename__ = "stop_losses"
    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(unique=True)
    stop_loss_price: Mapped[Decimal]
    enabled: Mapped[bool] = mapped_column(default=True)
    notify_sound: Mapped[bool] = mapped_column(default=True)
    notify_desktop: Mapped[bool] = mapped_column(default=True)
    notify_vibrate: Mapped[bool] = mapped_column(default=True)
    last_triggered_at: Mapped[date | None]
    # ...
```

### 6.4 迁移策略(v1.3 强化:即使 MVP 也用 Alembic)

**问题**:用户用 1 个月后,加新字段(比如 v1.5 加的止损),`create_all()` **不会改已有表**,数据丢失风险。

**解决方案**:即使 MVP 阶段,也用 Alembic。

```bash
# 1. 初始化(启动后端前)
cd backend
alembic init migrations

# 2. 配置 alembic.ini + env.py 指向我们的 metadata
# env.py: target_metadata = Base.metadata

# 3. 首次部署(空数据库)
alembic stamp head

# 4. 后续字段变更
alembic revision --autogenerate -m "add stop_losses table"
alembic upgrade head
```

**MVP 启动流程**:
```python
# main.py 启动时
@app.on_event("startup")
async def startup():
    # 1. 运行 alembic 迁移
    await run_alembic_upgrade()
    # 2. 启动 APScheduler(可选)
    # 3. 启动 EventBus heartbeat
```

**用户升级时**:
- 旧版本用户升级到新版本 → alembic 自动检测 + 迁移
- 不会出现"加字段失败"或"数据丢失"

---

## 第 7 章 API 设计

### 7.1 REST 端点清单(MVP)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/positions` | 持仓列表(含今日盈亏) |
| GET | `/api/transactions` | 流水列表 |
| POST | `/api/transactions` | 录入交易 |
| PATCH | `/api/transactions/{id}` | 修改 |
| DELETE | `/api/transactions/{id}` | 删除 |
| POST | `/api/calculator` | 计算新成本 + 21 档 |
| GET | `/api/diagnose/{trade_id}` | 获取评分(轮询降级) |
| GET | `/api/stop-losses` | 止损列表 |
| POST | `/api/stop-losses` | 设置/更新止损 |
| DELETE | `/api/stop-losses/{code}` | 删除止损 |
| GET | `/api/annual-report/{year}` | 年度账单 |
| GET | `/api/watchlist` | 自选股列表 |
| POST | `/api/watchlist` | 加入自选股 |
| DELETE | `/api/watchlist/{code}` | 移除 |
| GET | `/api/events/sse` | SSE 推送通道 |
| GET | `/api/llm/providers` | 返回可用 provider 列表(v1.5 新增)|
| GET | `/api/llm/settings` | 获取当前激活 provider(v1.5 新增)|
| POST | `/api/llm/settings` | 切换 provider(v1.5 新增)|
| POST | `/api/llm/test` | 测试连接,发 1 个简单 prompt(v1.5 新增)|
| GET | `/api/llm/keys` | 返回 3 个 Provider 的 Key 状态(已配置/未配置,不返回明文,v2.1 新增)|
| PUT | `/api/llm/keys` | 更新 Key(body: {deepseek, minimax, doubao},v2.1 新增)|
| POST | `/api/diagnose/{trade_id}/regenerate` | 用指定 provider 重新生成评语(v1.5 新增,A/B)|
| POST | `/api/screenshot/upload` | 上传截图(multipart)+ 异步识别主路径(v2.0 新增)|
| GET  | `/api/screenshot/pending` | 待确认列表(给前端预览,v2.0 新增)|
| POST | `/api/screenshot/{id}/confirm` | 用户确认入库(v2.0 新增)|
| POST | `/api/screenshot/{id}/reject` | 取消,删除原图(v2.0 新增)|
| POST | `/api/screenshot/parse-paste` | 降级路径:用户粘贴 JSON 解析(v2.0 新增)|

### 7.2 Pydantic Schemas(API 契约)

```python
# models/schemas.py
from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import date, datetime
from typing import Literal

class TransactionCreate(BaseModel):
    stock_code: str = Field(min_length=6, max_length=6)
    action: Literal["buy", "sell"]
    shares: int = Field(gt=0)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=3)
    trade_date: date
    note: str | None = None

class TransactionOut(BaseModel):
    id: int
    stock_code: str
    stock_name: str | None
    action: Literal["buy", "sell"]
    shares: int
    price: Decimal
    trade_date: date
    note: str | None
    score: int | None = None
    created_at: datetime
    
    model_config = {"from_attributes": True}

class PositionOut(BaseModel):
    stock_code: str
    stock_name: str | None
    shares: int
    avg_cost: Decimal
    total_cost: Decimal
    current_price: Decimal | None
    today_pnl: Decimal | None
    today_pnl_pct: float | None
    floating_pnl: Decimal | None
    floating_pnl_pct: float | None

class CalculatorRequest(BaseModel):
    stock_code: str
    action: Literal["buy", "sell"]
    tx_shares: int
    tx_price: Decimal

class CalculatorResponse(BaseModel):
    before: dict
    after: dict
    pnl_grid: list[dict]

class StopLossCreate(BaseModel):
    stock_code: str
    stop_loss_price: Decimal
    enabled: bool = True
    notify_sound: bool = True
    notify_desktop: bool = True
    notify_vibrate: bool = True

class ScreenshotItem(BaseModel):  # v2.0 新增
    stock_code: str
    stock_name: str | None = None
    shares: int
    price: Decimal
    confidence: float = 1.0

class ScreenshotPasteRequest(BaseModel):  # v2.0 新增
    screenshot_type: Literal["position", "transactions", "watchlist"]
    items: list[ScreenshotItem]
    confidence: float = 1.0

class ScreenshotConfirmRequest(BaseModel):  # v2.0 新增
    items: list[ScreenshotItem]
    screenshot_type: Literal["position", "transactions", "watchlist"]

class LlmKeysStatus(BaseModel):  # v2.1 新增
    """GET /api/llm/keys 返回:每个 Provider 的配置状态(不返回明文)"""
    deepseek: bool = False
    minimax: bool = False
    doubao: bool = False

class LlmKeysUpdate(BaseModel):  # v2.1 新增
    """PUT /api/llm/keys body:3 个 Provider 的 Key,空字符串表示不修改/清空"""
    deepseek: str = ""
    minimax: str = ""
    doubao: str = ""

class LlmTestRequest(BaseModel):  # v2.1 新增
    provider: Literal["deepseek", "minimax", "doubao"]
```

### 7.3 错误处理规范

```python
# 统一错误格式
{
    "code": "INSUFFICIENT_SHARES",
    "message": "这只票只剩 800 股了,卖不出 1000 股",
    "detail": {"have": 800, "want": 1000}
}
```

错误码清单:

| 错误码 | HTTP | 含义 |
|---|---|---|
| `INVALID_STOCK_CODE` | 422 | 股票代码格式错误 |
| `INSUFFICIENT_SHARES` | 422 | 卖出股数超过持仓 |
| `INVALID_PRICE` | 422 | 价格 ≤ 0 |
| `STOCK_NOT_FOUND` | 404 | 股票不存在 |
| `LLM_FAILED` | 500 | LLM 调用失败 |
| `AKSHARE_FAILED` | 503 | 行情源不可用 |
| `INTERNAL_ERROR` | 500 | 其他 |

---

## 第 8 章 SSE 推送

### 8.1 端点

```
GET /api/events/sse
```

### 8.2 事件格式

```typescript
// 事件 1:评分完成
data: {"event": "trade.scored", "trade_id": 123, "score": 72, "breakdown": {...}}

// 事件 2:AI 评语完成
data: {"event": "trade.commented", "trade_id": 123, "comment": "..."}

// 事件 3:AI 评语失败
data: {"event": "trade.failed", "trade_id": 123, "reason": "LLM timeout"}

// 事件 4:持仓价格刷新(可选,MVP 暂不实现)
data: {"event": "position.updated", "stock_code": "000001", "current_price": 10.05}
```

### 8.3 内部 Event Bus(v1.1 加心跳 + 死连接清理)

**问题**:浏览器关闭 / 断开 SSE 时,queue 永远不会被消费,**内存泄漏**。

**解决方案**:

```python
# services/event_bus.py
import asyncio
import time
from typing import Any

class EventBus:
    def __init__(self):
        # (client_id, queue, last_active_at)
        self._subscribers: list[tuple[str, asyncio.Queue, float]] = []
        self._cleanup_task: asyncio.Task | None = None
    
    def subscribe(self, client_id: str) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=100)
        self._subscribers.append((client_id, queue, time.time()))
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._heartbeat_loop())
        return queue
    
    def unsubscribe(self, client_id: str):
        self._subscribers = [
            (cid, q, t) for cid, q, t in self._subscribers if cid != client_id
        ]
    
    async def publish(self, event: dict):
        # 只推给活跃的 queue,清理阻塞的
        for client_id, queue, _ in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 死连接,清理
                self.unsubscribe(client_id)
    
    async def _heartbeat_loop(self):
        """每 30s 推 ping,清理 1 分钟无响应的连接"""
        while True:
            await asyncio.sleep(30)
            now = time.time()
            for client_id, queue, last_active in list(self._subscribers):
                try:
                    queue.put_nowait({"event": "ping", "ts": now})
                except asyncio.QueueFull:
                    self.unsubscribe(client_id)
                # 1 分钟无活动视为死连接
                if now - last_active > 60:
                    self.unsubscribe(client_id)

# api/events.py
@router.get("/events/sse")
async def sse_endpoint(request: Request):
    client_id = str(time.time_ns())
    
    async def event_generator():
        queue = event_bus.subscribe(client_id)
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            event_bus.unsubscribe(client_id)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**前端心跳处理**:见 `frontend-architecture.md` §8.1(`onmessage` 中过滤 `event === 'ping'`)。

---

## 第 9 章 AI Provider 抽象层(v1.5 重写)

### 9.0 设计动机

> - **单一 Provider 风险**:DeepSeek 限流/服务挂 = 评语全挂
> - **A/B 价值**:对比 DeepSeek / MiniMax / 豆包,挑最适合交易评语场景的模型
> - **实施成本**:3 个 Provider 共享同一个 sanitizer + Prompt + 重试逻辑,新增 provider 只需写一个 client 类
> - **MVP 用途**:用户手动切换对比评语质量(纯 A/B 测试,不自动跑三方,见 project-book 6.2.4)

### 9.1 BaseLLM 抽象

```python
# llm/base.py
from abc import ABC, abstractmethod

class BaseLLM(ABC):
    name: str  # "deepseek" / "minimax" / "doubao"

    @abstractmethod
    async def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
```

### 9.2 Provider 实现(3 个)

```python
# llm/deepseek.py
class DeepSeekClient(BaseLLM):
    name = "deepseek"
    model_name = "deepseek-chat"
    BASE_URL = "https://api.deepseek.com/v1/chat/completions"
    # OpenAI 兼容,3 次指数退避(2s/4s/8s)

# llm/minimax.py
class MiniMaxClient(BaseLLM):
    name = "minimax"
    model_name = "abab6.5s-chat"
    BASE_URL = "https://api.minimax.chat/v1/text/chatcompletion_v2"
    # MiniMax 自有格式,需消息体适配

# llm/doubao.py
class DoubaoClient(BaseLLM):
    name = "doubao"
    model_name = "doubao-pro-32k"
    BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    # OpenAI 兼容(火山引擎)
```

### 9.3 ProviderFactory

```python
# llm/factory.py
class ProviderFactory:
    _instances: dict[str, BaseLLM] = {}

    @classmethod
    def get(cls, name: str) -> BaseLLM:
        if name not in cls._instances:
            settings = get_settings()
            providers = {
                "deepseek": lambda: DeepSeekClient(settings.deepseek_api_key),
                "minimax": lambda: MiniMaxClient(settings.minimax_api_key),
                "doubao": lambda: DoubaoClient(settings.doubao_api_key),
            }
            if name not in providers:
                raise ValueError(f"Unknown provider: {name}")
            cls._instances[name] = providers[name]()
        return cls._instances[name]

    @classmethod
    def available(cls) -> list[dict]:
        """返回所有已配置 Key 的 provider,前端用于单选列表"""
        settings = get_settings()
        return [
            {"name": "deepseek", "model": "deepseek-chat", "configured": bool(settings.deepseek_api_key)},
            {"name": "minimax", "model": "abab6.5s-chat", "configured": bool(settings.minimax_api_key)},
            {"name": "doubao", "model": "doubao-pro-32k", "configured": bool(settings.doubao_api_key)},
        ]
```

### 9.4 配置(.env)

```
DEEPSEEK_API_KEY=sk-xxx
MINIMAX_API_KEY=xxx
DOUBAO_API_KEY=xxx
LLM_DEFAULT_PROVIDER=deepseek
```

未配置 Key 的 provider 在设置页不可选。

### 9.5 数据脱敏(适用所有 provider)

```python
# llm/sanitizer.py
from typing import Literal

def sanitize_for_llm(trade: dict) -> dict:
    """传给 LLM 前脱敏,只保留股票代码 + 摘要"""
    shares = trade.get("shares", 0)
    shares_bucket = bucket_shares(shares)

    return {
        "stock_code": trade["stock_code"],
        "stock_name": trade.get("stock_name", ""),
        "action": trade["action"],
        "shares_bucket": shares_bucket,  # 100 / 500 / 1000 / 5000+
        "trade_date": trade.get("trade_date"),
        "concentration_pct": trade.get("concentration_pct"),  # v1.5 新增:持仓占比
        # 不传:价格、金额、持仓成本
    }

def bucket_shares(shares: int) -> str:
    if shares < 100:    return "<100"
    elif shares < 500:  return "100-500"
    elif shares < 1000: return "500-1000"
    elif shares < 5000: return "1000-5000"
    else:               return "5000+"
```

### 9.6 Prompt 模板(适用所有 provider)

```python
# core/prompts.py
DIAGNOSE_SYSTEM = """你是克制的复盘助手,2~3 句话讲清楚,只基于给定数据,不预测涨跌,末尾固定加"以上不构成投资建议"。"""

DIAGNOSE_USER_TEMPLATE = """
数据:
- 本次交易:{stock_code} {stock_name} {action} {shares_bucket}股
- 持仓占比:{concentration_pct}%
- 历史最近 5 笔:{recent_summary}
- 评分:{score} 分,各维度:{breakdown}
- 自选股状态:{is_in_watchlist}

任务:
1) 指出本次操作的主要问题(或亮点)
2) 下次类似场景的改进建议(1 句)
"""
```

---

## 第 9.7 章 截图识别服务(v2.0 新增)

### 9.7.1 设计原则

- **OCR 在本地完成**(PaddleOCR 离线,Win11 + Python 3.13 兼容,详见 §5.8 akshare 类似处理)
- **LLM 只接收文本**,不接收图片(隐私友好)
- **视觉 LLM 不强求**(Provider 可不支持)
- **降级路径**:用户外网可识图模型 + 我们的 Prompt + 粘贴 JSON

### 9.7.2 模块结构

```
backend/app/
├── ocr/
│   ├── paddle_client.py     # PaddleOCR 异步封装(lazy init)
│   └── text_extract.py      # OCR 文本 → 字段提取(同花顺布局规则)
├── llm/
│   └── vision_prompt.py     # Prompt 模板(同 project-book §4.10.4)
└── services/
    └── screenshot_service.py  # 编排:OCR + LLM 或降级解析
```

### 9.7.3 主路径:OCR + LLM

```python
# services/screenshot_service.py
class ScreenshotService:
    async def parse_from_image(self, file_bytes: bytes, filename: str) -> dict:
        # 1. 保存原图到 ~/rich/uploads/{uuid}.jpg(本地,不上传)
        file_path = await self._save_upload(file_bytes, filename)

        # 2. OCR 提取文本(asyncio.to_thread)
        ocr_text = await paddle_client.extract_text(file_path)

        # 3. LLM 解析(用当前 Provider,仅文本,不接收图片)
        active = await llm_settings_repo.get_active()
        llm = ProviderFactory.get(active)
        prompt = build_ocr_prompt(ocr_text)
        raw = await llm.chat(OCR_SYSTEM, prompt)

        # 4. JSON 解析 + 字段校验
        items = parse_and_validate(raw)

        # 5. 写 screenshot_records(status='pending', source='ocr_llm')
        record = await screenshot_repo.create(
            file_path=file_path, ocr_text=ocr_text,
            raw_response=raw, parsed_items=items, status='pending',
        )

        # 6. 返回 record_id + items 给前端预览
        return {"record_id": record.id, "items": items, "ocr_text": ocr_text}

    async def confirm(self, record_id: int, items: list[dict], screenshot_type: str):
        """用户确认后,根据 screenshot_type 写入对应表"""
        async with db_write_lock:  # 写入必须 safe_write
            if screenshot_type == "transactions":
                for item in items:
                    await transaction_repo.create(item)
            elif screenshot_type == "watchlist":
                for item in items:
                    await watchlist_repo.create(item)
            # 更新 screenshot_records.status = 'confirmed'
            await screenshot_repo.mark_confirmed(record_id)
```

### 9.7.4 降级路径:粘贴 JSON 解析

```python
async def parse_from_paste(self, raw_json: str) -> dict:
    """用户粘贴外网模型输出,直接解析(无 LLM 调用)"""
    # 1. JSON 解析(try/except → 422 + 友好提示)
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        raise ScreenshotError(f"JSON 格式错误: {e}", code="INVALID_JSON")

    # 2. 字段校验(Pydantic)
    payload = ScreenshotPasteRequest(**data)  # 校验失败抛 422

    # 3. 标准化 items
    items = parse_and_validate(payload.model_dump_json())

    # 4. 写 screenshot_records(source='manual_paste', file_path=NULL)
    record = await screenshot_repo.create(
        file_path=None, ocr_text=None,
        raw_response=raw_json, parsed_items=items, status='pending',
        source='manual_paste',
    )

    return {"record_id": record.id, "items": items}
```

### 9.7.5 Prompt 模板

`llm/vision_prompt.py`:

```python
OCR_SYSTEM = """你是同花顺 App 截图 OCR 文本解析专家。从 OCR 提取的文本中识别持仓 / 流水 / 自选股字段,返回合法 JSON。"""

OCR_USER_TEMPLATE = """
OCR 提取文本:
\"\"\"
{ocr_text}
\"\"\"

字段定义:
- 持仓:{stock_code(6位), stock_name, shares(int), cost_price(3位小数), market_value(2位小数)}
- 流水:{stock_code, stock_name, action(buy/sell), shares(int), price(3位小数), trade_date(YYYY-MM-DD)}
- 自选股:{stock_code, stock_name}

输出合法 JSON:
{{
  "screenshot_type": "position | transactions | watchlist",
  "items": [ ... ],
  "confidence": 0.0~1.0,
  "notes": "..."
}}

约束:代码读不清就标 confidence < 0.5;价格只取 OCR 数字,不要估算;JSON 合法无尾逗号。
"""
```

### 9.7.6 PaddleOCR 异步封装

```python
# ocr/paddle_client.py
import asyncio
from paddleocr import PaddleOCR

class PaddleOCRClient:
    def __init__(self):
        # lazy init:首次调用才加载模型(~50MB)
        self._ocr = None

    async def extract_text(self, image_path: str) -> str:
        if self._ocr is None:
            self._ocr = await asyncio.to_thread(
                PaddleOCR, use_angle_cls=True, lang="ch"
            )
        result = await asyncio.to_thread(self._ocr.ocr, image_path, cls=True)
        return self._format_result(result)

    def _format_result(self, result) -> str:
        # 拼接所有识别文本,行分隔
        lines = []
        for line in result[0]:
            text = line[1][0]
            conf = line[1][1]
            if conf > 0.5:  # 置信度过滤
                lines.append(text)
        return "\n".join(lines)
```

### 9.7.7 字段提取规则(同花顺布局)

`ocr/text_extract.py`:基于同花顺 App 截图布局做正则匹配 + 行扫描:

- **持仓页**:每行匹配 `代码 + 名称 + 股数 + 成本价 + 市值`(顺序固定)
- **流水页**:每行匹配 `日期 + 代码 + 名称 + 操作 + 股数 + 价格`
- **自选股页**:每行匹配 `代码 + 名称`

> **实施前风险 R22**:PaddleOCR 在 Win11 + Python 3.13 兼容性需实测;若装包失败,备选 `easyocr`(更轻量,中文好,速度慢)或 `pytesseract`(需额外装 tesseract 二进制)。

### 9.7.8 隐私与安全

- 截图原图**只存本地**(`~/rich/uploads/`)
- LLM **不接收图片**(主路径只用 OCR 文本)
- 降级路径用户**自决**——是否上传外网模型由用户自己选,我们不背锅
- 截图随数据库备份(`backups/`)走,失败迁移时一并保留

### 9.7.9 失败模式

| 场景 | 行为 | 用户感知 |
|---|---|---|
| OCR 失败(PaddleOCR 报错) | 走降级路径,提示用户粘贴 JSON | 弹"OCR 失败,可粘贴外网模型输出"|
| OCR 置信度低(< 0.5)| 该行不送给 LLM,在 items 中标记 `low_confidence: true` | 预览表格对应行变红,可手动改 |
| LLM 返回非法 JSON | 重试 1 次,失败则提示用户粘贴降级 | 弹"识别失败,可粘贴外网模型输出"|
| 图片格式不支持(非 jpg/png/webp)| 后端 415 + 友好提示 | "暂只支持 jpg / png / webp 格式" |
| 图片 > 5MB | 前端压缩 + 后端再校验 | "图片过大,请压缩后重试" |
| Provider 不支持视觉 | 自动检测 chat() 调用成功 → 走 OCR 文本解析 | 弹"已用 OCR + 文本模式识别" |

---

## 第 10 章 异步任务

### 10.1 BackgroundTasks 使用

```python
from fastapi import BackgroundTasks

@router.post("/transactions")
async def create_transaction(
    payload: TransactionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # 1. 同步:写入 transactions
    transaction = await transaction_repo.create(db, payload)
    
    # 2. 异步:触发诊断
    background_tasks.add_task(
        diagnose_service.score_and_notify,
        trade_id=transaction.id,
    )
    
    # 3. 同步返回(SSE 后续推送)
    return TransactionOut.model_validate(transaction)
```

### 10.2 任务编排

```
POST /api/transactions
  ├─ 同步:写入 transactions(~5ms)
  ├─ 异步:add_task(score_and_notify)
  └─ 立即返回 transaction_out

[BackgroundTasks 执行]
score_and_notify(trade_id)
  ├─ 计算评分(纯函数,~10ms)
  ├─ 写入 trade_scores(~5ms)
  ├─ SSE 推送 trade.scored
  ├─ 调用 DeepSeek(~5-30s)
  ├─ 更新 ai_comment(~5ms)
  └─ SSE 推送 trade.commented / trade.failed
```

### 10.3 失败重试

- LLM 调用:3 次指数退避(2s, 4s, 8s)
- AkShare 调用:3 次,间隔 1s
- 评分计算:纯函数,无重试必要

---

## 第 11 章 安全与隐私

### 11.1 LLM 数据脱敏(见 9.2)

### 11.2 配置安全

```python
# core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    deepseek_api_key: str = ""           # v1.5:允许为空(未配置)
    minimax_api_key: str = ""            # v1.5 新增
    doubao_api_key: str = ""             # v1.5 新增
    llm_default_provider: str = "deepseek"  # v1.5 新增:deepseek/minimax/doubao
    akshare_enabled: bool = True
    database_url: str = "sqlite+aiosqlite:///./data.db"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
```

`.env` 文件(不提交):
```
# v2.1:FERNET_KEY 用于加密 API Key(首次启动自动生成)
FERNET_KEY=<auto-generated-44-bytes-base64>
# v2.1:DEEPSEEK_API_KEY 等不在 .env 存储,而是用户通过设置页 UI 输入
# (保留兼容:若 .env 仍有 Key,启动时自动导入到 SQLite 加密存储)
DEEPSEEK_API_KEY=
MINIMAX_API_KEY=
DOUBAO_API_KEY=
```

`.gitignore`:
```
.env
data.db
backups/
__pycache__/
```

### 11.3 LLM API Key 加密存储(v2.1 新增)

> **设计动机**:用户通过设置页 UI 输入 API Key(不读 .env),需要本地加密存储以避免明文落库。

#### 11.3.1 加密方案

**选型**:`cryptography.fernet`(AES-128-CBC + HMAC,Python 标准库)

```
明文 Key(deepseek: "sk-abc...")
   ↓
Fernet(FERNET_KEY).encrypt(明文)  → 密文(44 字节 base64)
   ↓
存 SQLite llm_api_keys.encrypted_key
```

#### 11.3.2 FERNET_KEY 管理

- **存储位置**:`.env` 的 `FERNET_KEY=xxx`(44 字节 base64)
- **自动生成**:用户首次启动检测 .env 缺 `FERNET_KEY`,自动生成并写入,提示用户"已自动生成 Fernet Key,请勿手动修改"
- **不可手动改**:若丢失,已存 Key **无法解密**,必须重新输入

```python
# core/crypto.py
from cryptography.fernet import Fernet
from pathlib import Path

class CryptoManager:
    def __init__(self, fernet_key: str | None = None):
        if not fernet_key:
            fernet_key = Fernet.generate_key().decode()
            # 写入 .env
            env_path = Path(".env")
            with env_path.open("a", encoding="utf-8") as f:
                f.write(f"\nFERNET_KEY={fernet_key}\n")
        self.cipher = Fernet(fernet_key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self.cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        return self.cipher.decrypt(ciphertext.encode()).decode()
```

#### 11.3.3 存储与读取

```python
# repositories/llm_keys_repo.py
class LlmKeysRepository:
    async def upsert(self, provider: str, plaintext_key: str):
        encrypted = crypto_manager.encrypt(plaintext_key)
        # SQLite upsert

    async def get_decrypted(self, provider: str) -> str | None:
        """返回解密后的 Key,缺 Key 时返回 None(不抛错)"""
        row = await self.get(provider)
        if row is None:
            return None
        try:
            return crypto_manager.decrypt(row.encrypted_key)
        except InvalidToken:
            # FERNET_KEY 变更导致无法解密
            return None
```

#### 11.3.4 ProviderFactory 改造(v2.1)

**原行为**:从 settings 取 Key(Key 必填)
**新行为**:从 llm_api_keys 表取解密 Key,**缺 Key 时返回 None**

```python
# llm/factory.py(v2.1 改造)
class ProviderFactory:
    _instances: dict[str, BaseLLM] = {}

    @classmethod
    async def get(cls, name: str) -> BaseLLM | None:  # v2.1:加 async + 可能 None
        if name not in cls._instances:
            key = await llm_keys_repo.get_decrypted(name)
            if key is None:
                return None  # v2.1:缺 Key 不抛错
            providers = {
                "deepseek": lambda k: DeepSeekClient(k),
                "minimax": lambda k: MiniMaxClient(k),
                "doubao": lambda k: DoubaoClient(k),
            }
            cls._instances[name] = providers[name](key)
        return cls._instances[name]
```

#### 11.3.5 DiagnoseService 优雅降级(v2.1)

```python
# services/diagnose_service.py(v2.1 改造)
async def score_and_notify(trade_id: int):
    ...
    active = await llm_settings_repo.get_active()
    llm = await ProviderFactory.get(active)

    if llm is None:
        # v2.1:缺 Key 时优雅降级,评分仍出,推 trade.failed
        async with db_write_lock:
            await trade_score_repo.update_ai_status(trade_id, "no_key")
        await event_bus.publish({
            "event": "trade.failed",
            "trade_id": trade_id,
            "reason": f"{active} 未配置 Key,请到设置页填写",
        })
        return

    # 正常 LLM 调用流程不变
    ...
```

#### 11.3.6 .env 兼容迁移

若用户从 v2.0 升级,`.env` 已有 Key:
- 启动时检测 `llm_api_keys` 表为空但 `.env` 有 Key
- **自动迁移**:将 `.env` 的 Key 加密写入 SQLite
- 清空 `.env` 的 Key 行(留 `FERNET_KEY`)
- 用户下次启动时设置页"已配置"状态

#### 11.3.7 失败模式

| 场景 | 行为 |
|---|---|
| 用户从未填过 Key,触发诊断 | 评分仍出,评语区显示"Provider 未配置 Key,请到设置页填写" |
| 用户填了无效 Key,触发诊断 | 评分仍出,评语区显示"Key 无效,请检查设置页" |
| FERNET_KEY 丢失/被改 | 已存 Key 全部失效,提示用户重新输入 |
| 加密失败(InvalidToken) | 返回 None,优雅降级 |
| Key 解密超时 | 同 InvalidToken |

---

### 11.4 日志策略(v2.1 章节号顺延)

```python
# 配置 logging,不记录敏感字段
import logging

logger = logging.getLogger("rich")

# 不记录:价格、金额、API Key
# 记录:API 路径、错误堆栈、响应时间
```

---

## 第 12 章 性能与可靠性

### 12.1 性能预算

| 操作 | 目标 |
|---|---|
| 持仓聚合 | < 50ms |
| 21 档计算 | < 10ms |
| 评分计算 | < 100ms |
| 流水录入响应 | < 200ms |
| 评分 SSE 推送 | < 1s |
| AI 评语 SSE | < 30s |
| AkShare 拉取 | < 2s |
| AkShare 缓存命中 | < 10ms |

### 12.2 缓存策略

```python
# data/cache.py
import json
from pathlib import Path

class JSONCache:
    def __init__(self, cache_dir: Path = Path("./cache")):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)
    
    def get(self, key: str, ttl_seconds: int = 300) -> dict | None:
        """读取缓存,过期返回 None"""
        ...
    
    def set(self, key: str, value: dict):
        """写入缓存"""
        ...
```

缓存策略:

| 数据 | TTL | 存储 |
|---|---|---|
| 行情价格 | 5 分钟 | JSON 文件 |
| 股票基础信息 | 1 天 | JSON 文件 |
| 历史 K 线 | 永久 | SQLite |

### 12.3 失败降级

| 场景 | 降级方案 |
|---|---|
| AkShare 失败 | 返回缓存 + 标记陈旧 |
| DeepSeek 失败 | 评分仍展示,ai_comment = None |
| SSE 推送失败 | 前端降级轮询 `/api/diagnose/{id}` |
| SQLite 锁 | 重试 3 次 + 错误提示 |

### 12.4 监控埋点(v1.3 新增)

#### 12.4.1 结构化日志

```python
# core/logging.py
import json
from pathlib import Path
from datetime import datetime
from loguru import logger  # 或 stdlib logging

LOG_DIR = Path.home() / "rich" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

def configure_logging():
    """配置结构化日志"""
    logger.add(
        LOG_DIR / "rich-{time:YYYY-MM-DD}.log",
        format="{message}",
        serialize=True,  # JSON 格式
        rotation="00:00",  # 每天 0 点轮转
        retention="30 days",
    )
```

**关键事件记录**:
| 事件 | 字段 |
|---|---|
| API 调用 | trace_id, path, method, duration, status |
| LLM 调用 | trace_id, model, prompt_tokens, completion_tokens, duration, success |
| AkShare 调用 | trace_id, endpoint, duration, success, error |
| SSE 推送 | trace_id, trade_id, event, success |
| 错误 | trace_id, error_type, stack_trace, context |

#### 12.4.2 关键指标端点

```python
# api/admin.py
from collections import deque
from time import time

class MetricsStore:
    def __init__(self):
        self.llm_calls = deque(maxlen=200)  # 最近 200 次
        self.akshare_calls = deque(maxlen=200)
        self.api_durations = deque(maxlen=500)
    
    def record_llm(self, success: bool, duration: float):
        self.llm_calls.append({"success": success, "duration": duration, "ts": time()})
    
    def summary(self) -> dict:
        return {
            "llm_success_rate_2h": self._calculate_rate(self.llm_calls),
            "akshare_success_rate_2h": self._calculate_rate(self.akshare_calls),
            "api_p99_ms": self._calculate_p99(self.api_durations),
        }

@router.get("/metrics")
async def metrics():
    return metrics_store.summary()
```

**前端可视化**(可选):`/metrics` 页面展示健康度。

#### 12.4.3 错误报告

```python
# 自动写本地错误报告
async def report_error(error: Exception, context: dict):
    error_file = Path.home() / "rich" / "logs" / "errors-{date}.log"
    error_file.parent.mkdir(parents=True, exist_ok=True)
    with error_file.open("a") as f:
        f.write(json.dumps({
            "ts": datetime.now().isoformat(),
            "error": str(error),
            "type": type(error).__name__,
            "context": context,
        }) + "\n")
```

**用户可分享**:如果工具失败,用户可将 `errors.log` 分享给开发者排查。

---

## 第 13 章 可测试性

### 13.1 测试金字塔

```
       E2E(v0.3 Playwright,可选)
        ▲
       ╱ ╲
      ╱   ╲
     ╱─────╲    集成测试(API 端到端)
    ╱       ╲      pytest + httpx.AsyncClient
   ╱─────────╲
  ╱           ╲  单元测试(Domain 纯函数)
 ╱             ╲    pytest,覆盖率 100%
─────────────────
```

### 13.2 必须 100% 覆盖

| 文件 | 原因 |
|---|---|
| `core/cost_engine.py` | 核心算法,4 类场景与同花顺对齐 |
| `core/scorer.py` | 评分主观性靠测试保障 |
| `core/decimal_helper.py` | 精度敏感 |
| `services/annual_report_service.py` | 聚合逻辑 |

### 13.3 数据准确性测试(v1.7 新增)

**目标**:验证数据源返回的数据**准确可信**,避免"数据错误导致误判"。

#### 13.3.1 单元测试(每日运行)

```python
# tests/test_data_accuracy.py
import pytest
from datetime import date, datetime
from app.services.timor_service import is_trading_day
from app.data.eastmoney import EastmoneyClient

def test_trading_day_weekday():
    """交易日判断:周一~周五是工作日"""
    assert is_trading_day(date(2026, 8, 3))  # 周一
    assert is_trading_day(date(2026, 8, 7))  # 周五

def test_trading_day_weekend():
    """非交易日:周末"""
    assert not is_trading_day(date(2026, 8, 1))  # 周六
    assert not is_trading_day(date(2026, 8, 2))  # 周日

def test_holiday_check():
    """节假日:国庆节"""
    assert not is_trading_day(date(2026, 10, 1))  # 国庆

@pytest.mark.asyncio
async def test_quote_consistency():
    """同一只股票,东财 vs 同花顺,价格差异 < 0.01"""
    code = "600519.SH"
    eastmoney_quote = await EastmoneyClient().get_quote(code)
    # 手动从同花顺抓取或 mock
    # tonghuashun_quote = ...
    # assert abs(eastmoney_quote.current_price - tonghuashun_quote.current_price) < Decimal("0.01")
```

#### 13.3.2 集成测试(每周一次)

```python
# tests/integration/test_data_accuracy_weekly.py
@pytest.mark.integration
async def test_historical_data_consistency():
    """历史数据不会出现未来日期"""
    kline = await EastmoneyClient().get_kline("600519.SH", limit=10)
    today = date.today()
    for bar in kline:
        assert bar.date <= today, "历史数据包含未来日期"

@pytest.mark.integration
async def test_prev_close_accuracy():
    """昨收 vs 实际昨收,差异 < 0.01"""
    quote = await EastmoneyClient().get_quote("600519.SH")
    # 取东财 K 线最后第二条
    kline = await EastmoneyClient().get_kline("600519.SH", limit=2)
    yesterday_close = Decimal(kline[-2]["close"])
    assert abs(quote.prev_close - yesterday_close) < Decimal("0.01")
```

#### 13.3.3 校验规则

| 规则 | 触发条件 | 失败处理 |
|---|---|---|
| 昨收 vs K 线 | 差异 > 0.01 | 标记数据源"可能不准" |
| 节假日数据 | 节假日有数据 | 标记"数据源未过滤节假日" |
| 未来日期 | 数据 > today | 拒绝使用 |
| 负价格 | 价格 < 0 | 拒绝使用 |

#### 13.3.4 实施频率

- **单元测试**:每次 CI 跑(覆盖节假日、月日数据)
- **集成测试**:每周日 02:00 自动跑(数据准确性巡检)
- **手动验证**:每月一次,人工对账同花顺

### 13.4 测试示例

```python
# tests/test_cost_engine.py
from decimal import Decimal
from app.core.cost_engine import calculate_after_transaction, build_pnl_grid

def test_buy_calculation():
    result = calculate_after_transaction(
        shares_before=1000,
        cost_before=Decimal("10.000"),
        action="buy",
        tx_shares=500,
        tx_price=Decimal("11.00"),
    )
    assert result["shares_after"] == 1500
    assert result["cost_after"] == Decimal("10.333")
    assert result["total_cost_after"] == Decimal("15500.00")

def test_sell_calculation():
    result = calculate_after_transaction(
        shares_before=1000,
        cost_before=Decimal("10.000"),
        action="sell",
        tx_shares=500,
        tx_price=Decimal("12.00"),
    )
    assert result["shares_after"] == 500
    assert result["cost_after"] == Decimal("10.000")  # 剩余成本不变
    assert result["realized_pnl"] == Decimal("1000.00")

def test_grid_21_points():
    grid = build_pnl_grid(
        cost_after=Decimal("10.333"),
        shares_after=1500,
    )
    assert len(grid) == 21
    assert grid[0]["pct"] == -10
    assert grid[20]["pct"] == 10
```

---

## 第 14 章 部署与运维

### 14.1 启动脚本

```bash
#!/bin/bash
# start.sh

# 1. 启动后端
cd backend
uv run uvicorn app.main:app --reload --port 8000 &

# 2. 等待 3 秒
sleep 3

# 3. 启动前端
cd ../frontend
npm run dev
```

### 14.2 健康检查

```python
# api/admin.py
@router.get("/health")
async def health():
    return {"status": "ok"}
```

### 14.3 升级路径

- **v0.2**:增加自选股监控、选股筛选 API
- **v0.3**:基本面、持仓诊断、流水导入
- **v1.0**:决定是否多用户/SaaS

### 14.4 多设备边界与演进(v1.4 新增)

> **盲点**:文档一直说"本地单机",但从没定义"多设备(手机 + 电脑)"到底做不做、什么时候做、现有架构留了什么后路。

#### 14.4.1 边界定义(MVP 明确)

| 场景 | 结论 | 原因 |
|---|---|---|
| 同一台电脑两个浏览器窗口 | ✅ 支持 | 都是连 localhost:8000,天然多标签 |
| 手机浏览器访问电脑(localhost) | ❌ 不做 | 手机访问不到 localhost;需要局域网地址 + 防火墙放行,体验不稳定 |
| 手机 App + 电脑同步 | ❌ 不做 | 需要云端存储 + 账号 + 鉴权,复杂度爆炸,与"仅本地"承诺冲突 |

#### 14.4.2 重评估条件(满足任一再启动)

1. 用户(本人)连续 1 个月每周使用 ≥ 3 次,且明确表达"想在手机上看"
2. 年度账单/止损提醒在电脑端触达率不足(用户经常不在电脑前)

#### 14.4.3 三条演进路径(届时三选一)

| 路径 | 方案 | 成本 | 适合 |
|---|---|---|---|
| A | 局域网共享:手机浏览器访问 `http://电脑IP:8000`,数据仍在电脑 | 低(暴露端口 + 防火墙) | 尝鲜 |
| B | 数据文件上云(SQLite 挂 WebDAV/网盘),两设备连同一文件 | 中(锁冲突/同步冲突风险) | 轻度同步 |
| C | 完整后端化:云端 API + 鉴权 + 数据库迁移 | 高(违背"仅本地"卖点) | 产品被验证 |

> 隐私承诺与多设备天然冲突:路径 C 会推翻"数据不上传任何第三方"。**MVP 期间不做任何动作**,只保证下一条。

#### 14.4.4 现有架构预留(零成本)

- 数据访问全走 Repository 层 → 未来换 PostgreSQL/云端不碰业务代码
- API 无状态(无 session 耦合)→ 未来加鉴权容易
- 数据可导出(CSV/Excel/JSON,project-book 9.5)→ 就算不支持同步,数据也能手动搬到另一台设备

---

## 第 15 章 决策记录

| # | 决策项 | 选择 | 理由 |
|---|---|---|---|
| A1 | 进程模型 | FastAPI + Next.js 双进程 | 职责清晰 |
| A2 | 异步 IO | 全异步(asyncio + aiosqlite) | FastAPI 原生 |
| A3 | ORM | SQLAlchemy 2 async | 类型友好,生态熟 |
| A4 | DB 文件 | 本地 SQLite | 单机足够 |
| A5 | 数值精度 | Python `Decimal` | 金额必须 |
| A6 | AI 调用 | httpx 异步 + 3 次重试 | 简单可靠 |
| A7 | 异步任务 | FastAPI BackgroundTasks | MVP 不需要 Redis |
| A8 | SSE | 内置 EventBus + asyncio.Queue | 无需 Redis pub/sub |
| A9 | 配置 | pydantic-settings + .env | 标准做法 |
| A10 | 错误格式 | 统一 `{code, message, detail}` | 前端好处理 |
| A11 | 类型生成 | OpenAPI → openapi-typescript | 单一来源 |
| A12 | 测试 | pytest + pytest-asyncio | 异步友好 |
| A13 | 缓存 | JSON 文件,无 Redis | 个人项目最简 |
| A14 | 多设备边界 | MVP 仅本机单用户;三条演进路径,重评估条件见 14.4 | v1.4 盲点 10 |
| A15 | 并发写规则 | 全部写 SQLite 路径必须 `safe_write`(补 2/4/5 路径)+ 缓存原子写 | v1.4 盲点 13 |
| A16 | akshare 治理 | 锁版本 + 单点封装 + 失败率监控 + 东财列表应急切换 | v1.4 盲点 18 |
| A17 | Provider 抽象 | BaseLLM(ABC)+ ProviderFactory 单例 + 3 实现 | v1.5 |
| A18 | Provider 切换存储 | SQLite llm_settings 单行表 + Alembic 迁移 | v1.5 |
| A19 | 配置管理 | 3 个 Key + LLM_DEFAULT_PROVIDER 都在 .env,.env.example 列全 | v1.5 |
| A20 | A/B 测试策略 | 用户手动切换 + 评分详情"重新生成"对比,不自动跑三方 | v1.5 |
| A21 | 截图识别架构(v2.0 新增) | PaddleOCR 离线 + LLM 文本解析(主路径)+ 粘贴 JSON(降级路径);截图只存本地 | v2.0 |
| A22 | Key UI 输入 + 加密存储(v2.1 新增) | Fernet 加密 + llm_api_keys 表;FERNET_KEY 存 .env 首次启动自动生成;ProviderFactory.get 返回 None;DiagnoseService 优雅降级 | v2.1 |

---

**文档结束。**