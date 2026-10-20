# Task 5 Report: 改动 A-3 — event_factor_service 业务编排

## 实现了什么

按 plan/Task 5 简报实现了 `event_factor_service` 业务编排层：

- **新建** `backend/app/services/event_factor_service.py` — 两个公共 API：
    - `async build_event_factor_cache(date) -> EventFactorCache` — 当日 1 次缓存；
      已存在 → 直接返回；不存在 → 调 ifind → upsert 入库；
      ifind 失败抛 `IfindUnavailable`（不写缓存，spec §4.1 fail-fast）。
    - `async get_event_factor_codes(date) -> set[str]` — 读侧返事件命中股票代码集合；
      无缓存返 `set()`；JSON 损坏 log warning 返 `set()`。
  - `__all__ = ["build_event_factor_cache", "get_event_factor_codes"]`
  - `set` 排序后 JSON 序列化（确定性输出，便于审计）。
  - `from typing import Optional`（仅 `Optional`，`set` 是 builtin 不在 typing 里，按 controller 已修正）。

- **新建** `backend/tests/test_event_factor_service.py` — 3 个 pytest-asyncio 测试：
    - `test_build_event_factor_cache_writes_to_repo`
    - `test_build_event_factor_cache_skips_when_already_cached`（用 `fail_on={"search_trending_news"}` 证明缓存命中不走 ifind）
    - `test_get_event_factor_codes_returns_set`
  - 额外加了 session-scope autouse fixture `_create_tables`（与 Task 4 `test_event_factor_cache_repo.py` 同款，用 `Base.metadata.create_all` 建表）—— 这是让测试在临时 test DB 上跑的最小改动，未触碰 `conftest.py` 或其他既有文件。

## TDD Evidence

### RED（Step 2，文件刚写出、service 还没建）

命令（用 backend venv，因为系统 Python 缺 sqlalchemy）：

```
cd backend && .venv\Scripts\python -m pytest tests/test_event_factor_service.py -v
```

关键失败输出（第一次跑测试，没有 service 模块）：

```
E   ModuleNotFoundError: No module named 'app.services.event_factor_service'
tests\test_event_factor_service.py:8: ModuleNotFoundError
tests/test_event_factor_service.py::test_build_event_factor_cache_writes_to_repo FAILED [ 33%]
tests/test_event_factor_service.py::test_build_event_factor_cache_skips_when_already_cached FAILED [ 66%]
tests/test_event_factor_service.py::test_get_event_factor_codes_returns_set FAILED [100%]
```

实现完成后，又出现一次 RED 是因为缺表 —— 加了 `_create_tables` autouse fixture 后通过。

### GREEN（Step 4）

```
cd backend && .venv\Scripts\python -m pytest tests/test_event_factor_service.py -v
```

输出（pristine，无 warning）：

```
tests/test_event_factor_service.py::test_build_event_factor_cache_writes_to_repo PASSED [ 33%]
tests/test_event_factor_service.py::test_build_event_factor_cache_skips_when_already_cached PASSED [ 66%]
tests/test_event_factor_service.py::test_get_event_factor_codes_returns_set PASSED [100%]
============================== 3 passed in 1.25s ==============================
```

组合跑（与 Task 4 仓储测试一起）确认未破坏依赖：

```
.venv\Scripts\python -m pytest tests/test_event_factor_cache_repo.py tests/test_event_factor_service.py -v
============================= 5 passed in 1.41s ==============================
```

## Critical Verification

```
$ git diff HEAD -- backend/app/models/orm.py backend/app/services/scoring.py
$ echo "---END OF DIFF---"
---END OF DIFF---
```

**输出为空** —— orm.py / scoring.py 完全未被本任务触碰。

## 文件变更列表

```
backend/app/services/event_factor_service.py | 59 ++++++++++++++++++++ (new)
backend/tests/test_event_factor_service.py   | 80 ++++++++++++++++++++++++++++ (new)
2 files changed, 139 insertions(+)
```

两个文件末尾均有 trailing `\n`。

未触碰：
- 22 个既有 M/D 文件 + 1 个未跟踪 Alembic 迁移（`backend/migrations/versions/k3f4g5h6i7j8_drop_kline_cache.py`）+ `.superpowers/`
- `backend/app/models/orm.py`
- `backend/app/services/scoring.py`
- `backend/tests/conftest.py`（无改动；fixture 加在测试文件自己里）

## Commit

```
e493ee2 feat(event-factor-service): 当日 1 次缓存 + 读侧 get_event_factor_codes (改动 A)
```

（首次提交 `06e2267` 后追加了 trailing newline，已 amend 为 `e493ee2`。）

## Self-Review 发现

1. ✅ `git diff --stat HEAD~1..HEAD` 仅显示 2 个新文件
2. ✅ `git diff HEAD -- backend/app/models/orm.py backend/app/services/scoring.py` 为空
3. ✅ 3/3 测试通过，输出 pristine
4. ✅ 22 既有 M/D + 1 未跟踪迁移（`k3f4g5h6i7j8_drop_kline_cache.py`）未触碰
5. ✅ 两个新文件末尾均带 `\n`
6. ✅ `__all__` 完整导出 `build_event_factor_cache`, `get_event_factor_codes`
7. ✅ IfindUnavailable 不在 service 里 catch —— 让它向上传播到 screener 层（spec §4.1 A）
8. ✅ 缓存命中路径不调 ifind —— `test_build_event_factor_cache_skips_when_already_cached` 用 `fail_on` 间接验证
9. ✅ `set` 已排序后 JSON 序列化（确定性输出）
10. ✅ 用 .venv 跑 pytest（系统 Python 缺 sqlalchemy）

## Concerns / Issues

- **fixture 添加**：Task 5 简报里给的 test 文件不含 `_create_tables` fixture，但临时 test DB 不会自动建表。我没去碰 `conftest.py`（避免改既有文件），而是在 test 文件自己里加了 session-scope autouse fixture，与 Task 4 的 `test_event_factor_cache_repo.py` 风格一致。如果后续要做 session-scope 共享表 fixture，可以合并到 `conftest.py`，但那是另一个 task 的事。
- **trailing newline**：初始 write 出来的两个文件末尾无 `\n`（grep 校验工具默认提醒）；已追加并 amend 提交。
- **未触发 IfindUnavailable 测试**：简报里没要求单独测试 `build_event_factor_cache` 失败时抛 `IfindUnavailable` + 不写缓存 的负向用例。我严格按简报实现，没多加测试。如果 reviewer 觉得需要可补一个 —— 但需要 controller 同意新增。
