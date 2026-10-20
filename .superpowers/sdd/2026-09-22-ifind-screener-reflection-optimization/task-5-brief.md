# Task 5 Brief: 改动 A-3 — event_factor_service 业务编排

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1 ADR-0008: `74d6448`
- Task 2 fixture (AsyncMock): `84cba33`
- Task 3 ifind_events wrapper: `c8f9a0d`
- Task 4 event_factor_cache_repo + migration + EventFactorCache ORM: `3be76ad`

本任务（Task 5 / 20）创建**改动 A 的业务编排层**——`event_factor_service` 把 ifind_events + 仓储粘合起来，让 screener 可以调用。

## Global Constraints (本任务相关)

- 工作分支: `main`
- 业务编排: 当日 1 次缓存，**已缓存则跳过**（spec §5）
- 失败语义: ifind 失败 → `IfindUnavailable`，**不写缓存**
- pytest + pytest-asyncio (`asyncio_mode = "auto"`)
- **本地 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些
- **特别警告**: Task 4 implementer 曾吃掉过用户的 orm.py 改动。这次**只新增 2 个文件**，**不动 orm.py**

## Interfaces from Earlier Tasks

- Consumes:
  - `from app.data.ifind_events import fetch_trending_events, IfindUnavailable`
  - `from app.repositories.event_factor_cache_repo import event_factor_cache_repo`
  - `from app.models.orm import EventFactorCache`
  - `from tests.conftest import mock_thsifind`
- Produces:
  - `from app.services.event_factor_service import build_event_factor_cache, get_event_factor_codes`
  - `async build_event_factor_cache(date) -> EventFactorCache` —— 拉 ifind + 写缓存，已缓存直接返
  - `async get_event_factor_codes(date) -> set[str]` —— 读侧：返 stock_codes 集合（无缓存返空集）

## Task Description

### Files
- Create: `backend/app/services/event_factor_service.py`
- Create: `backend/tests/test_event_factor_service.py`
- **NOT** modify `backend/app/services/scoring.py`（plan 里写 "新增 event_score 但本 task 只加占位 import" —— **跳过**）

### Steps

#### Step 1: 写失败测试

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
    with mock_thsifind(fail_on={"search_trending_news"}):
        row = await build_event_factor_cache(today)

    assert "预填" in row.event_keywords_json


@pytest.mark.asyncio
async def test_get_event_factor_codes_returns_set():
    from app.services.event_factor_service import get_event_factor_codes
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo

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

#### Step 2: 跑测试确认失败

```bash
cd backend && python -m pytest tests/test_event_factor_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.event_factor_service'`

#### Step 3: 实现 event_factor_service.py

新建 `backend/app/services/event_factor_service.py`：

```python
"""screener 事件因子服务 (改动 A)

业务编排: 当日 1 次缓存; 失败 fail-fast 不写缓存."""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

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
    logger.info(
        "event factor cache built: trade_date=%s codes=%d",
        trade_date, len(result["stock_codes"]),
    )
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
        logger.warning(
            "event_factor_cache.stock_codes_json 损坏: %s", cached.stock_codes_json,
        )
        return set()


__all__ = ["build_event_factor_cache", "get_event_factor_codes"]
```

**注**: brief 原文里有 `from typing import Optional, set`（plan 错）；`set` 不是 typing 成员，必须**只**导入 `Optional`。已修正。

#### Step 4: 跑测试确认通过

```bash
cd backend && python -m pytest tests/test_event_factor_service.py -v
```

Expected: 3 passed

#### Step 5: Commit

```bash
git add backend/app/services/event_factor_service.py backend/tests/test_event_factor_service.py
git commit -m "feat(event-factor-service): 当日 1 次缓存 + 读侧 get_event_factor_codes (改动 A)"
```

## Acceptance Criteria

- `backend/app/services/event_factor_service.py` 存在
- `backend/tests/test_event_factor_service.py` 存在，3 tests
- 3/3 tests passing, output pristine
- 1 commit on main，**仅含** 2 个新文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- `scoring.py` **未**被修改（plan 的原意是"占位 import"，但 plan 自己也注释掉了这一步）
- `orm.py` **未**被修改（极重要！Task 4 曾误吃；这次只 add 新文件）
- 所有新文件末尾 trailing newline

## Ambiguity Resolution

- **`scoring.py` 不动**：plan Step 3 注释 "but 本 task 只加占位 import，下一 task 实装" —— 这一步实际无用，Task 6 会单独做 `event_score` + config 常量。**完全跳过 scoring.py 修改**
- **`orm.py` 不动**：Task 4 误吃过，这次**绝对不动**
- **`IfindUnavailable` 处理**：spec 说"失败 fail-fast 不写缓存"。service 层**直接抛 `IfindUnavailable`**，不 catch（让上层 screener 决定怎么处理——目前 screener 失败时降级 4 因子版，见 spec §4.1）
- **缓存已存在时**：直接返 cached，不调 ifind（spec §5）
- **`get_event_factor_codes` 返回值**：永远是 `set[str]`（无缓存返空 `set()`，损坏 JSON 也返空 `set()`）
- **`stock_codes` 排序**：`sorted(result["stock_codes"])` 让 JSON 稳定，便于审计
- **测试运行**：`mock_thsifind(fail_on={"search_trending_news"})` 触发 fixture 内部 RuntimeError，service 不应调 ifind（因为已缓存直接返），所以测试通过

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-5-report.md`

报告应包含：
- 实现了什么
- TDD evidence (RED + GREEN 命令 + 关键输出)
- 文件变更列表
- Commit hash + 短 subject
- self-review 发现（**重点**：确认 orm.py + scoring.py 完全未改）
- 任何 issues 或 concerns