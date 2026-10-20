# Task 9 Brief: 改动 B-1 — ifind_fundamentals 包装层

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。改动 A 已完成（Tasks 1-8）。本任务开始**改动 B**（基本面兜底过滤）。

- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-8 commits: `74d6448` → `84cba33` → `c8f9a0d` → `3be76ad` → `e493ee2` → `99a037a` → `7888122`
- 改动 A 完成：screener 评分 5 因子（155→170）
- 改动 B 目标：screener Top N 末尾追加基本面兜底过滤

本任务（Task 9 / 20）创建**改动 B 的数据层**——`ifind_fundamentals` 模块，包装 thsifind `search_securities` 工具栏。

## Global Constraints

- 工作分支: `main`
- pytest + pytest-asyncio（**用 `.venv\Scripts\python.exe`** 跑测试，system python 缺 fastapi）
- 项目 .venv 已配：`backend\.venv\Scripts\python.exe`
- 测试运行命令：`cd backend && .venv\Scripts\python.exe -m pytest tests/test_ifind_fundamentals.py -v`
- **本地 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些
- **本任务只创建 2 个新文件**（同 Task 3 模式）

## Interfaces from Earlier Tasks

- Consumes:
  - `from app.data.ifind_events import IfindUnavailable`（统一异常基类）
  - `from tests.conftest import mock_thsifind`（Task 2 fixture，已 AsyncMock）
  - thsifind 工具栏 `search_securities`
- Produces:
  - `from app.data.ifind_fundamentals import is_hit_fundamental_filter`
  - `async is_hit_fundamental_filter(stock_code, query, market='A股') -> bool`

## Task Description

### Files
- Create: `backend/app/data/ifind_fundamentals.py`
- Create: `backend/tests/test_ifind_fundamentals.py`

### Steps

#### Step 1: 写失败测试

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

#### Step 2: 跑测试确认失败（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_ifind_fundamentals.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.ifind_fundamentals'`

#### Step 3: 实现 ifind_fundamentals.py

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

#### Step 4: 跑测试确认通过（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_ifind_fundamentals.py -v
```

Expected: 4 passed

#### Step 5: Commit

```bash
git add backend/app/data/ifind_fundamentals.py backend/tests/test_ifind_fundamentals.py
git commit -m "feat(ifind-fundamentals): 包装 search_securities, 单只票基本面筛 (改动 B)"
```

## Acceptance Criteria

- 新文件 `backend/app/data/ifind_fundamentals.py` 含 `is_hit_fundamental_filter` + `_search_securities`（mock target）+ `__all__`
- 新文件 `backend/tests/test_ifind_fundamentals.py` 含 4 tests
- 4/4 tests passing via `.venv\Scripts\python.exe -m pytest` (system python 会 collection error，**不要**用)
- 1 commit on main，仅含 2 个新文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- **不动 orm.py / config.py / scoring.py / screener_service.py**（这些是 22 modified 文件之一）

## Ambiguity Resolution

- **pytest 用 `.venv\Scripts\python.exe`**，**不是** system `python` —— system python 缺 fastapi，pytest collection error
- **`IfindUnavailable` 复用** `app.data.ifind_events`（spec §3.3 强调统一异常）
- **mock target `_search_securities`** 必须在模块内定义（Task 2 fixture 的 patch 路径是 `app.data.ifind_fundamentals._search_securities`）
- **brief 字面** 与 Task 3 ifind_events 类似，但只 1 个 `search_securities` 子调用，无事件类复杂归一

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-9-report.md`

报告应包含：
- 实现了什么
- TDD evidence (RED + GREEN 命令 + 关键输出)
- 文件变更列表
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns