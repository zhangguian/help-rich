# Task 3 Brief: 改动 A-1 — ifind_events 包装层

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 是一个本地 A 股投资辅助工具（branch `main`）。前几轮已交付：
- Spec: `docs/superpowers/specs/2026-09-22-ifind-screener-reflection-optimization-design.md`（commit `ff5d275`）
- Plan: `docs/superpowers/plans/2026-09-22-ifind-screener-reflection-optimization.md`（commit `3d7b9a4`）
- Task 1 ADR-0008: commit `74d6448`
- Task 2 mock_thsifind fixture: commit `67f42aa`

本任务（Task 3 / 20）是**改动 A 的第 1 个 task**——创建 `app.data.ifind_events` 模块，包装 thsifind `search_trending_news` 工具栏入口，归一返回为 `{event_keywords, stock_codes, raw, fetched_at}`。

## Global Constraints (本任务相关)

- 工作分支: `main`
- 后端栈: Python 3.11+ / FastAPI 0.115 / SQLAlchemy 2.0 / Pydantic 2 / aiosqlite / loguru
- 项目已用 `connector__thsifind__*` 工具栏，本任务模块**包装**它（不直接调用）
- 失败语义: 失败即抛 `IfindUnavailable`（spec §3 "失败就是失败"）
- pytest + pytest-asyncio（`asyncio_mode = "auto"`，所以无需装饰但 plan/spec 已写 `@pytest.mark.asyncio`，可保留也可省）
- **本地 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些

## Interfaces from Earlier Tasks

- Consumes: `tests.conftest.mock_thsifind` fixture（Task 2 提供）
- Produces:
  - `from app.data.ifind_events import IfindUnavailable, fetch_trending_events`
  - `async fetch_trending_events(size=20, time_scope='24小时') -> dict` 返 `{fetched_at, event_keywords: set[str], stock_codes: set[str], raw: list[dict]}`

## Task Description

### Files
- Create: `backend/app/data/ifind_events.py`
- Create: `backend/tests/test_ifind_events.py`

### Steps

#### Step 1: 写失败测试

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

#### Step 2: 跑测试确认失败

```bash
cd backend && python -m pytest tests/test_ifind_events.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.ifind_events'`

#### Step 3: 实现 ifind_events.py

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

#### Step 4: 跑测试确认通过

```bash
cd backend && python -m pytest tests/test_ifind_events.py -v
```

Expected: 3 passed

#### Step 5: Commit

```bash
git add backend/app/data/ifind_events.py backend/tests/test_ifind_events.py
git commit -m "feat(ifind-events): 包装 search_trending_news, 归一为 {event_keywords, stock_codes}"
```

## Acceptance Criteria

- 新文件 `backend/app/data/ifind_events.py` 含 `IfindUnavailable` + `fetch_trending_events` + `_search_trending_news`
- 新文件 `backend/tests/test_ifind_events.py` 3 测试
- 3 tests passing, output pristine
- 1 commit on main, 仅含 2 个新文件
- 22 个未提交改动 + 1 个迁移文件未触碰
- 新文件末尾应有 trailing newline

## Ambiguity Resolution

- **`_mcode_call` 导入**: `from mcode_tools_connector import call` 在测试环境 / Windows 环境通常不存在，必须 try/except 降级为 `None`。生产路径在 Windows WSL 或 Linux 上由 MiniMax Code runtime 提供，本地任务不指望它能直接 import
- **`@pytest.mark.asyncio` 装饰器**: 项目 `asyncio_mode = "auto"`，所以严格说不需要装饰器。但 brief 写了就保留——加装饰器是安全的
- **`fetch_trending_events` 返回 `set[str]`** 而非 `list[str]` —— 测试断言 `isinstance(..., set)`，必须返 set
- **股票代码归一**: `s.strip().upper()` (统一大写)
- **tag 归一**: `t.strip()` (大小写保留，因为 ifind tag 可能是 "AI" / "ai")

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-3-report.md`

报告应包含：
- 实现了什么
- TDD evidence (RED command + 关键输出 / GREEN command + 关键输出)
- 文件变更列表
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns