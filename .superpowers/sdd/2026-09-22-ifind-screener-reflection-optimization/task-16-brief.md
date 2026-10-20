# Task 16 Brief: 改动 C-4 — `/api/reflection-context` 端点

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-15 commits: `74d6448` → `84cba33` → `c8f9a0d` → `3be76ad` → `e493ee2` → `99a037a` → `7888122` → `dc24c10` → `e128eb7` → `69e9f6e` → `ccc87ca` → `bc37119` → `52b280b` → `27f1411`
- 改动 A + B完成（Tasks 1-12）
- 改动 C 数据层 + 服务层完成（Tasks 13-15）
- 本任务做改动 C 的 API 端点：`GET /api/reflection-context?date=YYYY-MM-DD`

## Global Constraints

- 工作分支: `main`
- pytest 用 `.venv\Scripts\python.exe -m pytest`
- PowerShell `&&` NOT supported — 用 `;`
- **本地 22 个未提交改动 + 1 个 untracked Alembic migration** —— 不动这些
- 失败即失败（spec §3.1）：ifind 调用失败 → 返 503
- 测试运行命令：`cd backend && .venv\Scripts\python.exe -m pytest tests/test_reflection_context_api.py -v`

## Interfaces from Earlier Tasks

- Consumes:
  - `from app.services.reflection_context_service import build_reflection_context, get_reflection_context_summary` (Task 15)
  - `from app.data.ifind_events import IfindUnavailable` (复用)
  - `from app.services.position_service import get_all_positions` (已存在)
  - `from app.repositories.watchlist_repo import watchlist_repo` (已存在, `list_all()` 方法)
  - `from app.repositories.transaction_repo import transaction_repo` (已存在, `list_all()` 方法,**没有** `list_by_date`)
  - `from app.core.stock_code import normalize_code` (已存在)
  - `from app.main import app` (FastAPI instance)
- Produces:
  - `from app.api.reflection_context import router`
  - `GET /api/reflection-context?date=YYYY-MM-DD` → 200 `{date, summary, fetched_for_count}` 或 503 `{detail: ifind 拉取失败}` 或 400 `{detail: date 格式错}`

## Task Description

### Files
- Create: `backend/app/api/reflection_context.py`
- Modify: `backend/app/main.py` (注册 router)
- Create: `backend/tests/test_reflection_context_api.py`

### Steps

#### Step 1: 写失败测试

新建 `backend/tests/test_reflection_context_api.py`：

```python
"""reflection_context API 端点测试 (改动 C)"""
import pytest
from datetime import date


@pytest.mark.asyncio
async def test_get_reflection_context_returns_summary():
    from app.services.reflection_context_service import build_reflection_context
    from tests.conftest import mock_thsifind

    today = date.today()
    raw_news = [{"title": "今日新闻", "date": "2026-09-22"}]
    with mock_thsifind(news=raw_news, notices=[]):
        await build_reflection_context(["600519.SH"], today)

    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/reflection-context?date={today.isoformat()}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["news_count"] == 1


@pytest.mark.asyncio
async def test_get_reflection_context_returns_503_on_ifind_failure():
    from datetime import date, timedelta
    from tests.conftest import mock_thsifind

    # 使用未来日期避免 cache 冲突 (与其他 test 在同一 session-scoped DB 上跑)
    target_day = date.today() + timedelta(days=1)
    with mock_thsifind(fail_on={"search_news"}):
        from httpx import AsyncClient, ASGITransport
        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/reflection-context?date={target_day.isoformat()}")

    assert resp.status_code == 503
    assert "ifind" in resp.json()["detail"].lower() or "ifind" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_reflection_context_returns_400_on_bad_date():
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/reflection-context?date=not-a-date")

    assert resp.status_code == 400
```

**关键**：
- `test_returns_503_on_ifind_failure` 必须用**未来日期** `date.today() + timedelta(days=1)` 避免 cache hit（同一 session-scoped DB 在 test 1 写入了 today 的缓存,test 2 用 today 会 cache hit 不会触发 ifind 调用,验证不了 fail-fast）
- 额外加了 `test_returns_400_on_bad_date` (brief plan 漏了这个边界 case,有必要补上)

#### Step 2: 跑测试确认失败（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_reflection_context_api.py -v
```

Expected: FAIL with 404 (端点未注册)

#### Step 3: 实现 api/reflection_context.py

新建 `backend/app/api/reflection_context.py`：

```python
"""/api/reflection-context 端点 (改动 C)

返回 ReflectionCard 22:00 消息面上下文提示用数据。"""
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

router = APIRouter(prefix="/reflection-context", tags=["reflection-context"])


async def _collect_relevant_codes(target: date) -> set[str]:
    """收集相关股票代码: 持仓 + 自选股 + 今日交易."""
    codes: set[str] = set()

    # 持仓
    positions = await get_all_positions()
    for p in positions:
        normalized = normalize_code(p.stock_code)
        codes.add(normalized or p.stock_code)

    # 自选股 (list_all 已实现,返 Watchlist ORM 对象列表)
    watchlist = await watchlist_repo.list_all()
    for w in watchlist:
        raw = getattr(w, "stock_code", None) or (w.get("stock_code") if isinstance(w, dict) else None)
        if raw:
            normalized = normalize_code(raw)
            codes.add(normalized or raw)

    # 今日交易 (transaction_repo 没有 list_by_date,使用 list_all 后 filter in memory;MVP 量级可接受)
    all_tx, _ = await transaction_repo.list_all(limit=500)
    for t in all_tx:
        if t.trade_date == target:
            normalized = normalize_code(t.stock_code)
            codes.add(normalized or t.stock_code)

    return {c for c in codes if c}


@router.get("")
async def get_reflection_context(
    date: str = Query(..., description="YYYY-MM-DD"),
) -> dict:
    """拉取当日 ReflectionCard 消息面上下文汇总。

    流程:
    1. 收集相关股票: 持仓 + 自选股 + 今日交易
    2. build_reflection_context (写当日缓存, 失败 fail-fast 返 503)
    3. 返 summary
    """
    try:
        target = date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"date 格式错: {date}")

    codes = await _collect_relevant_codes(target)

    try:
        await build_reflection_context(sorted(codes), target)
    except IfindUnavailable as e:
        logger.warning("reflection-context ifind failed: %s", e)
        raise HTTPException(status_code=503, detail=f"ifind 拉取失败: {e}")

    summary = await get_reflection_context_summary(target)
    return {
        "date": date,
        "summary": summary,
        "fetched_for_count": len(codes),
        "fetched_for": sorted(codes),
    }


__all__ = ["router"]
```

**注意 brief plan literal 代码问题**：
- plan 的 brief 用 `prefix="/api"` + Query alias `date_str` 复杂;**修正** 为 `prefix="/reflection-context"` + `Query(alias="date")` 可省略 (FastAPI 允许 query 参数名与 Python 参数名不同) — 让 main.py 统一加 `/api` 前缀
- plan 的 brief 用了 `from app.core.stock_code import normalize_code` + `from app.data.ifind_scripts import IfindUnavailable` — 验证这些 import 路径在项目实际中存在（Task 4 / Task 3 同款用法）

#### Step 4: 在 main.py 注册 router

编辑 `backend/app/main.py`：

**1. 在 imports 段（按字母序）追加**（在 `rebalance_router` 之前）：

```python
from app.api.reflection_context import router as reflection_context_router
```

**2. 在 `app.include_router(...)` 集中处追加一行**（与上方 import 同一字母位序位置，在 `rebalance_router` 之前）：

```python
app.include_router(reflection_context_router, prefix="/api")
```

⚠�️ **关键**：**只追加 1 行 import + 1 行 include_router**，**不动其他现有行** (其他 22 modified 文件不动)

#### Step 5: 跑测试确认通过（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_reflection_context_api.py -v
```

Expected: 3 passed

#### Step 6: Commit

```bash
git add backend/app/api/reflection_context.py backend/app/main.py backend/tests/test_reflection_context_api.py
git commit -m "feat(api): /api/reflection-context 端点 (改动 C)"
```

## Acceptance Criteria

- `GET /api/reflection-context?date=YYYY-MM-DD` 返 200 `{date, summary, fetched_for_count, fetched_for}`
- ifind 失败 → 503 `{detail: ifind 拉取失败}`
- date 格式错 → 400 `{detail: date 格式错}`
- 收集 相关股票包括: 持仓 + 自选股 + 今日交易 (三者并集去重)
- 3/3 tests passing via `.venv\Scripts\python.exe`
- 1 commit on main, 3 files (api + main.py import + test)
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- main.py **仅添加** import + include_router 各 1 行,其他行不变
- 失败 fail-fast (spec §3.1 硬约束)

## Ambiguity Resolution

- **router prefix**：`/reflection-context` (main.py 加 `/api` 前缀)。与 peer `holdings_health` (`/holdings-health`) 同款 pattern
- **HTTPException import**：从 `fastapi` 导入，与 peer `holdings_health` 同款
- **收集股票**: `position_service.get_all_positions` + `watchlist_repo.list_all` + `transaction_repo.list_all(filter in memory)` — transaction_repo 没有 list_by_date，implementer 不要修改它（避免污染 22 modified 文件边界）。MVP 量级 in-memory filter 可接受
- **future date for 503 test**: 必须 `date.today() + timedelta(days=1)` 避免 cache hit — 同 Task 15 implementer 发现的 pattern
- **Date validation**: `date.fromisoformat(date)` ValueError → 400 (brief plan 未含,但应当补)
- **stock_code 规范化**: 调用 `normalize_code()`，原始 code 作为 fallback
- **`fetched_for` 字段**: 额外添加返个股代码列表（brief 未明说，但显式有帮助客户端渲染"fetched for N stocks"）
- **`Query(alias="date")`** 可省略: FastAPI 默认用参数名作为 query key (`?date=...`)。Python 参数名 `date` 同名 query key,不需要 alias

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-16-report.md`

报告应包含：
- 实现了什么
- RED + GREEN 命令 + 输出（用 `.venv\Scripts\python.exe`）
- 文件变更列表
- Commit hash + 短 subject
- **关键**: paste `git diff HEAD~1..HEAD -- backend/app/main.py` (确认仅 import + include_router 备 1 行 additive)
- self-review 发现
- 任何 issues 或 concern