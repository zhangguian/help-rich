# Task 11 Report: 改动 B-3 — screener_service._apply_fundamental_filter

**Status:** DONE (with deviation documented)

## TDD Evidence

### RED (before implementation)
```
tests/test_apply_fundamental_filter.py::test_apply_filter_all_pass_keeps_order FAILED
tests/test_apply_fundamental_filter.py::test_apply_filter_kicked_gets_penalty_and_resorts FAILED
tests/test_apply_fundamental_filter.py::test_apply_filter_failure_raises FAILED
tests/test_apply_fundamental_filter.py::test_apply_filter_disabled_short_circuits FAILED
4 failed with ImportError: cannot import name '_apply_fundamental_filter'
```

### GREEN (after implementation)
```
tests/test_apply_fundamental_filter.py::test_apply_filter_all_pass_keeps_order PASSED
tests/test_apply_fundamental_filter.py::test_apply_filter_kicked_gets_penalty_and_resorts PASSED
tests/test_apply_fundamental_filter.py::test_apply_filter_failure_raises PASSED
tests/test_apply_fundamental_filter.py::test_apply_filter_disabled_short_circuits PASSED
tests/test_apply_fundamental_filter.py::test_run_daily_pick_calls_fundamental_filter PASSED  [bonus integration]
tests/test_apply_fundamental_filter.py::test_run_daily_pick_skips_persist_on_fundamental_filter_failure PASSED  [bonus integration]
6 passed in 0.92s
```

### Full pytest suite (`cd backend && .venv\Scripts\python.exe -m pytest`)

```
307 passed, 2 warnings, 4 errors in 6.51s
```

The 4 errors are pre-existing in `tests/test_sina_data.py::TestMarketAPI` (and 23 collection errors in other tests that import `app.main`), all caused by `RuntimeError: Form data requires "python-multipart" to be installed`. This is an environment/infrastructure issue unrelated to Task 11 — verified by inspecting the error trace: it originates from `app/api/screenshot.py`'s `multipart_not_installed_error`, not from screener_service or filter code.

Per the brief's instruction, tests were run on the runnable subset (excluding 23 multipart-dependent test files plus 4 TestMarketAPI cases that share the same root cause). All Task 11 in-scope tests pass.

## Main entry & variable found

- **Main entry:** `run_daily_pick(target_date)` in `backend/app/services/screener_service.py` (confirmed by Task 7)
- **`top_n_picks` analog in run_daily_pick:** `picks_payload: list[dict]` — built from `top: list[tuple[StockFeatures, ScoreBreakdown]]` after scoring. The brief's literal `top_n_picks` does not pre-exist; the function operates on `picks_payload` via a thin proxy class.

## Critical verification — append-only on screener_service.py

```
git diff HEAD -- backend/app/services/screener_service.py | tail -50
```

```
+class _PickProxy:
+    """picks_payload dict 的薄包装, 让 filter 能以 object-API (stock_code/score/
+    fundamental_filter_status) 操作, 通过 commit() 把改动写回原 dict.
+
+    只在 run_daily_pick 集成处使用, 不暴露给外部.
+    """
+
+    __slots__ = ("stock_code", "score", "fundamental_filter_status", "_p")
+
+    def __init__(self, payload: dict) -> None:
+        self._p = payload
+        self.stock_code: str = payload["stock_code"]
+        self.score: float = payload["score"]
+        self.fundamental_filter_status: str | None = None
+
+    def commit(self) -> None:
+        self._p["score"] = self.score
+        self._p["fundamental_filter_status"] = self.fundamental_filter_status
+
+
+async def _apply_fundamental_filter(picks: list) -> list:
+    """对 Top N 跑一次基本面兜底过滤; 任一失败直接抛 IfindUnavailable.
+
+    行为:
+    - SCREENER_FUNDAMENTAL_FILTER_ENABLED=False → 原样返
+    - is_hit_fundamental_filter 返 True → fundamental_filter_status='passed', 分不变
+    - 返 False → fundamental_filter_status='kicked', 扣 SCREENER_FUNDAMENTAL_KICKOUT_PENALTY
+    - 任一票 ifind 调用失败 → 抛 IfindUnavailable, 不写库
+
+    Args:
+        picks: 列表, 元素需有 stock_code, score, fundamental_filter_status 属性
+            (SimpleNamespace / ScreenerPick / dataclass 均可)
+
+    Returns:
+        重新排序的 picks 列表 (in-place + return)
+    """
+    from app.core.config import (
+        SCREENER_FUNDAMENTAL_FILTER_ENABLED,
+        SCREENER_FUNDAMENTAL_FILTER_QUERY,
+        SCREENER_FUNDAMENTAL_KICKOUT_PENALTY,
+    )
+    if not SCREENER_FUNDAMENTAL_FILTER_ENABLED:
+        return picks
+
+    # 并发查 Top N
+    results = await asyncio.gather(
+        *[is_hit_fundamental_filter(p.stock_code, SCREENER_FUNDAMENTAL_FILTER_QUERY) for p in picks],
+        return_exceptions=True,
+    )
+    # 任一失败 → 整体抛
+    for i, r in enumerate(results):
+        if isinstance(r, Exception):
+            if isinstance(r, IfindUnavailable):
+                raise r
+            raise IfindUnavailable(f"基本面过滤异常: {picks[i].stock_code}: {r}") from r
+
+    for pick, hit in zip(picks, results):
+        if hit:
+            pick.fundamental_filter_status = "passed"
+        else:
+            pick.fundamental_filter_status = "kicked"
+            pick.score -= SCREENER_FUNDAMENTAL_KICKOUT_PENALTY
+
+    picks.sort(key=lambda p: p.score, reverse=True)
+    return picks
```

## Files Changed (in-scope, 3 files only)

```
backend/app/core/config.py                       |   7 ++-
backend/app/services/screener_service.py         |  89 +++++++++++++++++-
backend/tests/test_apply_fundamental_filter.py   | 153 ++++++++++++++++ (new)
```

## Commit

- **Hash:** `00282ad`
- **Short subject:** `feat(screener): Top N 基本面兜底过滤, 失败 fail-fast (改动 B)`
- **Files:** 3 in-scope files (screener_service.py +89, config.py +7/-2, test_apply_fundamental_filter.py +153)
- **22-modified set:** untouched (no file in the user's uncommitted set was staged)
- **Migration file:** left untracked, untouched

```
$ git show --stat 00282ad
backend/app/core/config.py                       |   7 ++-
backend/app/services/screener_service.py         |  89 +++++++++++++++++-
backend/tests/test_apply_fundamental_filter.py   | 153 ++++++++++++++++ (new)
3 files changed, 261 insertions(+), 2 deletions(-)
```

## Deviation from brief — document for review

The brief mandated APPEND-ONLY with "1-line call" to `_apply_fundamental_filter`. In practice, two pieces made strict 1-line impossible while preserving spec §6 semantics:

1. **Failure semantics require wrapping**: spec §6 says "B 改动 failure → screener run 不展示 Top N" and the brief verbatim says "IfindUnavailable raised by _apply_fundamental_filter should be caught at run_daily_pick level → log error + skip persistence + skip display". A literal 1-line call without `try/except IfindUnavailable → return None` would propagate the exception and break `replace_picks` mocking in `tests/test_screener_with_event_factor.py`.

2. **Persistence integration**: the brief's pick-wrapper model (`.stock_code`, `.score`, `.fundamental_filter_status`) doesn't match `picks_payload`'s dict-of-features shape. Two viable approaches:
   - (A) Modify the picks_payload loop body to add `fundamental_filter_status` and use filtered score.
   - (B) Use a `_PickProxy` thin wrapper that mirrors pick-API on the dict and mutates it via `commit()`. No existing loop body needs to change.

I chose (B) to minimize touch on existing content. The deviation:
- Inside `run_daily_pick`, inserted a **13-line block** (comment + try/except + commit + sort + re-rank) between `picks_payload = [...]` and `run = await screener_repo.upsert_run(...)`.
- Added a `_PickProxy` class at end of file (no API surface change — purely internal helper).

Original `picks_payload` dict-literal construction loop body is byte-identical to pre-Task-11. The 13-line block sits after it, before persistence — no existing lines were modified.

The `screener_repo.py` `replace_picks` was NOT modified (kept original signature, `fundamental_filter_status` field exists in the dict but is ignored by replace_picks → DB column remains NULL). This matches the brief's "仅含 3 个 in-scope 文件" constraint. Persisting the filter status to the DB column is a follow-up; the filter logic itself works end-to-end at the application layer.

## Self-review / concerns

- **Concern 1 (DB persistence):** `fundamental_filter_status` is set in the in-memory `picks_payload` dict but not persisted to the `screener_picks.fundamental_filter_status` column because `screener_repo.replace_picks` doesn't pass it. A follow-up task should update `replace_picks` to pass `fundamental_filter_status=p.get("fundamental_filter_status")`. Out of scope for Task 11 per the brief's "仅含 3 个 in-scope 文件" constraint.

- **Concern 2 (run_daily_pick deviation):** The 13-line block instead of 1-line call is the minimum required to satisfy spec §6 fail-fast semantics AND keep `test_screener_with_event_factor.py` green. Adding a follow-up that refactors `run_daily_pick` into smaller composable functions could revert this to a literal 1-line call in a future iteration.

- **Concern 3 (pre-existing python-multipart issue):** 27 test files (23 collection errors + 4 TestMarketAPI runtime errors) are blocked by missing `python-multipart` package in `.venv`. This blocks the full suite from being reported as 100% green. The fix is `pip install python-multipart` in `.venv`. Out of scope for Task 11.

## References

- Spec: `ff5d275` (iFinD 驱动 screener+reflection 优化设计, §6 失败语义)
- Plan: `3d7b9a4`
- Task 9: `e128eb7` (`ifind_fundamentals` wrapper, `is_hit_fundamental_filter`)
- Task 10: `dc24c10` (`ScreenerPick.fundamental_filter_status` column added)