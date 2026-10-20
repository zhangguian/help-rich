# Task 9 Report: 改动 B-1 — ifind_fundamentals 包装层

## Status
**DONE** — 4/4 tests passing, 1 commit on `main` containing exactly 2 new files.

## What was implemented

- **`backend/app/data/ifind_fundamentals.py`** (new, 58 lines): wraps thsifind `search_securities` tool.
  - Public API: `is_hit_fundamental_filter(stock_code, query, market='A股') -> bool`
  - Module-level helper: `_search_securities(market, query) -> list[dict]` (mock target for `mock_thsifind` fixture)
  - Reuses `IfindUnavailable` from `app.data.ifind_events` (统一异常基类, spec §3.3)
  - Reuses existing `mock_thsifind` fixture from `tests/conftest.py` (already has `securities=` kwarg + `fail_on={"search_securities"}` support from Task 2)
  - `__all__ = ["is_hit_fundamental_filter"]`
- **`backend/tests/test_ifind_fundamentals.py`** (new, 50 lines): 4 tests covering hit / no-match / empty / failure paths.

## TDD Evidence

### RED — tests fail with ModuleNotFoundError

Command (must use venv python; system python 3.13 lacks fastapi):
```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_ifind_fundamentals.py -v
```

Key output (before implementation):
```
collected 4 items
tests/test_ifind_fundamentals.py::test_is_hit_returns_true_when_stock_in_results FAILED [ 25%]
tests/test_ifind_fundamentals.py::test_is_hit_returns_false_when_stock_not_in_results FAILED [ 50%]
tests/test_ifind_fundamentals.py::test_is_hit_empty_results_returns_false FAILED [ 75%]
tests/test_ifind_fundamentals.py::test_is_hit_failure_raises FAILED      [100%]

E       ModuleNotFoundError: No module named 'app.data.ifind_fundamentals'
```

4/4 fail with the expected `ModuleNotFoundError`.

### GREEN — implementation passes

Same command after writing `backend/app/data/ifind_fundamentals.py`:
```
collected 4 items
tests/test_ifind_fundamentals.py::test_is_hit_returns_true_when_stock_in_results PASSED [ 25%]
tests/test_ifind_fundamentals.py::test_is_hit_returns_false_when_stock_not_in_results PASSED [ 50%]
tests/test_ifind_fundamentals.py::test_is_hit_empty_results_returns_false PASSED [ 75%]
tests/test_ifind_fundamentals.py::test_is_hit_failure_raises PASSED      [100%]

============================== 4 passed in 0.09s ==============================
```

4/4 passing via `.venv\Scripts\python.exe`. Output pristine (only the standard pytest-asyncio `asyncio_default_fixture_loop_scope` deprecation warning, unrelated to this task).

## File changes

| File | Action |
|---|---|
| `backend/app/data/ifind_fundamentals.py` | created |
| `backend/tests/test_ifind_fundamentals.py` | created |

Verification via `git diff --stat HEAD~1 HEAD`:
```
 backend/app/data/ifind_fundamentals.py   | 58 ++++++++++++++++++++++++++++++++
 backend/tests/test_ifind_fundamentals.py | 50 +++++++++++++++++++++++++++
 2 files changed, 108 insertions(+)
```

Exactly the 2 new files. None of the 22 pre-existing modified files (orm.py / scoring.py / screener_service.py / etc.) nor the untracked Alembic migration `k3f4g5h6i7j8_drop_kline_cache.py` were touched.

## Commit

```
dc24c10 feat(ifind-fundamentals): 包装 search_securities, 单只票基本面筛 (改动 B)
```

## Self-review

- ✅ `__all__ = ["is_hit_fundamental_filter"]` — public API exported
- ✅ `_search_securities` is a **module-level** function (not nested/lambda), so `mock_thsifind` fixture's `patch("app.data.ifind_fundamentals._search_securities", ...)` correctly resolves the attribute
- ✅ `IfindUnavailable` imported from `app.data.ifind_events` (not redefined) — spec §3.3 统一异常基类
- ✅ Failure path: try/except wraps `_search_securities` and re-raises as `IfindUnavailable` — never silently swallowed
- ✅ Non-list response handling: raises `IfindUnavailable` instead of `TypeError`
- ✅ `stock_code` normalization: `.upper().strip()` matches both dict-side normalization (handles lowercase or whitespace from upstream)
- ✅ Mirror Task 3 (ifind_events) structure: connector import guarded with try/except for environments without `mcode-tools`
- ✅ Brief literally followed; no architectural deviations

## Issues / Concerns

None. Task completed within stated scope.