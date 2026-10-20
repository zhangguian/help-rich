# Task 2 Brief: conftest.py 加 mock_thsifind fixture

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 是一个本地 A 股投资辅助工具（branch `main`）。前一轮已交付：
- Spec: `docs/superpowers/specs/2026-09-22-ifind-screener-reflection-optimization-design.md`（commit `ff5d275`）
- Plan: `docs/superpowers/plans/2026-09-22-ifind-screener-reflection-optimization.md`（commit `3d7b9a4`）
- Task 1 ADR-0008: commit `74d6448`

本任务（Task 2 / 20）是**测试基础设施**：在 `conftest.py` 加一个 `mock_thsifind` fixture，后续 Task 3/4/5/9/10/11/13/14/15/16 都会用它来 mock thsifind 工具栏的 4 个 connector 入口。

## Global Constraints (本任务相关)

- 工作分支: `main`
- pytest + pytest-asyncio（项目 `asyncio_mode = "auto"`）
- 测试不真打 ifind（避免扣费 + 限流）
- 容错：写本 fixture 时，patches `app.data.ifind_events._search_trending_news` 等路径可能尚未存在（Task 3/9/13 才创建），patch 不存在路径时静默跳过
- Commit message: `test(conftest): add mock_thsifind fixture for ifind mocking`
- **本地有 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些

## Interfaces from Earlier Tasks

- Consumes: 无（Task 1 是 ADR 文档，与本任务无代码接口依赖）
- Produces:
  - `from tests.conftest import mock_thsifind` —— context manager
  - 调用形式：`with mock_thsifind(trending_news=..., news=..., notices=..., securities=..., fail_on={...}) as m: ...`
  - m.search_trending_news(...) / m.search_news(...) / m.search_notice(...) / m.search_securities(...) 返 mock 返值
  - 当 `fail_on` 含某个工具名时，调对应 mock 抛 `RuntimeError("mocked ifind failure: <name>")`

## Task Description

### Files
- Modify: `backend/tests/conftest.py`（追加 mock_thsifind fixture 在文件末尾，**不要重写文件**）
- Create: `backend/tests/test_conftest_mock.py`

### Steps

#### Step 1: 读现有 conftest.py

读 `backend/tests/conftest.py` 全文，了解现有 fixture 风格（async_session / db_lock / 临时库等）。

#### Step 2: 写失败测试

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

#### Step 3: 跑测试确认失败

```bash
cd backend && python -m pytest tests/test_conftest_mock.py -v
```

Expected: FAIL with `ImportError: cannot import name 'mock_thsifind' from 'tests.conftest'`

#### Step 4: 实现 mock_thsifind fixture

编辑 `backend/tests/conftest.py`，在文件末尾追加（**不要触碰文件其他部分**）：

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

#### Step 5: 验证 fixture 可加载

```bash
cd backend && python -c "from tests.conftest import mock_thsifind; print('fixture importable')"
```

Expected: 输出 `fixture importable`

同时跑测试，应该 2 个都过：

```bash
cd backend && python -m pytest tests/test_conftest_mock.py -v
```

Expected: 2 passed

#### Step 6: Commit

```bash
git add backend/tests/conftest.py backend/tests/test_conftest_mock.py
git commit -m "test(conftest): add mock_thsifind fixture for ifind mocking"
```

## Acceptance Criteria

- conftest.py 末尾追加 mock_thsifind fixture（其他内容不动）
- 新文件 test_conftest_mock.py 存在
- `python -c "from tests.conftest import mock_thsifind"` 成功
- 测试 `tests/test_conftest_mock.py` 2 passed
- 1 commit 落在 main，仅含 2 个文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- 文件末尾应有 trailing newline（项目惯例）

## Ambiguity Resolution

- **fixture 必须容错**：4 个 patch 路径在 Task 2 写入时还不存在。fixture 必须 try/except `ModuleNotFoundError` / `AttributeError` 静默跳过。**不要**用 `importlib.util.find_spec` 预检（更复杂），直接 try/except 即可
- **fixture 必须不改 conftest.py 的其他 fixture**：只追加，不重写
- **test_conftest_mock.py** 必须独立运行（不需要 db / 网络 / iTunes stub）

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-2-report.md`

报告应包含：
- 实现了什么
- TDD evidence (RED + GREEN 命令 + 关键输出)
- 文件变更列表
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns