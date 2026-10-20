# Retrofit Brief: AsyncMock fixture + remove wrapper adapter (Tasks 2 & 3 amend)

> Plan-level decision: retrofit Task 2's `mock_thsifind` fixture from sync `MagicMock` to `AsyncMock` so subsequent ifind wrappers (Tasks 3/9/13) stay clean (no `inspect.iscoroutine` adapter).

## Context

Current state (commit history):
- HEAD `367b756` — Task 3 (ifind_events wrapper) — added `inspect.iscoroutine` adapter to bridge sync fixture / async helper
- HEAD~1 `67f42aa` — Task 2 (mock_thsifind fixture) — uses sync `MagicMock`
- HEAD~2 `74d6448` — Task 1 (ADR-0008)
- HEAD~3 `3d7b9a4` — Plan

Local uncommitted state (DO NOT touch): 22 modified files + 1 untracked Alembic migration.

## Goal

Eliminate the `inspect.iscoroutine` adapter pattern. After this amend:
- Task 2 fixture provides `AsyncMock` for the 4 search_* mock slots (matches async helper signature)
- Task 3 wrapper is byte-identical to the brief (no `import inspect`, no adapter)
- Task 2's test calls `await m.search_*` (since `AsyncMock` returns awaitable)
- All tests pass pristine
- Commit history ends up clean: `74d6448` (ADR) → amended Task 2 → amended Task 3, OR new commits (e.g., `67f42aa-v2` and `367b756-v2`)

## Tasks (in order)

### A1. Resync fixture to AsyncMock

Modify `backend/tests/conftest.py` (Task 2 fixture, lines 80/86/92/98):

Replace each `MagicMock(return_value=...)` for the 4 search slots with `AsyncMock(return_value=...)`:

```python
from unittest.mock import AsyncMock, MagicMock, patch
...
m.search_trending_news = (
    _maybe_fail("search_trending_news")
    if "search_trending_news" in fail_on
    else AsyncMock(return_value=trending_news if trending_news is not None else [])
)
m.search_news = (
    _maybe_fail("search_news")
    if "search_news" in fail_on
    else AsyncMock(return_value=news if news is not None else [])
)
m.search_notice = (
    _maybe_fail("search_notice")
    if "search_notice" in fail_on
    else AsyncMock(return_value=notices if notices is not None else [])
)
m.search_securities = (
    _maybe_fail("search_securities")
    if "search_securities" in fail_on
    else AsyncMock(return_value=securities if securities is not None else [
        {"stock_code": "600519.SH", "hit": True, "name": "贵州茅台"},
    ])
)
m.get_security_indicators = MagicMock(return_value={})  # keep MagicMock (sync, not used in async paths)
m.get_stock_summary = MagicMock(return_value={})
```

The `get_security_indicators` / `get_stock_summary` lines are deferred-minor and can stay as MagicMock (they are unused dead attrs per Task 2 review).

### A2. Resync Task 2 test to await AsyncMock

Modify `backend/tests/test_conftest_mock.py`:

```python
"""验证 mock_thsifind fixture 行为"""
import pytest


@pytest.mark.asyncio
async def test_mock_thsifind_search_trending_news_default():
    from tests.conftest import mock_thsifind
    async with mock_thsifind() as m:
        result = await m.search_trending_news(time_scope="24小时", size=5)
        assert isinstance(result, list)
        # Note: brief said `assert len(result) > 0` but the global default is `[]`.
        # The controller-approved Task 2 review dropped this assertion (DONE_WITH_CONCERNS resolution).
        # Don't re-add it.


@pytest.mark.asyncio
async def test_mock_thsifind_search_securities_default():
    from tests.conftest import mock_thsifind
    async with mock_thsifind() as m:
        result = await m.search_securities(market="A股", query="扣非ROE>0")
        assert isinstance(result, list)
```

Run:
```bash
cd backend && python -m pytest tests/test_conftest_mock.py -v
```
Expected: 2 passed.

### A3. Remove adapter from Task 3 wrapper

Modify `backend/app/data/ifind_events.py`:

1. Remove `import inspect` (line 6).
2. Replace lines 47-55:
   ```python
   try:
       result = _search_trending_news(time_scope=time_scope, size=size)
       if inspect.iscoroutine(result):
           result = await result
       raw = result
   except Exception as e:
       raise IfindUnavailable(f"search_trending_news 失败: {e}") from e
   ```
   With:
   ```python
   try:
       raw = await _search_trending_news(time_scope=time_scope, size=size)
   except Exception as e:
       raise IfindUnavailable(f"search_trending_news 失败: {e}") from e
   ```
3. **Keep the rest of the file verbatim** — public API (`IfindUnavailable`, `fetch_trending_events`), helper `_search_trending_news` with `return await _mcode_call(...)`, normalization, `__all__`.

Run:
```bash
cd backend && python -m pytest tests/test_ifind_events.py -v
```
Expected: 3 passed.

### A4. Run full test suite (sanity)

```bash
cd backend && python -m pytest tests/test_conftest_mock.py tests/test_ifind_events.py -v
```
Expected: 5 passed (2 + 3), output pristine.

### A5. Amend commits

Two acceptable strategies:

**Strategy 1 — `git reset --soft HEAD~2` + recreate**:
```bash
git reset --soft HEAD~2
git status  # confirm only the touched files are staged
git commit -m "test(conftest): add mock_thsifind fixture for ifind mocking (AsyncMock retrofit)"
git add backend/app/data/ifind_events.py
git commit -m "feat(ifind-events): 包装 search_trending_news, 归一为 {event_keywords, stock_codes}"
```

**Strategy 2 — `git commit --fixup` + `git rebase --autosquash`**:
```bash
git add backend/tests/conftest.py backend/tests/test_conftest_mock.py
git commit --fixup=67f42aa
git add backend/app/data/ifind_events.py
git commit --fixup=367b756
GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash HEAD~4
```

Pick Strategy 1 (simpler, no interactive editor needed in PowerShell).

**Important constraints:**
- After amend, `git log --oneline HEAD~3..HEAD` should show: ADR-0008 → test(conftest) → feat(ifind-events), exactly 3 commits.
- Final HEAD must be `main` branch.
- Diff stat between HEAD~3 (ADR-0008) and HEAD should match the spec: ADR + conftest fixture + test + ifind_events + test_ifind_events.

### A6. Report

Write to `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/retrofit-task-2-and-3-report.md`:
- Strategy chosen and why
- New HEAD SHA + subject
- Final `git log --oneline -3` output
- Final `git diff --stat HEAD~3..HEAD` output
- All test commands + outputs (RED pre-amend → GREEN post-amend, 5 tests passing)
- Confirmation that 22 modified files + 1 untracked migration remain untouched
- Any concerns

## Acceptance Criteria

- `backend/tests/conftest.py` uses `AsyncMock` for the 4 `m.search_*` slots
- `backend/tests/test_conftest_mock.py` calls `await m.search_*` (async test)
- `backend/app/data/ifind_events.py` does NOT import `inspect`, does NOT have the `if inspect.iscoroutine(result):` adapter
- 5/5 tests pass (2 from conftest_mock + 3 from ifind_events)
- Final git history: 3 commits on main (ADR-0008 → test conftest → feat ifind-events)
- All 22 modified files + 1 untracked migration remain unchanged
- Each amended file has trailing newline

## Ambiguity Resolution

- Use `git reset --soft` strategy (simpler than fixup+autosquash in PowerShell)
- `m.get_security_indicators` / `m.get_stock_summary` stay as `MagicMock` (they are unused dead attrs; retrofitting them is out of scope)
- The dropped `assert len(result) > 0` from Task 2 review stays dropped (controller-approved)
- Don't add any new files or delete any files; only modify the 3 already-existing files (conftest.py, test_conftest_mock.py, ifind_events.py)

## Report File

`D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/retrofit-task-2-and-3-report.md`