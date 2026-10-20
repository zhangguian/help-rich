# Task 15 Brief: 改动 C-3 — reflection_context_service 业务编排

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-14 commits: `74d6448` → `84cba33` → `c8f9a0d` → `3be76ad` → `e493ee2` → `99a037a` → `7888122` → `dc24c10` → `e128eb7` → `69e9f6e` → `ccc87ca` → `bc37119` → `52b280b`
- 改动 A + B完成（Tasks 1-12）
- 改动 C 数据层完成（Tasks 13-14：ifind_news wrapper + reflection_context_cache_repo）
- 本任务开始改动 C 服务层——reflection_context_service 业务编排

## Global Constraints

- 工作分支: `main`
- pytest 用 `.venv\Scripts\python.exe -m pytest`
- **本地 22 个未提交改动 + 1 个 untracked Alembic migration** —— 不动这些
- 测试运行命令：`cd backend && .venv\Scripts\python.exe -m pytest tests/test_reflection_context_service.py -v`
- PowerShell `&&` NOT supported — 用 `;`
- 失败即失败（spec §3.1）：ifind 调用失败 → 抛 `IfindUnavailable`，不写缓存
- `IfindUnavailable` 复用 from `app.data.ifind_events`

## Interfaces from Earlier Tasks

- Consumes:
  - `from app.data.ifind_news import fetch_news_for_stock` (Task 13)
  - `from app.data.ifind_events import IfindUnavailable` (Task 3)
  - `from app.models.orm import ReflectionContextCache` (Task 14)
  - `from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo` (Task 14)
- Produces:
  - `from app.services.reflection_context_service import build_reflection_context`
  - `async build_reflection_context(stock_codes: list[str], today: date) -> ReflectionContextCache`
  - `async get_reflection_context_summary(today: date) -> dict | None`

## Task Description

### Files
- Create: `backend/app/services/reflection_context_service.py`
- Create: `backend/tests/test_reflection_context_service.py`

### Steps

#### Step 1: 写失败测试

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
    # 给一只票各 mock 一条公告 + 一条新闻
    raw_news = [{"title": f"今日新闻 for 600519", "date": "2026-09-22"}]
    raw_notices = [{"title": f"今日公告 for 600519", "date": "2026-09-21"}]

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

    far_past = date.today() - timedelta(days=365)
    assert await get_reflection_context_summary(far_past) is None


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

#### Step 2: 跑测试确认失败（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_reflection_context_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.reflection_context_service'`

#### Step 3: 实现 reflection_context_service.py

新建 `backend/app/services/reflection_context_service.py`：

```python
"""ReflectionCard 22:00 消息面提示服务 (改动 C)

业务编排: 当日 1 次缓存; 失败 fail-fast 不写缓存."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.data.ifind_news import fetch_news_for_stock
from app.data.ifind_events import IfindUnavailable
from app.models.orm import ReflectionContextCache
from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo

logger = logging.getLogger(__name__)


_CN_TZ = timezone(timedelta(hours=8))


def _fetched_at_now() -> str:
    return datetime.now(_CN_TZ).isoformat()


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
            fetched_at=_fetched_at_now(),
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
        fetched_at=_fetched_at_now(),
        ifind_calls=calls,
    )
    logger.info(
        "reflection context built: date=%s stocks=%d announcements=%d news=%d",
        today, len(stock_codes), len(all_announcements), len(all_news),
    )
    return row


async def get_reflection_context_summary(today: date) -> Optional[dict]:
    """读侧: 给 Reflectioncard 用的汇总 (无缓存时返 None)."""
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

**Note on `fetched_at`**: brief plan literal text `date.today().isoformat() + "T00:00:00+08:00"` is buggy (always returns today's date, not `today` arg). Use the `_fetched_at_now()` helper with CST timezone — matches `event_factor_service.py` pattern of using the actual fetch time.

#### Step 4: 跑测试确认通过（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_reflection_context_service.py -v
```

Expected: 4 passed

#### Step 5: Commit

```bash
git add backend/app/services/reflection_context_service.py backend/tests/test_reflection_context_service.py
git commit -m "feat(reflection-context-service): 当日 1 次缓存 + 读侧 summary (改动 C)"
```

## Acceptance Criteria

- `backend/app/services/reflection_context_service.py` 含 2 个公开函数 + 1 个模块级常量 + `__all__`
- `build_reflection_context` 失败抛 `IfindUnavailable`，**不**写缓存（缓存仍为空）
- `build_reflection_context` 写入缓存 schema `{announcements_count, news_count, top_news_title, fetched_for}`
- `get_reflection_context_summary` 无缓存返 None，有缓存返 dict；损坏 JSON 返 None + warn log
- 4/4 tests passing via `.venv\Scripts\python.exe`
- 1 commit on main，仅含 2 个新文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- 失败 fail-fast（spec §3.1 硬约束）

## Ambiguity Resolution

- **`fetched_at` 时间**：用 `_fetched_at_now()` helper 返回 CST ISO 字符串，**不**用 brief literal `date.today().isoformat() + ...` （buggy —— 永远返回 today 而非 `today` arg）
- **`_start_of_window`** 是 7 日窗口（brief plan 默认）
- **`window_days=7`** 计算公式：`today - (window_days - 1)` —— 即返回 today - 6 = 7 日窗口
- **空 `stock_codes` 列表**：写空缓存（counts=0）避免重复触发 —— 比抛错更友好
- **`fetched_for` 字段**：传整个 `stock_codes` 列表（**不去重**），调用方负责去重
- **`top_news_title`**：取第一个 news 的 title，没有则空串
- **`mock_thsifind(fail_on={"search_news"})`**：触发 IfindUnavailable，验证 build 不写缓存
- **风格**：参考 `backend/app/services/event_factor_service.py` 的 `build_xxx` + `get_xxx` 双函数 pattern

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-15-report.md`

报告应包含：
- 实现了什么
- RED + GREEN 命令 + 输出（用 `.venv\Scripts\python.exe`）
- 文件变更列表
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concern
- **关键**：paste `git show --stat HEAD` 输出 + 解释 `fetched_at` 修正理由（why datetime.now vs brief literal）