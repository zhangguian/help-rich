# Task 13 Brief: 改动 C-1 — ifind_news 包装层

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。改动 A + B 已完成（Tasks 1-12）。本任务开始**改动 C**（ReflectionCard 22:00 消息面提示）。

- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-12 commits: `74d6448` → `84cba33` → `c8f9a0d` → `3be76ad` → `e493ee2` → `99a037a` → `7888122` → `dc24c10` → `e128eb7` → `69e9f6e` → `ccc87ca`
- 改动 A 完成：screener 评分 5 因子（155→170）
- 改动 B 完成：screener Top N 末尾基本面兜底过滤
- 改动 C 目标：ReflectionCard 22:00 弹窗增加消息面上下文提示行

本任务（Task 13 / 20）创建**改动 C 的数据层**——`ifind_news` 模块，包装 thsifind `search_news` + `search_notice` 工具栏。

## Global Constraints

- 工作分支: `main`
- pytest + pytest-asyncio（**用 `.venv\Scripts\python.exe`** 跑测试，system python 缺 fastapi）
- 项目 .venv 已配：`backend\.venv\Scripts\python.exe`
- 测试运行命令：`cd backend && .venv\Scripts\python.exe -m pytest tests/test_ifind_news.py -v`
- **本地 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些
- **本任务只创建 2 个新文件**（同 Task 3 / Task 9 模式）

## Interfaces from Earlier Tasks

- Consumes:
  - `from app.data.ifind_events import IfindUnavailable`（统一异常基类，spec §3.3）
  - `from tests.conftest import mock_thsifind`（Task 2 fixture，已 AsyncMock）
  - thsifind 工具栏 `search_news` + `search_notice`
- Produces:
  - `from app.data.ifind_news import fetch_news_for_stock`
  - `async fetch_news_for_stock(stock_code, start_date, end_date) -> dict` 返回 `{stock_code, announcements: list, news: list, fetched_at}`

## Task Description

### Files
- Create: `backend/app/data/ifind_news.py`
- Create: `backend/tests/test_ifind_news.py`

### Steps

#### Step 1: 写失败测试

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

#### Step 2: 跑测试确认失败（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_ifind_news.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.ifind_news'`

#### Step 3: 实现 ifind_news.py

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

#### Step 4: 跑测试确认通过（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_ifind_news.py -v
```

Expected: 4 passed

#### Step 5: Commit

```bash
git add backend/app/data/ifind_news.py backend/tests/test_ifind_news.py
git commit -m "feat(ifind-news): 包装 search_news + search_notice (改动 C)"
```

## Acceptance Criteria

- 新文件 `backend/app/data/ifind_news.py` 含 `fetch_news_for_stock` + `_search_news` + `_search_notice`（mock targets）+ `_normalize_items` + `__all__`
- 新文件 `backend/tests/test_ifind_news.py` 含 4 tests
- 4/4 tests passing via `.venv\Scripts\python.exe -m pytest` (system python 会 collection error，**不要**用)
- 1 commit on main，仅含 2 个新文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- **不动 orm.py / config.py / scoring.py / screener_service.py / ReflectionCard.tsx**（这些是 22 modified 文件之一）

## Ambiguity Resolution

- **pytest 用 `.venv\Scripts\python.exe`**，**不是** system `python` —— system python 缺 fastapi，pytest collection error
- **`IfindUnavailable` 复用** `app.data.ifind_events`（spec §3.3 强调统一异常）
- **mock targets `_search_news` / `_search_notice`** 必须在模块内定义（Task 2 fixture 的 patch 路径是 `app.data.ifind_news._search_news` / `_search_notice`）
- **mock_thsifind 用法**：`with mock_thsifind(news=raw_news, notices=raw_notices):` 提供 news + notices；`with mock_thsifind(fail_on={"search_news"}):` 模拟该工具失败（按 Task 2 fixture contract）
- **改动 C 是 22:00 弹窗用**，不是盘中实时调用；size 默认 5/5 即可，无需大数量
- **brief 字面** 与 Task 3 ifind_events 类似，但有 2 个子调用（search_news + search_notice），返回结构是 `{stock_code, announcements, news, fetched_at}` 而非 `{event_keywords, stock_codes}`

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-13-report.md`

报告应包含：
- 实现了什么
- TDD evidence (RED + GREEN 命令 + 关键输出)
- 文件变更列表
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns