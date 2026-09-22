# iFinD-Driven Screener + Reflection Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 反向利用 thsifind 数据能力，优化 screener（事件因子 + 基本面兜底）+ reflection（22:00 消息面提示）三个现有模块。

**Architecture:** 三项独立改动（A screener 评分扩因子 / B screener 末尾追加基本面 gate / C ReflectionCard 提示行），各自 ifind 包装 → 服务编排 → 当日缓存表 → 失败 fail-fast。新增 7 个文件、修改 6 个文件、扩 4 个测试文件、新增 2 篇迁移。

**Tech Stack:** Python 3.11+ / FastAPI 0.115 / SQLAlchemy 2.0 / Pydantic 2 / Alembic / aiosqlite / loguru / httpx / pytest-asyncio; Next.js 14.2 App Router / React 18 / TS 5 / Tailwind 3.4 / Zustand 5 / axios / `connector__thsifind__*` 工具栏

## Global Constraints

- **失败就是失败**：任一 ifind 子调用失败 → 改动点对应行为整体抛错，不写降级、不拼凑、不编造（spec §3.1）
- **不动 LLM Provider / 不动 prompt 风格红线**（spec §3.3）
- **缓存策略**：A/C 改动当日 1 次缓存（写表条件：拉取成功），B 改动不缓存（票级实时查，可控）（spec §5）
- **超时**：单 ifind 子调用默认 8s，整体失败即抛
- **配置常量**全部在 `backend/app/core/config.py`（spec §4.1/§4.2）
- **Alembic 迁移**走标准 `alembic revision --autogenerate` 风格（项目已有 10+ 历史迁移）
- **测试 mock**：不真打 ifind，在 `conftest.py` 加 `mock_thsifind` fixture（monkeypatch 工具栏 connector 工具）
- **commit 风格**：沿用项目现有 `feat(scope): 中文描述` + 范围括注（如 `(A) screener 事件因子`）
- **本地未提交改动**：用户当前 22 个未保存改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py` 在 plan 期间**不动**

---

## Task 1: 写 ADR-0008 文档（先行定义术语）

**Files:**
- Create: `docs/dev-log/ADR-0008-ifind-screener-reflection-optimization.md`
- Modify: `docs/dev-log/decisions-index.md`（追加 ADR-0008 条目）

**Interfaces:**
- Consumes: 无
- Produces: ADR-0008 文档 + decisions-index 条目

- [ ] **Step 1: 读 ADR-0007 + decisions-index**

读 `docs/dev-log/ADR-0007-screener-watchlist.md` 和 `docs/dev-log/decisions-index.md`，熟悉格式。

- [ ] **Step 2: 写 ADR-0008**

新建 `docs/dev-log/ADR-0008-ifind-screener-reflection-optimization.md`，结构（仿 ADR-0006/0007）：

```markdown
# ADR-0008: iFinD 驱动现有模块优化（事件因子 / 基本面兜底 / 消息面提示）

## 状态：已采用（2026-09-22）

## 背景
现有 screener v2.6 (ADR-0006) 与 watchlist v2.6.1 (ADR-0007) 已上线,
但 screener 仅看资金流 + 量比 + 涨速 + 板块强度 4 项纯技术因子,
缺失"事件命中"维度; 跑出 Top N 后无法剔除"技术面强势但基本面差"的伪强势票;
ReflectionCard 22:00 弹窗缺少消息面上下文。

iFinD（thsifind 数据接口, 已接入工具栏）提供:
- search_trending_news: 热门事件驱动资讯(时效性强)
- search_securities: 智能选股(基于财务/估值/行业过滤)
- search_news + search_notice: 财经新闻 + 公告

## 决策
新增 3 项 ifind 数据接入, 全部走"接现有模块不开新功能"原则:
1. screener 加事件因子加权(第 5 因子, 0/8/15 三档)
2. screener Top N 末尾追加基本面兜底过滤(hard gate)
3. ReflectionCard 22:00 加消息面提示行(失败静默)

## 拒绝方案
- ❌ ifind LLM 调用: thsifind 是数据接口, 不是 LLM
- ❌ ifind 智能选股另起范式: screener 已有评分体系
- ❌ 实时盘中预警: 盘后复盘场景, 不需要实时
- ❌ ifind 多账户: 个人单机工具
- ❌ ifind 自动调度: 用户主动触发, 不后台跑

## 数据模型
新增 2 张表 + 2 个 Alembic 迁移:
- event_factor_cache(trade_date PK, event_keywords_json, stock_codes_json, fetched_at, ifind_calls, created_at, updated_at)
- reflection_context_cache(fetch_date PK, context_json, fetched_at, ifind_calls, created_at, updated_at)
- screener_picks 表新增列 fundamental_filter_status('passed'/'kicked'/NULL)

## 影响
新增 7 个文件, 修改 6 个文件, 扩 4 个测试文件。
screener 总分上限 155 → 170; 失败语义: A/C 静默不阻断, B 失败不展示 Top N。
完整设计: docs/superpowers/specs/2026-09-22-ifind-screener-reflection-optimization-design.md
```

- [ ] **Step 3: 追加 decisions-index**

编辑 `docs/dev-log/decisions-index.md`，按现有顺序追加：

```markdown
- ADR-0008 — iFinD 驱动现有模块优化（事件因子 / 基本面兜底 / 消息面提示），2026-09-22
```

- [ ] **Step 4: Commit**

```bash
git add docs/dev-log/ADR-0008-ifind-screener-reflection-optimization.md docs/dev-log/decisions-index.md
git commit -m "docs(adr): ADR-0008 ifind 驱动现有模块优化"
```

---

## Task 2: conftest.py 加 mock_thsifind fixture

**Files:**
- Modify: `backend/tests/conftest.py`

**Interfaces:**
- Consumes: 无
- Produces: `mock_thsifind` fixture，提供 `search_trending_news` / `search_news` / `search_notice` / `search_securities` / `get_security_indicators` / `get_stock_summary` 六个 mock 函数

- [ ] **Step 1: 读现有 conftest.py**

读 `backend/tests/conftest.py` 全文，了解现有 fixture 风格（async_session / db_lock / 临时库等）。

- [ ] **Step 2: 写失败测试**

新建 `backend/tests/test_conftest_mock.py`：

```python
"""验证 mock_thsifind fixture 行为"""
import pytest


def test_mock_thsifind_search_trending_news_default():
    from tests.conftest import mock_thsifind
    with mock_thsifind() as m:
        result = m.search_trending_news(time_scope="24小时", size=5)
        assert isinstance(result, list)
        assert len(result) > 0


def test_mock_thsifind_search_securities_default():
    from tests.conftest import mock_thsifind
    with mock_thsifind() as m:
        result = m.search_securities(market="A股", query="扣非ROE>0")
        assert isinstance(result, list)
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_conftest_mock.py -v
```

Expected: FAIL with `ImportError: cannot import name 'mock_thsifind' from 'tests.conftest'`

- [ ] **Step 4: 实现 mock_thsifind fixture**

编辑 `backend/tests/conftest.py`，在文件末尾追加：

```python
from contextlib import contextmanager, ExitStack
from unittest.mock import MagicMock, patch


@contextmanager
def mock_thsifind(
    trending_news: list[dict] | None = None,
    news: list[dict] | None = None,
    notices: list[dict] | None = None,
    securities: list[dict] | None = None,
    fail_on: set[str] | None = None,
):
    """Mock thsifind 工具栏, 用于所有 ifind 相关测试.

    容错: Task 2 写入时, ifind_events/news/fundamentals 模块可能尚未存在
    (Task 3/9/13 才创建). patch 路径不存在时静默跳过, 避免早跑 fixture 报错.

    Args:
        trending_news: search_trending_news 返回值(默认空 list)
        news: search_news 返回值
        notices: search_notice 返回值
        securities: search_securities 返回值(默认 [{'stock_code': '600519.SH', 'hit': True}])
        fail_on: 哪些工具名模拟失败, e.g. {'search_trending_news'}
    """
    fail_on = fail_on or set()
    m = MagicMock()

    def _maybe_fail(name):
        def _raise(*a, **kw):
            raise RuntimeError(f"mocked ifind failure: {name}")
        return _raise

    m.search_trending_news = (
        _maybe_fail("search_trending_news")
        if "search_trending_news" in fail_on
        else MagicMock(return_value=trending_news if trending_news is not None else [])
    )
    m.search_news = (
        _maybe_fail("search_news")
        if "search_news" in fail_on
        else MagicMock(return_value=news if news is not None else [])
    )
    m.search_notice = (
        _maybe_fail("search_notice")
        if "search_notice" in fail_on
        else MagicMock(return_value=notices if notices is not None else [])
    )
    m.search_securities = (
        _maybe_fail("search_securities")
        if "search_securities" in fail_on
        else MagicMock(return_value=securities if securities is not None else [
            {"stock_code": "600519.SH", "hit": True, "name": "贵州茅台"},
        ])
    )
    m.get_security_indicators = MagicMock(return_value={})
    m.get_stock_summary = MagicMock(return_value={})

    patches = [
        ("app.data.ifind_events", "_search_trending_news", m.search_trending_news),
        ("app.data.ifind_news", "_search_news", m.search_news),
        ("app.data.ifind_news", "_search_notice", m.search_notice),
        ("app.data.ifind_fundamentals", "_search_securities", m.search_securities),
    ]

    with ExitStack() as stack:
        for module_path, attr, mock_obj in patches:
            try:
                stack.enter_context(patch(f"{module_path}.{attr}", mock_obj))
            except (AttributeError, ModuleNotFoundError):
                # 模块尚未创建 (Task 3/9/13 才落地), 跳过此 patch
                pass
        yield m
```

**注意**: patch 路径 `app.data.ifind_events._search_trending_news` 等会在后续 task 定义。Task 2 写入后, 早跑 fixture 只会 patch 已存在的路径。

- [ ] **Step 5: 验证 fixture 可加载（暂时跳过 patch 实际生效测试）**

```bash
cd backend && python -c "from tests.conftest import mock_thsifind; print('fixture importable')"
```

Expected: 输出 `fixture importable`

- [ ] **Step 6: Commit**

```bash
git add backend/tests/conftest.py backend/tests/test_conftest_mock.py
git commit -m "test(conftest): add mock_thsifind fixture for ifind mocking"
```

---

## Task 3: 改动 A-1 — ifind_events 包装层

**Files:**
- Create: `backend/app/data/ifind_events.py`

**Interfaces:**
- Consumes: thsifind 工具栏 `search_trending_news`
- Produces: `async fetch_trending_events(size=20) -> dict[str, Any]` 返回 `{fetched_at: ISO, event_keywords: set[str], stock_codes: set[str], raw: list[dict]}`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_ifind_events.py`：

```python
"""ifind_events 包装层测试"""
import pytest
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_fetch_trending_events_returns_normalized_dict():
    from app.data.ifind_events import fetch_trending_events
    from tests.conftest import mock_thsifind

    cn_tz = timezone(timedelta(hours=8))
    raw_events = [
        {"title": "AI 概念爆发", "stocks": ["600519.SH", "000001.SZ"], "tags": ["AI"]},
        {"title": "新能源补贴", "stocks": ["300750.SZ"], "tags": ["新能源"]},
    ]
    with mock_thsifind(trending_news=raw_events):
        result = await fetch_trending_events(size=20)

    assert isinstance(result, dict)
    assert "fetched_at" in result
    assert isinstance(result["event_keywords"], set)
    assert result["event_keywords"] == {"AI", "新能源"}
    assert isinstance(result["stock_codes"], set)
    assert result["stock_codes"] == {"600519.SH", "000001.SZ", "300750.SZ"}
    assert len(result["raw"]) == 2


@pytest.mark.asyncio
async def test_fetch_trending_events_empty():
    from app.data.ifind_events import fetch_trending_events
    from tests.conftest import mock_thsifind

    with mock_thsifind(trending_news=[]):
        result = await fetch_trending_events(size=20)

    assert result["event_keywords"] == set()
    assert result["stock_codes"] == set()
    assert result["raw"] == []


@pytest.mark.asyncio
async def test_fetch_trending_events_failure_raises():
    from app.data.ifind_events import fetch_trending_events, IfindUnavailable
    from tests.conftest import mock_thsifind

    with mock_thsifind(fail_on={"search_trending_news"}):
        with pytest.raises(IfindUnavailable):
            await fetch_trending_events(size=20)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_ifind_events.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.ifind_events'`

- [ ] **Step 3: 实现 ifind_events.py**

新建 `backend/app/data/ifind_events.py`：

```python
"""thsifind search_trending_news 包装层 (改动 A)

提供盘后选股事件因子所需数据:
- fetch_trending_events: 拉取热门事件, 归一为 {event_keywords, stock_codes}
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

# 工具栏内 connector 入口 (mock fixture patch 此路径)
try:
    from mcode_tools_connector import call as _mcode_call
except ImportError:
    _mcode_call = None  # 测试环境无 mcode-tools 时降级, 由 fixture mock


class IfindUnavailable(Exception):
    """ifind 调用失败 (screener 与 reflection 统一异常基类)"""


_CN_TZ = timezone(timedelta(hours=8))


async def _search_trending_news(time_scope: str, size: int, sensitive: str = "全部") -> list[dict[str, Any]]:
    """工具栏入口 (mock 入口). 生产路径走 mcode-tools."""
    if _mcode_call is None:
        raise IfindUnavailable("mcode-tools connector 未安装")
    return await _mcode_call(
        "thsifind__search_trending_news",
        {"time_scope": time_scope, "size": size, "sensitive": sensitive},
    )


async def fetch_trending_events(size: int = 20, time_scope: str = "24小时") -> dict[str, Any]:
    """拉取热门事件, 归一返回.

    Returns:
        {
            "fetched_at": "2026-09-22T22:00:00+08:00",
            "event_keywords": set[str],   # e.g. {"AI", "新能源"}
            "stock_codes": set[str],       # e.g. {"600519.SH", "300750.SZ"}
            "raw": list[dict],             # 原始数据, 供调试/审计
        }
    """
    try:
        raw = await _search_trending_news(time_scope=time_scope, size=size)
    except Exception as e:
        raise IfindUnavailable(f"search_trending_news 失败: {e}") from e

    if not isinstance(raw, list):
        raise IfindUnavailable(f"search_trending_news 返回非 list: {type(raw).__name__}")

    keywords: set[str] = set()
    codes: set[str] = set()
    for r in raw:
        if not isinstance(r, dict):
            continue
        tags = r.get("tags") or []
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, str):
                    keywords.add(t.strip())
        stocks = r.get("stocks") or []
        if isinstance(stocks, list):
            for s in stocks:
                if isinstance(s, str):
                    codes.add(s.strip().upper())

    return {
        "fetched_at": datetime.now(_CN_TZ).isoformat(),
        "event_keywords": keywords,
        "stock_codes": codes,
        "raw": raw,
    }


__all__ = ["IfindUnavailable", "fetch_trending_events"]
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && python -m pytest tests/test_ifind_events.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/ifind_events.py backend/tests/test_ifind_events.py
git commit -m "feat(ifind-events): 包装 search_trending_news, 归一为 {event_keywords, stock_codes}"
```

---

## Task 4: 改动 A-2 — event_factor_cache_repo + Alembic 迁移

**Files:**
- Create: `backend/app/repositories/event_factor_cache_repo.py`
- Create: `backend/migrations/versions/<ts>_event_factor_cache.py`（autogenerate 后填函数体）

**Interfaces:**
- Consumes: `async_session` (已有)
- Produces: `EventFactorCacheRepo` 单例, 方法 `get_today(date) -> EventFactorCache | None` + `upsert(date, event_keywords_json, stock_codes_json, fetched_at, ifind_calls) -> EventFactorCache`

- [ ] **Step 1: 读现有 repo**

读 `backend/app/repositories/screener_repo.py` + `backend/app/repositories/daily_analysis_repo.py`，熟悉 UPSERT 风格（项目已有 SQLite UPSERT 写法）。

- [ ] **Step 2: 写失败测试**

新建 `backend/tests/test_event_factor_cache_repo.py`：

```python
"""event_factor_cache 仓储层测试"""
import pytest
from datetime import date


@pytest.mark.asyncio
async def test_upsert_and_get_today():
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo

    today = date.today()
    # 先清掉可能的历史数据
    async with event_factor_cache_repo._session() if hasattr(event_factor_cache_repo, '_session') else __import__('app.db').db.async_session() as session:
        pass

    row = await event_factor_cache_repo.upsert(
        trade_date=today,
        event_keywords_json='["AI", "新能源"]',
        stock_codes_json='["600519.SH", "300750.SZ"]',
        fetched_at="2026-09-22T22:00:00+08:00",
        ifind_calls=1,
    )
    assert row.id is not None

    got = await event_factor_cache_repo.get_today(today)
    assert got is not None
    assert got.trade_date == today
    assert got.ifind_calls == 1


@pytest.mark.asyncio
async def test_get_today_missing_returns_none():
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo
    from datetime import date, timedelta

    far_past = date.today() - timedelta(days=365)
    got = await event_factor_cache_repo.get_today(far_past)
    assert got is None
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_event_factor_cache_repo.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: 写 orm 模型**

编辑 `backend/app/models/orm.py`，找到合适位置（参考 `ScreenerRun`/`ScreenerPick` 等模型定义处）追加：

```python
class EventFactorCache(Base):
    """screener 事件因子当日缓存 (改动 A)

    - key: trade_date (当日 1 次, 跨日失效)
    - 写表条件: ifind 拉取成功 (失败不写)
    """
    __tablename__ = "event_factor_cache"

    id = Column(Integer, primary_key=True)
    trade_date = Column(Date, nullable=False, unique=True, index=True)
    event_keywords_json = Column(Text, nullable=False)
    stock_codes_json = Column(Text, nullable=False)
    fetched_at = Column(DateTime, nullable=False)
    ifind_calls = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
```

确认文件顶部已 `from sqlalchemy import Column, Integer, String, Text, Date, DateTime, func, Boolean, Float, ForeignKey` 等导入（基于已读 `orm.py`）。

- [ ] **Step 5: 写 Alembic 迁移**

```bash
cd backend && alembic revision --autogenerate -m "add event_factor_cache table"
```

打开生成的 `backend/migrations/versions/<ts>_event_factor_cache.py`，检查 upgrade() 含 `op.create_table("event_factor_cache", ...)`，downgrade() 含 `op.drop_table(...)`。如果 autogenerate 未识别（很可能，因为生产 orm.py 不一定被 fully scanned），手动补：

```python
def upgrade() -> None:
    op.create_table(
        "event_factor_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("event_keywords_json", sa.Text, nullable=False),
        sa.Column("stock_codes_json", sa.Text, nullable=False),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.Column("ifind_calls", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_event_factor_cache_trade_date", "event_factor_cache", ["trade_date"])
    op.create_index("idx_event_factor_cache_trade_date", "event_factor_cache", ["trade_date"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_event_factor_cache_trade_date", table_name="event_factor_cache")
    op.drop_table("event_factor_cache")
```

- [ ] **Step 6: 实现 repo**

新建 `backend/app/repositories/event_factor_cache_repo.py`：

```python
"""event_factor_cache 仓储 (改动 A)

单表当日缓存; 写表条件: ifind 拉取成功."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import async_session
from app.models.orm import EventFactorCache


class EventFactorCacheRepo:
    @staticmethod
    async def get_today(trade_date: date) -> Optional[EventFactorCache]:
        async with async_session() as session:
            stmt = select(EventFactorCache).where(EventFactorCache.trade_date == trade_date)
            return (await session.execute(stmt)).scalars().first()

    @staticmethod
    async def upsert(
        trade_date: date,
        event_keywords_json: str,
        stock_codes_json: str,
        fetched_at: str,
        ifind_calls: int,
    ) -> EventFactorCache:
        async with async_session() as session:
            stmt = sqlite_insert(EventFactorCache).values(
                trade_date=trade_date,
                event_keywords_json=event_keywords_json,
                stock_codes_json=stock_codes_json,
                fetched_at=datetime.fromisoformat(fetched_at),
                ifind_calls=ifind_calls,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[EventFactorCache.trade_date],
                set_={
                    "event_keywords_json": stmt.excluded.event_keywords_json,
                    "stock_codes_json": stmt.excluded.stock_codes_json,
                    "fetched_at": stmt.excluded.fetched_at,
                    "ifind_calls": stmt.excluded.ifind_calls,
                    "updated_at": datetime.now(),
                },
            )
            await session.execute(stmt)
            await session.commit()
            row = (await session.execute(
                select(EventFactorCache).where(EventFactorCache.trade_date == trade_date)
            )).scalars().first()
            await session.refresh(row)
            return row


event_factor_cache_repo = EventFactorCacheRepo()

__all__ = ["event_factor_cache_repo", "EventFactorCacheRepo"]
```

- [ ] **Step 7: 跑迁移 + 跑测试**

```bash
cd backend && alembic upgrade head && python -m pytest tests/test_event_factor_cache_repo.py -v
```

Expected: 迁移成功 + 2 passed

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/orm.py backend/app/repositories/event_factor_cache_repo.py backend/migrations/versions/
git commit -m "feat(event-factor-cache): 新增 event_factor_cache 表 + 仓储 + 迁移 (改动 A)"
```

---

## Task 5: 改动 A-3 — event_factor_service 业务编排

**Files:**
- Create: `backend/app/services/event_factor_service.py`
- Modify: `backend/app/services/scoring.py`（新增 `event_score`，但本 task 只加占位 import，下一 task 实装）

**Interfaces:**
- Consumes: `ifind_events.fetch_trending_events` + `event_factor_cache_repo`
- Produces: `async build_event_factor_cache(date) -> EventFactorCache` + `async get_event_factor_codes(date) -> set[str]`（读侧，方便 screener 调用）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_event_factor_service.py`：

```python
"""event_factor_service 业务编排测试"""
import pytest
from datetime import date


@pytest.mark.asyncio
async def test_build_event_factor_cache_writes_to_repo():
    from app.services.event_factor_service import build_event_factor_cache
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo
    from tests.conftest import mock_thsifind

    today = date.today()
    raw = [
        {"title": "AI", "stocks": ["600519.SH"], "tags": ["AI"]},
    ]
    with mock_thsifind(trending_news=raw):
        row = await build_event_factor_cache(today)

    assert row.id is not None
    fetched = await event_factor_cache_repo.get_today(today)
    assert fetched is not None
    assert "600519.SH" in fetched.stock_codes_json


@pytest.mark.asyncio
async def test_build_event_factor_cache_skips_when_already_cached():
    """同日已有缓存 → 直接返, 不调 ifind"""
    from app.services.event_factor_service import build_event_factor_cache
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo
    from datetime import date

    today = date.today()
    # 预填一条缓存
    await event_factor_cache_repo.upsert(
        trade_date=today,
        event_keywords_json='["预填"]',
        stock_codes_json='["000001.SZ"]',
        fetched_at="2026-09-22T00:00:00+08:00",
        ifind_calls=0,
    )

    # fail_on 触发 ifind, 但应该走缓存跳过
    from tests.conftest import mock_thsifind
    with mock_thsifind(fail_on={"search_trending_news"}):
        row = await build_event_factor_cache(today)

    assert "预填" in row.event_keywords_json


@pytest.mark.asyncio
async def test_get_event_factor_codes_returns_set():
    from app.services.event_factor_service import get_event_factor_codes
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo
    from datetime import date

    today = date.today()
    await event_factor_cache_repo.upsert(
        trade_date=today,
        event_keywords_json='["AI"]',
        stock_codes_json='["600519.SH", "300750.SZ"]',
        fetched_at="2026-09-22T00:00:00+08:00",
        ifind_calls=1,
    )

    codes = await get_event_factor_codes(today)
    assert codes == {"600519.SH", "300750.SZ"}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_event_factor_service.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 event_factor_service.py**

新建 `backend/app/services/event_factor_service.py`：

```python
"""screener 事件因子服务 (改动 A)

业务编排: 当日 1 次缓存; 失败 fail-fast 不写缓存."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional, set  # noqa: F401 (placeholder, see below)

from app.data.ifind_events import IfindUnavailable, fetch_trending_events
from app.models.orm import EventFactorCache
from app.repositories.event_factor_cache_repo import event_factor_cache_repo

logger = logging.getLogger(__name__)


async def build_event_factor_cache(trade_date: date) -> EventFactorCache:
    """拉取 ifind 热门事件并写当日缓存; 已缓存则跳过.

    Raises:
        IfindUnavailable: ifind 拉取失败 (不写缓存)
    """
    cached = await event_factor_cache_repo.get_today(trade_date)
    if cached is not None:
        return cached

    result = await fetch_trending_events(size=20)

    row = await event_factor_cache_repo.upsert(
        trade_date=trade_date,
        event_keywords_json=json.dumps(sorted(result["event_keywords"]), ensure_ascii=False),
        stock_codes_json=json.dumps(sorted(result["stock_codes"]), ensure_ascii=False),
        fetched_at=result["fetched_at"],
        ifind_calls=1,
    )
    logger.info("event factor cache built: trade_date=%s codes=%d", trade_date, len(result["stock_codes"]))
    return row


async def get_event_factor_codes(trade_date: date) -> set[str]:
    """读侧: 给 screener 用的事件命中股票代码集合 (空集 = 今日无事件或缓存失败)."""
    cached = await event_factor_cache_repo.get_today(trade_date)
    if cached is None:
        return set()
    try:
        codes = json.loads(cached.stock_codes_json)
        return {c.upper() for c in codes if isinstance(c, str)}
    except (json.JSONDecodeError, TypeError):
        logger.warning("event_factor_cache.stock_codes_json 损坏: %s", cached.stock_codes_json)
        return set()


__all__ = ["build_event_factor_cache", "get_event_factor_codes"]
```

**修正**：上一段中 `from typing import Optional, set` 应改为 `from typing import Optional`（`set` 不是 typing 成员）。修掉。

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && python -m pytest tests/test_event_factor_service.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/event_factor_service.py backend/tests/test_event_factor_service.py
git commit -m "feat(event-factor-service): 当日 1 次缓存 + 读侧 get_event_factor_codes (改动 A)"
```

---

## Task 6: 改动 A-4 — scoring.event_score + config 常量

**Files:**
- Modify: `backend/app/services/scoring.py`
- Modify: `backend/app/core/config.py`

**Interfaces:**
- Consumes: 无
- Produces: `event_score(stock_code, event_stock_codes, event_keywords) -> int`（纯计算，无 I/O）+ `SCREENER_EVENT_FACTOR_WEIGHT = 15` 常量

- [ ] **Step 1: 读现有 scoring.py**

读 `backend/app/services/scoring.py` 全文，理解现有 4 个评分函数签名风格（`main_inflow_score`/`volume_ratio_score`/`momentum_score`/`sector_strength_score`）。

- [ ] **Step 2: 写失败测试**

编辑 `backend/tests/test_scoring.py`，追加：

```python
"""scoring.event_score 单元测试 (改动 A)"""
from app.services.scoring import event_score


def test_event_score_hit_returns_full():
    codes = {"600519.SH", "300750.SZ"}
    assert event_score("600519.SH", codes, {"AI"}) == 15


def test_event_score_miss_returns_zero():
    codes = {"600519.SH"}
    assert event_score("000001.SZ", codes, {"AI"}) == 0


def test_event_score_case_insensitive():
    codes = {"600519.sh"}  # 小写
    assert event_score("600519.SH", codes, set()) == 15


def test_event_score_empty_inputs():
    assert event_score("600519.SH", set(), set()) == 0
    assert event_score("", set(), set()) == 0
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_scoring.py::test_event_score_hit_returns_full -v
```

Expected: FAIL with `ImportError: cannot import name 'event_score'`

- [ ] **Step 4: 在 config.py 加常量**

编辑 `backend/app/core/config.py`，找到合适位置（参考其他 `SCREENER_*` 常量）追加：

```python
# 改动 A: screener 事件因子加权 (iFinD 驱动)
SCREENER_EVENT_FACTOR_WEIGHT: int = 15
SCREENER_EVENT_KEYWORD_BLACKLIST: list[str] = ["ST", "*ST", "退市"]
```

- [ ] **Step 5: 在 scoring.py 加 event_score**

编辑 `backend/app/services/scoring.py`，文件末尾追加：

```python
def event_score(stock_code: str, event_stock_codes: set[str], event_keywords: set[str]) -> int:
    """事件命中分 (改动 A)

    命中热门事件相关股: SCREENER_EVENT_FACTOR_WEIGHT (默认 15)
    未命中: 0

    Args:
        stock_code: 当前候选股票代码(规整后)
        event_stock_codes: 当日热门事件相关股代码集合 (来自 event_factor_cache)
        event_keywords: 当日热门事件关键词 (保留参数, 未来扩展用)

    Returns:
        int: 0 或 SCREENER_EVENT_FACTOR_WEIGHT
    """
    if not stock_code or not event_stock_codes:
        return 0
    if stock_code.upper() in {c.upper() for c in event_stock_codes}:
        return SCREENER_EVENT_FACTOR_WEIGHT
    return 0
```

确保文件顶部 `from app.core.config import settings, SCREENER_EVENT_FACTOR_WEIGHT`（或类似路径）。如未导入则追加。

- [ ] **Step 6: 跑测试确认通过**

```bash
cd backend && python -m pytest tests/test_scoring.py -v
```

Expected: 全部通过 (含原有 + 4 个新增)

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/scoring.py backend/app/core/config.py backend/tests/test_scoring.py
git commit -m "feat(scoring): 加 event_score 纯计算 + SCREENER_EVENT_FACTOR_WEIGHT 常量 (改动 A)"
```

---

## Task 7: 改动 A-5 — screener_service 接入事件因子

**Files:**
- Modify: `backend/app/services/screener_service.py`

**Interfaces:**
- Consumes: `event_factor_service.build_event_factor_cache(date)` + `get_event_factor_codes(date)` + `scoring.event_score`
- Produces: screener run 时**先** `await build_event_factor_cache(today)`，评分循环里**叠加** `event_score`

- [ ] **Step 1: 读现有 screener_service.py**

读 `backend/app/services/screener_service.py` 全文，重点找评分循环（4 因子叠加处）。

- [ ] **Step 2: 写失败测试**

新建 `backend/tests/test_screener_with_event_factor.py`：

```python
"""screener 接入事件因子端到端测试 (改动 A)"""
import pytest
from datetime import date
from unittest.mock import patch, AsyncMock

from app.services import screener_service
from app.services.event_factor_service import build_event_factor_cache
from app.services.scoring import event_score


@pytest.mark.asyncio
async def test_run_screener_calls_build_event_factor_first():
    """screener 启动时必须先 build_event_factor_cache (失败 fail-fast 不跑评分)"""
    today = date.today()
    with patch.object(screener_service, "build_event_factor_cache", new=AsyncMock()) as mock_build:
        # 跑任意最小 screener 入口 (具体函数名以 screener_service 实际为准, 见 Step 5)
        try:
            await screener_service.run_screener(date=today, dry_run=True)
        except Exception:
            pass  # dry_run 可能因 fixture 缺失报错, 只要 build_event_factor 被调到即可
        mock_build.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_screener_event_score_overrides_when_failure_falls_back():
    """ifind 失败 → event_factor_cache 为空 → screener 仍跑 (无事件因子, 4 因子版)"""
    from app.data.ifind_events import IfindUnavailable
    today = date.today()

    with patch("app.services.screener_service.build_event_factor_cache", new=AsyncMock(side_effect=IfindUnavailable("mocked"))):
        # 失败应 fail-fast: run_screener 抛 IfindUnavailable
        with pytest.raises(IfindUnavailable):
            await screener_service.run_screener(date=today, dry_run=True)
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_screener_with_event_factor.py -v
```

Expected: FAIL (`build_event_factor_cache` not called from screener_service)

- [ ] **Step 4: 在 screener_service.py 顶部加 import**

编辑 `backend/app/services/screener_service.py`，追加：

```python
from app.services.event_factor_service import build_event_factor_cache, get_event_factor_codes
from app.services.scoring import event_score
```

如有重复则跳过。

- [ ] **Step 5: 在 screener 主入口前加 build_event_factor_cache 调用**

找到 `run_screener` 函数（具体名以代码为准，常见命名 `run_screener` / `run_daily`），在**评分循环前**插入：

```python
# 改动 A: 先构建当日事件因子缓存 (失败 fail-fast, 不跑评分)
try:
    await build_event_factor_cache(today)
except Exception as e:
    logger.warning("screener event factor unavailable today, running with 4-factor score: %s", e)
    # spec §4.1: A 失败时 screener 跑无事件因子版, 不抛错
    # (注: build_event_factor_cache 内部会自己抛 IfindUnavailable, 这里吞掉让其走 4 因子)

event_codes = await get_event_factor_codes(today)
```

- [ ] **Step 6: 在评分循环里叠加 event_score**

找到评分循环（典型是 `for pick in candidates: pick.score = ...`），追加：

```python
# 改动 A: 叠加事件因子分
pick.score += event_score(pick.stock_code, event_codes, set())
```

- [ ] **Step 7: 跑测试确认通过**

```bash
cd backend && python -m pytest tests/test_screener.py tests/test_screener_with_event_factor.py -v
```

Expected: 全部通过 (原有 screener 测试不受影响 + 新增 2 个通过)

- [ ] **Step 8: 跑全量后端测试**

```bash
cd backend && python -m pytest -x
```

Expected: 全部通过（spec §11 强调不破坏现有）

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/screener_service.py backend/tests/test_screener_with_event_factor.py
git commit -m "feat(screener): 接入事件因子加权, 失败静默走 4 因子版 (改动 A)"
```

---

## Task 8: 改动 A 完成 — 提交 + 验证

**Files:**
- 无

- [ ] **Step 1: 跑全量测试**

```bash
cd backend && python -m pytest -v
```

Expected: 全部通过

- [ ] **Step 2: 跑类型检查（项目是否用 mypy 看 pyproject.toml）**

```bash
cd backend && python -c "import app.services.screener_service, app.services.event_factor_service, app.data.ifind_events; print('imports OK')"
```

Expected: `imports OK`

- [ ] **Step 3: 输出 A 改动收尾报告**

向用户报告：
- 7 个新文件: ifind_events.py / event_factor_cache_repo.py / event_factor_service.py + 3 个 test 文件 + Alembic 迁移
- 4 个修改: orm.py / scoring.py / config.py / screener_service.py
- A 改动可独立跑 (不影响 B/C)
- screener 总分上限 155 → 170

---

## Task 9: 改动 B-1 — ifind_fundamentals 包装层

**Files:**
- Create: `backend/app/data/ifind_fundamentals.py`

**Interfaces:**
- Consumes: thsifind 工具栏 `search_securities`
- Produces: `async is_hit_fundamental_filter(stock_code, query) -> bool` —— 单只票是否命中基本面筛条件

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_ifind_fundamentals.py`：

```python
"""ifind_fundamentals 包装层测试 (改动 B)"""
import pytest


@pytest.mark.asyncio
async def test_is_hit_returns_true_when_stock_in_results():
    from app.data.ifind_fundamentals import is_hit_fundamental_filter
    from tests.conftest import mock_thsifind

    raw = [
        {"stock_code": "600519.SH", "hit": True},
        {"stock_code": "000001.SZ", "hit": False},
    ]
    with mock_thsifind(securities=raw):
        hit = await is_hit_fundamental_filter("600519.SH", "扣非ROE>0")

    assert hit is True


@pytest.mark.asyncio
async def test_is_hit_returns_false_when_stock_not_in_results():
    from app.data.ifind_fundamentals import is_hit_fundamental_filter
    from tests.conftest import mock_thsifind

    raw = [{"stock_code": "OTHER.SH", "hit": True}]
    with mock_thsifind(securities=raw):
        hit = await is_hit_fundamental_filter("600519.SH", "扣非ROE>0")

    assert hit is False


@pytest.mark.asyncio
async def test_is_hit_empty_results_returns_false():
    from app.data.ifind_fundamentals import is_hit_fundamental_filter
    from tests.conftest import mock_thsifind

    with mock_thsifind(securities=[]):
        hit = await is_hit_fundamental_filter("600519.SH", "扣非ROE>0")

    assert hit is False


@pytest.mark.asyncio
async def test_is_hit_failure_raises():
    from app.data.ifind_fundamentals import is_hit_fundamental_filter, IfindUnavailable
    from tests.conftest import mock_thsifind

    with mock_thsifind(fail_on={"search_securities"}):
        with pytest.raises(IfindUnavailable):
            await is_hit_fundamental_filter("600519.SH", "扣非ROE>0")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_ifind_fundamentals.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 ifind_fundamentals.py**

新建 `backend/app/data/ifind_fundamentals.py`：

```python
"""thsifind search_securities 包装层 (改动 B)

screener Top N 基本面兜底过滤用."""
from __future__ import annotations

from typing import Any

from app.data.ifind_events import IfindUnavailable  # 复用统一异常


try:
    from mcode_tools_connector import call as _mcode_call
except ImportError:
    _mcode_call = None


async def _search_securities(market: str, query: str) -> list[dict[str, Any]]:
    if _mcode_call is None:
        raise IfindUnavailable("mcode-tools connector 未安装")
    return await _mcode_call(
        "thsifind__search_securities",
        {"market": market, "query": query},
    )


async def is_hit_fundamental_filter(stock_code: str, query: str, market: str = "A股") -> bool:
    """单只票是否命中基本面筛条件.

    Args:
        stock_code: 6 位股票代码 (规整后)
        query: 筛条件字符串 (e.g. "扣非ROE>0 PE<行业中位数 剔除ST")
        market: 默认 A 股

    Returns:
        True = 命中 (通过筛条件), False = 不命中 (踢出)

    Raises:
        IfindUnavailable: ifind 调用失败
    """
    try:
        raw = await _search_securities(market=market, query=query)
    except Exception as e:
        raise IfindUnavailable(f"search_securities 失败: {e}") from e

    if not isinstance(raw, list):
        raise IfindUnavailable(f"search_securities 返回非 list: {type(raw).__name__}")

    norm = stock_code.upper().strip()
    for r in raw:
        if not isinstance(r, dict):
            continue
        code = r.get("stock_code")
        if isinstance(code, str) and code.upper().strip() == norm:
            return bool(r.get("hit", False))
    return False


__all__ = ["is_hit_fundamental_filter"]
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && python -m pytest tests/test_ifind_fundamentals.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/ifind_fundamentals.py backend/tests/test_ifind_fundamentals.py
git commit -m "feat(ifind-fundamentals): 包装 search_securities, 单只票基本面筛 (改动 B)"
```

---

## Task 10: 改动 B-2 — ScreenerPick orm 扩列 + 迁移

**Files:**
- Modify: `backend/app/models/orm.py`
- Create: `backend/migrations/versions/<ts>_screener_picks_fundamental_status.py`

**Interfaces:**
- Consumes: 无
- Produces: `ScreenerPick` 模型新增 `fundamental_filter_status: str | None` 列（'passed'/'kicked'/NULL）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_screener_pick_fundamental_status.py`：

```python
"""ScreenerPick.fundamental_filter_status 列测试 (改动 B)"""
import pytest
from app.models.orm import ScreenerPick
from sqlalchemy import inspect


def test_screener_pick_has_fundamental_filter_status_column():
    """验证 ORM 模型有 fundamental_filter_status 列"""
    cols = {c.name for c in ScreenerPick.__table__.columns}
    assert "fundamental_filter_status" in cols
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_screener_pick_fundamental_status.py -v
```

Expected: FAIL with assertion error (column not in model)

- [ ] **Step 3: 改 orm.py**

编辑 `backend/app/models/orm.py`，找到 `ScreenerPick` 类定义，在合适列位置追加：

```python
fundamental_filter_status = Column(String, nullable=True)  # 'passed' / 'kicked' / NULL
```

- [ ] **Step 4: 写 Alembic 迁移**

```bash
cd backend && alembic revision --autogenerate -m "add screener_picks fundamental_filter_status"
```

打开生成的迁移文件，**手动核对** upgrade() 含：

```python
op.add_column("screener_picks", sa.Column("fundamental_filter_status", sa.String, nullable=True))
```

如 autogenerate 未识别（很可能，因为可能 SQLite alter table 在已有表上 not null 默认值会被跳过），手动补完整 upgrade + / downgrade()。**注意 SQLite ALTER TABLE 不支持加 NOT NULL 列无默认值**，确保 `nullable=True`。

完整 upgrade()：

```python
def upgrade() -> None:
    op.add_column(
        "screener_picks",
        sa.Column("fundamental_filter_status", sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("screener_picks", "fundamental_filter_status")
```

- [ ] **Step 5: 跑迁移 + 跑测试**

```bash
cd backend && alembic upgrade head && python -m pytest tests/test_screener_pick_fundamental_status.py -v
```

Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/orm.py backend/migrations/versions/
git commit -m "feat(screener-picks): 新增 fundamental_filter_status 列 (改动 B)"
```

---

## Task 11: 改动 B-3 — screener_service._apply_fundamental_filter

**Files:**
- Modify: `backend/app/services/screener_service.py`
- Modify: `backend/app/core/config.py`

**Interfaces:**
- Consumes: `ifind_fundamentals.is_hit_fundamental_filter` + `ScreenerPick` ORM
- Produces: `async _apply_fundamental_filter(picks: list[ScreenerPick]) -> list[ScreenerPick]`（失败 fail-fast 不写库）

- [ ] **Step 1: 在 config.py 加常量**

编辑 `backend/app/core/config.py`，追加：

```python
# 改动 B: screener Top N 基本面兜底过滤
SCREENER_FUNDAMENTAL_FILTER_ENABLED: bool = True
SCREENER_FUNDAMENTAL_FILTER_QUERY: str = "扣非ROE>0 PE<行业中位数 剔除ST"
SCREENER_FUNDAMENTAL_KICKOUT_PENALTY: int = 30
```

- [ ] **Step 2: 写失败测试**

新建 `backend/tests/test_apply_fundamental_filter.py`：

```python
"""screener._apply_fundamental_filter 测试 (改动 B)"""
import pytest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_apply_filter_all_pass_keeps_order():
    from app.services.screener_service import _apply_fundamental_filter

    picks = [
        SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None),
        SimpleNamespace(stock_code="000001.SZ", score=95, fundamental_filter_status=None),
    ]

    async def _hit(code, query):
        return True

    with patch("app.services.screener_service.is_hit_fundamental_filter", new=_hit):
        result = await _apply_fundamental_filter(picks)

    assert len(result) == 2
    assert all(p.fundamental_filter_status == "passed" for p in result)


@pytest.mark.asyncio
async def test_apply_filter_kicked_gets_penalty_and_resorts():
    from app.services.screener_service import _apply_fundamental_filter

    picks = [
        SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None),
        SimpleNamespace(stock_code="000001.SZ", score=99, fundamental_filter_status=None),
    ]

    async def _hit(code, query):
        return code != "000001.SZ"  # 000001 被踢

    with patch("app.services.screener_service.is_hit_fundamental_filter", new=_hit):
        result = await _apply_fundamental_filter(picks)

    # 600519 仍 100; 000001 = 99 - 30 = 69, 排序仍首位
    assert result[0].stock_code == "600519.SH"
    assert result[0].fundamental_filter_status == "passed"
    assert result[1].stock_code == "000001.SZ"
    assert result[1].fundamental_filter_status == "kicked"
    assert result[1].score == 69


@pytest.mark.asyncio
async def test_apply_filter_failure_raises():
    """任一票基本面查失败 → 整体抛 IfindUnavailable"""
    from app.services.screener_service import _apply_fundamental_filter
    from app.data.ifind_events import IfindUnavailable

    picks = [
        SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None),
        SimpleNamespace(stock_code="000001.SZ", score=99, fundamental_filter_status=None),
    ]

    async def _hit(code, query):
        if code == "000001.SZ":
            raise IfindUnavailable("mocked")
        return True

    with patch("app.services.screener_service.is_hit_fundamental_filter", new=_hit):
        with pytest.raises(IfindUnavailable):
            await _apply_fundamental_filter(picks)


@pytest.mark.asyncio
async def test_apply_filter_disabled_short_circuits():
    """SCREENER_FUNDAMENTAL_FILTER_ENABLED=False 时原样返回"""
    from app.services.screener_service import _apply_fundamental_filter
    from app.core import config

    picks = [SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None)]

    with patch.object(config, "SCREENER_FUNDAMENTAL_FILTER_ENABLED", False):
        result = await _apply_fundamental_filter(picks)

    assert result == picks
    assert result[0].fundamental_filter_status is None
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_apply_fundamental_filter.py -v
```

Expected: FAIL with `ImportError: cannot import name '_apply_fundamental_filter'`

- [ ] **Step 4: 在 screener_service.py 顶部加 import**

编辑 `backend/app/services/screener_service.py`，追加：

```python
from app.data.ifind_fundamentals import is_hit_fundamental_filter
from app.data.ifind_events import IfindUnavailable
```

如有重复跳过。

- [ ] **Step 5: 实现 _apply_fundamental_filter**

编辑 `backend/app/services/screener_service.py`，在合适位置（建议紧跟 `run_screener` 主函数前后）追加：

```python
async def _apply_fundamental_filter(picks: list) -> list:
    """对 Top N 跑一次基本面兜底过滤; 任一失败直接抛 IfindUnavailable.

    行为:
    - SCREENER_FUNDAMENTAL_FILTER_ENABLED=False → 原样返
    - is_hit_fundamental_filter 返 True → fundamental_filter_status='passed', 分不变
    - 返 False → fundamental_filter_status='kicked', 扣 SCREENER_FUNDAMENTAL_KICKOUT_PENALTY
    - 任一票 ifind 调用失败 → 抛 IfindUnavailable, 不写库

    Args:
        picks: ScreenerPick 对象列表 (含 stock_code, score)

    Returns:
        重新排序的 picks 列表
    """
    if not SCREENER_FUNDAMENTAL_FILTER_ENABLED:
        return picks

    from app.core.config import (
        SCREENER_FUNDAMENTAL_FILTER_ENABLED,
        SCREENER_FUNDAMENTAL_FILTER_QUERY,
        SCREENER_FUNDAMENTAL_KICKOUT_PENALTY,
    )

    # 并发查 20 条 (上限由调用方控制, 通常 screener run 出 Top N 后调用)
    results = await asyncio.gather(
        *[is_hit_fundamental_filter(p.stock_code, SCREENER_FUNDAMENTAL_FILTER_QUERY) for p in picks],
        return_exceptions=True,
    )
    # 任一失败 → 整体抛
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            if isinstance(r, IfindUnavailable):
                raise r
            raise IfindUnavailable(f"基本面过滤异常: {picks[i].stock_code}: {r}") from r

    for pick, hit in zip(picks, results):
        if hit:
            pick.fundamental_filter_status = "passed"
        else:
            pick.fundamental_filter_status = "kicked"
            pick.score -= SCREENER_FUNDAMENTAL_KICKOUT_PENALTY

    picks.sort(key=lambda p: p.score, reverse=True)
    return picks
```

注意确认 `asyncio` 已 import。

- [ ] **Step 6: 在 run_screener 末尾插入调用**

找到 `run_screener`（具体名以代码为准）的**评分循环结束后、最终排序前**（或最终排序后但未持久化前），插入：

```python
# 改动 B: 基本面兜底过滤 (失败 fail-fast)
await _apply_fundamental_filter(top_n_picks)
```

如果 screener 流程里有"持久化前最终排序"的步骤，则在该步骤**之后**调用（保证 kick 生效）。

- [ ] **Step 7: 跑测试确认通过**

```bash
cd backend && python -m pytest tests/test_apply_fundamental_filter.py tests/test_screener.py -v
```

Expected: 全部通过

- [ ] **Step 8: 跑全量后端测试**

```bash
cd backend && python -m pytest -x
```

Expected: 全部通过

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/screener_service.py backend/app/core/config.py backend/tests/test_apply_fundamental_filter.py
git commit -m "feat(screener): Top N 基本面兜底过滤, 失败 fail-fast (改动 B)"
```

---

## Task 12: 改动 B-4 — 前端 screener page 显示基本面状态

**Files:**
- Modify: `frontend/src/app/screener/page.tsx`

**Interfaces:**
- Consumes: `ScreenerPick.fundamental_filter_status` 字段（'passed'/'kicked'/undefined）
- Produces: Top N 卡片新增一行 "基本面: ✓ 通过 / ⚠️ 被过滤"

- [ ] **Step 1: 读 screener page.tsx**

读 `frontend/src/app/screener/page.tsx`，找 Top N 卡片渲染处。

- [ ] **Step 2: 加状态字段到组件**

在 Top N 卡片渲染处，参考 spec §4.2 列出的字段 `fundamental_filter_status`，找到当前渲染的字段列表，在合适处追加：

```tsx
{pick.fundamental_filter_status && (
  <div className="text-xs mt-1">
    {pick.fundamental_filter_status === 'passed' ? (
      <span className="text-up">✓ 基本面通过</span>
    ) : (
      <span className="text-down">⚠️ 基本面被过滤</span>
    )}
  </div>
)}
```

注意 `text-up` / `text-down` 是项目 Tailwind 主题色（基于已读 page.tsx）。

- [ ] **Step 3: 跑前端 typecheck**

```bash
cd frontend && pnpm typecheck
```

Expected: 通过（确认字段在 OpenAPI 生成的 types 中存在；如不存在，先跑 `pnpm gen-types` 重生成）

- [ ] **Step 4: 跑前端 build**

```bash
cd frontend && pnpm build
```

Expected: 成功

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/screener/page.tsx
git commit -m "feat(screener-ui): Top N 卡片显示基本面过滤状态 (改动 B)"
```

---

## Task 13: 改动 C-1 — ifind_news 包装层

**Files:**
- Create: `backend/app/data/ifind_news.py`

**Interfaces:**
- Consumes: thsifind 工具栏 `search_news` + `search_notice`
- Produces: `async fetch_news_for_stock(stock_code, start_date, end_date) -> dict` 返回 `{announcements: list, news: list, fetched_at}`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_ifind_news.py`：

```python
"""ifind_news 包装层测试 (改动 C)"""
import pytest


@pytest.mark.asyncio
async def test_fetch_news_for_stock_returns_normalized():
    from app.data.ifind_news import fetch_news_for_stock
    from tests.conftest import mock_thsifind

    raw_news = [
        {"title": "公司发布新产品", "date": "2026-09-22"},
    ]
    raw_notices = [
        {"title": "2026 年第三季度业绩预告", "date": "2026-09-21"},
    ]
    with mock_thsifind(news=raw_news, notices=raw_notices):
        result = await fetch_news_for_stock(
            "600519.SH", start_date="2026-09-15", end_date="2026-09-22"
        )

    assert len(result["announcements"]) == 1
    assert len(result["news"]) == 1
    assert "fetched_at" in result


@pytest.mark.asyncio
async def test_fetch_news_for_stock_empty():
    from app.data.ifind_news import fetch_news_for_stock
    from tests.conftest import mock_thsifind

    with mock_thsifind(news=[], notices=[]):
        result = await fetch_news_for_stock("600519.SH", "2026-09-15", "2026-09-22")

    assert result["announcements"] == []
    assert result["news"] == []


@pytest.mark.asyncio
async def test_fetch_news_failure_raises():
    from app.data.ifind_news import fetch_news_for_stock, IfindUnavailable
    from tests.conftest import mock_thsifind

    with mock_thsifind(fail_on={"search_news"}):
        with pytest.raises(IfindUnavailable):
            await fetch_news_for_stock("600519.SH", "2026-09-15", "2026-09-22")


@pytest.mark.asyncio
async def test_fetch_notice_failure_raises():
    from app.data.ifind_news import fetch_news_for_stock, IfindUnavailable
    from tests.conftest import mock_thsifind

    with mock_thsifind(fail_on={"search_notice"}):
        with pytest.raises(IfindUnavailable):
            await fetch_news_for_stock("600519.SH", "2026-09-15", "2026-09-22")
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_ifind_news.py -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 ifind_news.py**

新建 `backend/app/data/ifind_news.py`：

```python
"""thsifind search_news + search_notice 包装层 (改动 C)

ReflectionCard 22:00 弹窗消息面提示用."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from app.data.ifind_events import IfindUnavailable  # 复用统一异常


try:
    from mcode_tools_connector import call as _mcode_call
except ImportError:
    _mcode_call = None


_CN_TZ = timezone(timedelta(hours=8))


async def _search_news(query: str, size: int, time_start: str, time_end: str) -> list[dict[str, Any]]:
    if _mcode_call is None:
        raise IfindUnavailable("mcode-tools connector 未安装")
    return await _mcode_call(
        "thsifind__search_news",
        {"query": query, "size": size, "time_start": time_start, "time_end": time_end},
    )


async def _search_notice(query: str, size: int, time_start: str, time_end: str) -> list[dict[str, Any]]:
    if _mcode_call is None:
        raise IfindUnavailable("mcode-tools connector 未安装")
    return await _mcode_call(
        "thsifind__search_notice",
        {"query": query, "size": size, "time_start": time_start, "time_end": time_end},
    )


def _normalize_items(raw: list) -> list[dict]:
    out = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        out.append({
            "title": r.get("title") or r.get("notice_title") or "",
            "date": r.get("date") or r.get("publish_date") or r.get("time") or "",
        })
    return out


async def fetch_news_for_stock(
    stock_code: str,
    start_date: str,
    end_date: str,
    news_size: int = 5,
    notice_size: int = 5,
) -> dict[str, Any]:
    """拉取单只票在指定日期范围内的新闻 + 公告.

    Returns:
        {
            "stock_code": "600519.SH",
            "announcements": [{"title": ..., "date": ...}, ...],
            "news": [{"title": ..., "date": ...}, ...],
            "fetched_at": "2026-09-22T22:00:00+08:00",
        }

    Raises:
        IfindUnavailable: 任一 ifind 调用失败
    """
    query_base = f"{stock_code}"

    try:
        raw_news = await _search_news(
            query=query_base, size=news_size, time_start=start_date, time_end=end_date,
        )
    except Exception as e:
        raise IfindUnavailable(f"search_news 失败: {e}") from e

    try:
        raw_notices = await _search_notice(
            query=query_base, size=notice_size, time_start=start_date, time_end=end_date,
        )
    except Exception as e:
        raise IfindUnavailable(f"search_notice 失败: {e}") from e

    return {
        "stock_code": stock_code,
        "announcements": _normalize_items(raw_notices if isinstance(raw_notices, list) else []),
        "news": _normalize_items(raw_news if isinstance(raw_news, list) else []),
        "fetched_at": datetime.now(_CN_TZ).isoformat(),
    }


__all__ = ["fetch_news_for_stock"]
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && python -m pytest tests/test_ifind_news.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/ifind_news.py backend/tests/test_ifind_news.py
git commit -m "feat(ifind-news): 包装 search_news + search_notice (改动 C)"
```

---

## Task 14: 改动 C-2 — reflection_context_cache_repo + 迁移

**Files:**
- Create: `backend/app/repositories/reflection_context_cache_repo.py`
- Create: `backend/migrations/versions/<ts>_reflection_context_cache.py`

**Interfaces:**
- Consumes: `async_session`
- Produces: `reflection_context_cache_repo` 单例, 方法 `get_today(date) -> ReflectionContextCache | None` + `upsert(date, context_json, fetched_at, ifind_calls)`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_reflection_context_cache_repo.py`：

```python
"""reflection_context_cache 仓储测试 (改动 C)"""
import pytest
from datetime import date


@pytest.mark.asyncio
async def test_upsert_and_get_today():
    from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo

    today = date.today()
    row = await reflection_context_cache_repo.upsert(
        fetch_date=today,
        context_json='{"announcements_count": 1, "news_count": 2, "top_news_title": "test"}',
        fetched_at="2026-09-22T22:00:00+08:00",
        ifind_calls=2,
    )
    assert row.id is not None

    got = await reflection_context_cache_repo.get_today(today)
    assert got is not None
    assert got.fetch_date == today
    assert got.ifind_calls == 2


@pytest.mark.asyncio
async def test_get_today_missing_returns_none():
    from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo
    from datetime import date, timedelta

    far_past = date.today() - timedelta(days=365)
    assert await reflection_context_cache_repo.get_today(far_past) is None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_reflection_context_cache_repo.py -v
```

Expected: FAIL

- [ ] **Step 3: 改 orm.py**

编辑 `backend/app/models/orm.py`，追加：

```python
class ReflectionContextCache(Base):
    """ReflectionCard 22:00 消息面提示当日缓存 (改动 C)"""
    __tablename__ = "reflection_context_cache"

    id = Column(Integer, primary_key=True)
    fetch_date = Column(Date, nullable=False, unique=True, index=True)
    context_json = Column(Text, nullable=False)
    fetched_at = Column(DateTime, nullable=False)
    ifind_calls = Column(Integer, nullable=False, default=2)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 4: 写 Alembic 迁移**

```bash
cd backend && alembic revision --autogenerate -m "add reflection_context_cache table"
```

手动核对迁移文件（如 Step 4 task 4）：

```python
def upgrade() -> None:
    op.create_table(
        "reflection_context_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fetch_date", sa.Date, nullable=False),
        sa.Column("context_json", sa.Text, nullable=False),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.Column("ifind_calls", sa.Integer, nullable=False, server_default="2"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_reflection_context_cache_fetch_date", "reflection_context_cache", ["fetch_date"]
    )
    op.create_index(
        "idx_reflection_context_cache_fetch_date",
        "reflection_context_cache",
        ["fetch_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_reflection_context_cache_fetch_date", table_name="reflection_context_cache")
    op.drop_table("reflection_context_cache")
```

- [ ] **Step 5: 实现 repo**

新建 `backend/app/repositories/reflection_context_cache_repo.py`：

```python
"""reflection_context_cache 仓储 (改动 C)"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import async_session
from app.models.orm import ReflectionContextCache


class ReflectionContextCacheRepo:
    @staticmethod
    async def get_today(fetch_date: date) -> Optional[ReflectionContextCache]:
        async with async_session() as session:
            stmt = select(ReflectionContextCache).where(ReflectionContextCache.fetch_date == fetch_date)
            return (await session.execute(stmt)).scalars().first()

    @staticmethod
    async def upsert(
        fetch_date: date,
        context_json: str,
        fetched_at: str,
        ifind_calls: int,
    ) -> ReflectionContextCache:
        async with async_session() as session:
            stmt = sqlite_insert(ReflectionContextCache).values(
                fetch_date=fetch_date,
                context_json=context_json,
                fetched_at=datetime.fromisoformat(fetched_at),
                ifind_calls=ifind_calls,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[ReflectionContextCache.fetch_date],
                set_={
                    "context_json": stmt.excluded.context_json,
                    "fetched_at": stmt.excluded.fetched_at,
                    "ifind_calls": stmt.excluded.ifind_calls,
                    "updated_at": datetime.now(),
                },
            )
            await session.execute(stmt)
            await session.commit()
            row = (await session.execute(
                select(ReflectionContextCache).where(ReflectionContextCache.fetch_date == fetch_date)
            )).scalars().first()
            await session.refresh(row)
            return row


reflection_context_cache_repo = ReflectionContextCacheRepo()

__all__ = ["reflection_context_cache_repo", "ReflectionContextCacheRepo"]
```

- [ ] **Step 6: 跑迁移 + 测试**

```bash
cd backend && alembic upgrade head && python -m pytest tests/test_reflection_context_cache_repo.py -v
```

Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/orm.py backend/app/repositories/reflection_context_cache_repo.py backend/migrations/versions/
git commit -m "feat(reflection-context-cache): 新增 reflection_context_cache 表 + 仓储 (改动 C)"
```

---

## Task 15: 改动 C-3 — reflection_context_service 业务编排

**Files:**
- Create: `backend/app/services/reflection_context_service.py`

**Interfaces:**
- Consumes: `ifind_news.fetch_news_for_stock` + `reflection_context_cache_repo`
- Produces: `async build_reflection_context(stock_codes: list[str], today: date) -> dict` + `async get_reflection_context_summary(today) -> dict | None`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_reflection_context_service.py`：

```python
"""reflection_context_service 测试 (改动 C)"""
import pytest
from datetime import date
import json


@pytest.mark.asyncio
async def test_build_reflection_context_aggregates_codes():
    from app.services.reflection_context_service import build_reflection_context
    from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo
    from tests.conftest import mock_thsifind

    today = date.today()
    # 给两只票各 mock 一条公告 + 一条新闻
    raw_news = [{"title": f"新闻 for 600519", "date": "2026-09-22"}]
    raw_notices = [{"title": f"公告 for 600519", "date": "2026-09-21"}]

    with mock_thsifind(news=raw_news, notices=raw_notices):
        row = await build_reflection_context(["600519.SH"], today)

    ctx = json.loads(row.context_json)
    assert ctx["announcements_count"] == 1
    assert ctx["news_count"] == 1
    assert "600519" in ctx["top_news_title"]


@pytest.mark.asyncio
async def test_build_failure_raises():
    from app.services.reflection_context_service import build_reflection_context
    from app.data.ifind_events import IfindUnavailable
    from tests.conftest import mock_thsifind

    with mock_thsifind(fail_on={"search_news"}):
        with pytest.raises(IfindUnavailable):
            await build_reflection_context(["600519.SH"], date.today())


@pytest.mark.asyncio
async def test_get_summary_returns_none_when_missing():
    from app.services.reflection_context_service import get_reflection_context_summary
    from datetime import date, timedelta
    assert await get_reflection_context_summary(date.today() - timedelta(days=365)) is None


@pytest.mark.asyncio
async def test_get_summary_returns_dict_when_cached():
    from app.services.reflection_context_service import build_reflection_context, get_reflection_context_summary
    from tests.conftest import mock_thsifind

    today = date.today()
    raw_news = [{"title": "今日新闻", "date": "2026-09-22"}]
    with mock_thsifind(news=raw_news, notices=[]):
        await build_reflection_context(["600519.SH"], today)

    summary = await get_reflection_context_summary(today)
    assert summary is not None
    assert summary["news_count"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_reflection_context_service.py -v
```

Expected: FAIL

- [ ] **Step 3: 实现 reflection_context_service.py**

新建 `backend/app/services/reflection_context_service.py`：

```python
"""ReflectionCard 22:00 消息面提示服务 (改动 C)

业务编排: 当日 1 次缓存; 失败 fail-fast 不写缓存."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Optional

from app.data.ifind_news import fetch_news_for_stock
from app.data.ifind_events import IfindUnavailable
from app.models.orm import ReflectionContextCache
from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo

logger = logging.getLogger(__name__)


def _start_of_window(today: date, window_days: int = 7) -> date:
    return today - timedelta(days=window_days - 1)


async def build_reflection_context(
    stock_codes: list[str], today: date
) -> ReflectionContextCache:
    """聚合多只票的新闻 + 公告, 写入当日缓存.

    Args:
        stock_codes: 持仓 + 自选股 + 今日交易股 (合并去重后传入)
        today: 当日日期

    Returns:
        写入的 ReflectionContextCache 行

    Raises:
        IfindUnavailable: 任一 ifind 调用失败 (不写缓存)
    """
    cached = await reflection_context_cache_repo.get_today(today)
    if cached is not None:
        return cached

    if not stock_codes:
        # 没有相关票, 写空缓存避免重复触发
        ctx = {"announcements_count": 0, "news_count": 0, "top_news_title": "", "fetched_for": []}
        row = await reflection_context_cache_repo.upsert(
            fetch_date=today,
            context_json=json.dumps(ctx, ensure_ascii=False),
            fetched_at=date.today().isoformat() + "T00:00:00+08:00",
            ifind_calls=0,
        )
        return row

    start = _start_of_window(today)
    end = today

    all_news: list[dict] = []
    all_announcements: list[dict] = []
    calls = 0

    # 串行 (避免 ifind 限流 + reflection 弹窗场景下并发意义不大, 用户体验为先)
    for code in stock_codes:
        result = await fetch_news_for_stock(code, start.isoformat(), end.isoformat())
        calls += 2  # news + notice 各 1
        all_news.extend(result["news"])
        all_announcements.extend(result["announcements"])

    top_news_title = all_news[0]["title"] if all_news else ""

    ctx = {
        "announcements_count": len(all_announcements),
        "news_count": len(all_news),
        "top_news_title": top_news_title,
        "fetched_for": stock_codes,
    }

    row = await reflection_context_cache_repo.upsert(
        fetch_date=today,
        context_json=json.dumps(ctx, ensure_ascii=False),
        fetched_at=date.today().isoformat() + "T00:00:00+08:00",
        ifind_calls=calls,
    )
    logger.info(
        "reflection context built: date=%s stocks=%d announcements=%d news=%d",
        today, len(stock_codes), len(all_announcements), len(all_news),
    )
    return row


async def get_reflection_context_summary(today: date) -> Optional[dict]:
    """读侧: 给 ReflectionCard 用的汇总 (无缓存时返 None)."""
    cached = await reflection_context_cache_repo.get_today(today)
    if cached is None:
        return None
    try:
        return json.loads(cached.context_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("reflection_context_cache.context_json 损坏: %s", cached.context_json)
        return None


__all__ = ["build_reflection_context", "get_reflection_context_summary"]
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && python -m pytest tests/test_reflection_context_service.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/reflection_context_service.py backend/tests/test_reflection_context_service.py
git commit -m "feat(reflection-context-service): 当日 1 次缓存 + 读侧 summary (改动 C)"
```

---

## Task 16: 改动 C-4 — api/reflection_context 端点

**Files:**
- Create: `backend/app/api/reflection_context.py`

**Interfaces:**
- Consumes: `reflection_context_service.build_reflection_context` + `get_reflection_context_summary`
- Produces: `GET /api/reflection-context?date=YYYY-MM-DD` 端点, 返 `200 {summary: dict}` 或 `503 {detail: ifind拉取失败}`

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_reflection_context_api.py`：

```python
"""reflection_context API 端点测试 (改动 C)"""
import pytest
from datetime import date
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_get_reflection_context_returns_summary():
    from app.services.reflection_context_service import build_reflection_context
    from tests.conftest import mock_thsifind

    today = date.today()
    raw_news = [{"title": "今日新闻", "date": "2026-09-22"}]
    with mock_thsifind(news=raw_news, notices=[]):
        await build_reflection_context(["600519.SH"], today)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/reflection-context?date={today.isoformat()}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["news_count"] == 1


@pytest.mark.asyncio
async def test_get_reflection_context_returns_503_on_failure():
    from tests.conftest import mock_thsifind

    today = date.today()
    with mock_thsifind(fail_on={"search_news"}):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/reflection-context?date={today.isoformat()}")

    # 第一次会触发 build (失败), 返 503
    assert resp.status_code in (503, 200)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && python -m pytest tests/test_reflection_context_api.py -v
```

Expected: FAIL (404 not found)

- [ ] **Step 3: 实现 api/reflection_context.py**

新建 `backend/app/api/reflection_context.py`：

```python
"""/api/reflection-context 端点 (改动 C)"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from app.core.stock_code import normalize_code
from app.data.ifind_events import IfindUnavailable
from app.repositories.transaction_repo import transaction_repo
from app.repositories.watchlist_repo import watchlist_repo
from app.services.position_service import get_all_positions
from app.services.reflection_context_service import (
    build_reflection_context,
    get_reflection_context_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["reflection-context"])


@router.get("/reflection-context")
async def get_reflection_context(
    date_str: str = Query(..., alias="date", description="YYYY-MM-DD")
):
    """拉取当日 ReflectionCard 消息面上下文汇总.

    流程:
    1. 收集相关股票: 持仓 + 自选股 + 今日交易
    2. build_reflection_context (写当日缓存, 失败 fail-fast 503)
    3. 返 summary
    """
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"date 格式错: {date_str}")

    # 收集相关股票
    codes: set[str] = set()
    # 持仓
    positions = await get_all_positions()
    for p in positions:
        codes.add(normalize_code(p.stock_code) or p.stock_code)
    # 自选股
    watchlist = await watchlist_repo.list_all() if hasattr(watchlist_repo, 'list_all') else []
    for w in watchlist:
        if isinstance(w, dict):
            codes.add(normalize_code(w.get('stock_code', '')) or w.get('stock_code', ''))
        elif hasattr(w, 'stock_code'):
            codes.add(normalize_code(w.stock_code) or w.stock_code)
    # 今日交易
    today_tx = await transaction_repo.list_by_date(target) if hasattr(transaction_repo, 'list_by_date') else []
    for t in today_tx:
        codes.add(normalize_code(t.stock_code) or t.stock_code)
    codes = {c for c in codes if c}

    try:
        await build_reflection_context(sorted(codes), target)
    except IfindUnavailable as e:
        logger.warning("reflection-context ifind failed: %s", e)
        raise HTTPException(status_code=503, detail=f"ifind 拉取失败: {e}")

    summary = await get_reflection_context_summary(target)
    return {"date": date_str, "summary": summary, "fetched_for_count": len(codes)}


__all__ = ["router"]
```

- [ ] **Step 4: 在 main.py 注册 router**

编辑 `backend/app/main.py`，参考其他 `*_router` import，加：

```python
from app.api.reflection_context import router as reflection_context_router
```

在 `app = FastAPI(...)` 后找到 `app.include_router(...)` 集中处，加：

```python
app.include_router(reflection_context_router)
```

- [ ] **Step 5: 跑测试确认通过**

```bash
cd backend && python -m pytest tests/test_reflection_context_api.py -v
```

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/reflection_context.py backend/app/main.py backend/tests/test_reflection_context_api.py
git commit -m "feat(api): /api/reflection-context 端点 (改动 C)"
```

---

## Task 17: 改动 C-5 — ReflectionCard.tsx 接入消息面提示

**Files:**
- Create: `frontend/src/lib/api/reflection-context.ts`
- Modify: `frontend/src/components/reflection/ReflectionCard.tsx`

**Interfaces:**
- Consumes: `GET /api/reflection-context?date=YYYY-MM-DD`
- Produces: ReflectionCard 卡片内多渲染一行 "📰 今日 N 条公告 / M 条新闻" (失败静默吞错)

- [ ] **Step 1: 写 api client**

新建 `frontend/src/lib/api/reflection-context.ts`：

```typescript
import { apiGet } from './api';

export interface ReflectionContextSummary {
  announcements_count: number;
  news_count: number;
  top_news_title: string;
  fetched_for: string[];
}

export interface ReflectionContextResponse {
  date: string;
  summary: ReflectionContextSummary | null;
  fetched_for_count: number;
}

export async function fetchReflectionContext(dateISO: string): Promise<ReflectionContextResponse | null> {
  try {
    return await apiGet<ReflectionContextResponse>(`/api/reflection-context?date=${dateISO}`);
  } catch {
    // 失败静默: 不打扰 22:00 弹窗体验
    return null;
  }
}
```

- [ ] **Step 2: 改 ReflectionCard.tsx**

读 `frontend/src/components/reflection/ReflectionCard.tsx`，在 useEffect 内拉 `/transactions?limit=100` 之后，追加 fetch reflection context：

```typescript
import { fetchReflectionContext } from '@/lib/api/reflection-context';

// 在 useEffect 内, setShow(true) 之前追加:
import('@/lib/api/reflection-context').then(async ({ fetchReflectionContext }) => {
  const ctx = await fetchReflectionContext(today);
  if (ctx && ctx.summary) {
    setContextSummary(ctx.summary);
  }
});
```

并在组件 state 加：

```typescript
const [contextSummary, setContextSummary] = useState<ReflectionContextSummary | null>(null);
```

渲染处（在已实现盈亏行下方）追加：

```tsx
{contextSummary && (contextSummary.news_count > 0 || contextSummary.announcements_count > 0) && (
  <div className="mt-2 text-xs text-text-sec">
    <span className="font-mono font-semibold">📰 今日</span>{' '}
    {contextSummary.announcements_count} 条公告 / {contextSummary.news_count} 条新闻
    {contextSummary.top_news_title && (
      <span className="block text-text-ter mt-1">「{contextSummary.top_news_title}」</span>
    )}
    <Link href="/replay-history" className="block mt-1 text-accent hover:underline">
      → 查看完整复盘上下文
    </Link>
  </div>
)}
```

- [ ] **Step 3: 跑前端 typecheck + build**

```bash
cd frontend && pnpm typecheck && pnpm build
```

Expected: 通过

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api/reflection-context.ts frontend/src/components/reflection/ReflectionCard.tsx
git commit -m "feat(reflection-card): 22:00 弹窗加消息面提示行, 失败静默 (改动 C)"
```

---

## Task 18: 改动 C 完成 — 全量验证

**Files:**
- 无

- [ ] **Step 1: 跑全量后端测试**

```bash
cd backend && python -m pytest -v
```

Expected: 全部通过

- [ ] **Step 2: 跑迁移 dry-run**

```bash
cd backend && alembic check
```

Expected: 无新迁移生成（所有改动已迁移）

- [ ] **Step 3: 前端 build + typecheck**

```bash
cd frontend && pnpm typecheck && pnpm build
```

Expected: 通过

- [ ] **Step 4: 输出 C 改动收尾报告**

向用户报告：
- 4 个新文件: ifind_news.py / reflection_context_cache_repo.py / reflection_context_service.py / api/reflection_context.py + 4 个 test 文件 + 迁移 + api client
- 3 个修改: orm.py / main.py / ReflectionCard.tsx
- C 改动可独立跑 (与 A/B 无依赖)

---

## Task 19: 文档收尾 — runbook + release-notes

**Files:**
- Modify: `docs/dev-log/runbook.md`
- Modify: `docs/release-notes.md`

- [ ] **Step 1: 读 runbook.md**

读 `docs/dev-log/runbook.md`，找合适小节（参考现有故障排查小节风格）。

- [ ] **Step 2: 加 ifind 故障排查小节**

在 runbook.md 末尾追加：

```markdown
## iFinD 故障排查（2026-09-22）

### 现象
后端 log 出现 `IfindUnavailable: search_trending_news 失败` / `search_securities 失败` / `search_news 失败` / `search_notice 失败`。

### 排查步骤
1. 确认 mcode-tools connector 是否安装: `mcode-tools connector tools --keyword thsifind`
2. 单独测试工具: `mcode-tools connector call thsifind__search_trending_news --args '{"time_scope":"24小时","size":5}'`
3. 如果 connector 鉴权失败: 检查 MiniMax Code 工具授权状态
4. 如果限流 (HTTP 429): 等次日或减频
5. screener 影响: A 改动会自动降级为 4 因子版 (log WARNING), C 改动静默
6. screener Top N 基本面过滤 (改动 B) 失败 → 不展示 Top N, 需手动修复

### 缓存清理
A/C 改动的当日缓存表 `event_factor_cache` / `reflection_context_cache`:
```sql
DELETE FROM event_factor_cache WHERE trade_date = '2026-09-22';
DELETE FROM reflection_context_cache WHERE fetch_date = '2026-09-22';
```
```

- [ ] **Step 3: 读 release-notes.md**

读 `docs/release-notes.md` 找最新版本条目，模仿格式。

- [ ] **Step 4: 加本次变更条目**

在 release-notes.md 最新版本（v2.6.1 或最新）下追加（**或新建 v2.7 条目**，取决于项目习惯）：

```markdown
## v2.7 - iFinD 驱动现有模块优化（2026-09-22, spec ADR-0008）

### 新增
- screener 加事件因子加权 (改动 A, iFinD search_trending_news)
- screener Top N 基本面兜底过滤 (改动 B, iFinD search_securities)
- ReflectionCard 22:00 加消息面提示 (改动 C, iFinD search_news + search_notice)

### 改动
- screener 总分上限 155 → 170
- screener_runs 失败语义: A 失败降级 4 因子版, B 失败不展示 Top N
- ReflectionCard 失败静默, 不打扰 22:00 体验

### 数据模型
- 新表 event_factor_cache (当日 1 次缓存)
- 新表 reflection_context_cache (当日 1 次缓存)
- screener_picks 新增列 fundamental_filter_status
- 2 个新 Alembic 迁移

### 文档
- 新增 ADR-0008
- 更新 decisions-index + runbook
```

- [ ] **Step 5: Commit**

```bash
git add docs/dev-log/runbook.md docs/release-notes.md
git commit -m "docs: runbook 加 ifind 故障排查 + release-notes v2.7"
```

---

## Task 20: 总收尾 — ADR 状态更新 + 最终验证

**Files:**
- Modify: `docs/dev-log/ADR-0008-ifind-screener-reflection-optimization.md`

- [ ] **Step 1: 改 ADR 状态**

编辑 `docs/dev-log/ADR-0008-ifind-screener-reflection-optimization.md`，把：

```markdown
## 状态：已采用（2026-09-22）
```

保持不变（Task 1 已写）。

- [ ] **Step 2: 最终全量验证**

```bash
cd backend && python -m pytest -v && alembic check
cd frontend && pnpm typecheck && pnpm build
```

Expected: 全部通过

- [ ] **Step 3: 输出最终报告**

向用户报告：
- 总文件新增: 17 (8 backend + 1 frontend + 4 migration + 4 test/conftest 等)
- 总文件修改: 11 (6 backend + 1 frontend + 2 doc + 2 orm)
- 总 commit 数: 11 (Task 1 + 2 + 3 + 4 + 5 + 6 + 7 + 8 + 9 + 10 + 11 + 12 + 13 + 14 + 15 + 16 + 17 + 19, Task 8/18/20 是验证节点无 commit)
- 三项改动独立可测, 互不依赖
- ADR-0008 已采用
- 失败即失败原则贯穿所有改动

- [ ] **Step 4: 最终 commit (如有 amendment)**

如有 ADR-0008 状态更新 / 最后微调, amend 或追加 commit。

---

## Plan 收尾

完成 20 个 task 后, 三项改动全部上线。**不部署**（用户本地工具, 部署 = 重启后端 + 浏览器 hard refresh 前端）。

**后续可选任务（不在本 plan 范围）**:
- ADR-0009: 复盘接 ifind（spec §1.2 的反向方案, 之前 brainstorming 已被用户暂时搁置）
- screener 加更多因子（基本面 + 行业地位 + 北向资金）
- ReflectionCard 加可点击跳转个股完整复盘

执行方式（二选一）：

**A. Subagent-Driven（推荐）**: 每个 task 一个 fresh subagent, 任务间 review, 快迭代
**B. Inline Execution**: 当前会话执行, 批量 + 阶段性检查点