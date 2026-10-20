# Task 14 Brief: 改动 C-2 — reflection_context_cache_repo + 迁移

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-13 commits: `74d6448` → `84cba33` → `c8f9a0d` → `3be76ad` → `e493ee2` → `99a037a` → `7888122` → `dc24c10` → `e128eb7` → `69e9f6e` → `ccc87ca` → `bc37119`
- 改动 A + B 完成（Tasks 1-12）
- Task 13 完成 ifind_news wrapper
- 本任务开始改动 C 数据层第二步——reflection_context_cache_repo + 迁移

## Global Constraints

- 工作分支: `main`
- pytest 用 `.venv\Scripts\python.exe -m pytest`
- alembic 用 `.venv\Scripts\python.exe -m alembic`
- **本地 22 个未提交改动 + 1 个 untracked Alembic migration** —— 不动这些
- ⚠️ **`backend/app/models/orm.py` 是 22 modified 文件之一** —— **append-only**，在文件末尾追加一个新 class `ReflectionContextCache`
- ⚠️ **Task 4 曾吃掉用户的 orm.py 改动**（KlineCache 删除 + 注释改动被打包进 Task 4 commit）。**这次** implementer **只 append 新 class**，不动其他内容
- 测试运行命令：`cd backend && .venv\Scripts\python.exe -m pytest tests/test_reflection_context_cache_repo.py -v`
- alembic 命令：`cd backend && .venv\Scripts\python.exe -m alembic revision --autogenerate -m "..."`

## Interfaces from Earlier Tasks

- Consumes: 
  - `from app.db import async_session`（已存在，Task 4 同款用法）
  - `from app.models.orm import ReflectionContextCache`（本任务新增 class）
- Produces:
  - `from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo`
  - `async get_today(fetch_date: date) -> Optional[ReflectionContextCache]`
  - `async upsert(fetch_date, context_json, fetched_at, ifind_calls) -> ReflectionContextCache`
  - SQLite ON CONFLICT upsert（`from sqlalchemy.dialects.sqlite import insert as sqlite_insert`）

## Task Description

### Files
- Modify: `backend/app/models/orm.py`（**append-only** —— 在文件末尾追加新 class `ReflectionContextCache`）
- Create: `backend/migrations/versions/<ts>_add_reflection_context_cache.py`
- Create: `backend/app/repositories/reflection_context_cache_repo.py`
- Create: `backend/tests/test_reflection_context_cache_repo.py`

### Steps

#### Step 1: 写失败测试

新建 `backend/tests/test_reflection_context_cache_repo.py`：

```python
"""reflection_context_cache 仓储测试 (改动 C)"""
import pytest
from datetime import date


@pytest.mark.asyncio
async def test_upsert_and_get_today():
    from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo

    today = date.today()
    row = await reflection_context_cache_repo.upsert(
        fetch_date=today,
        context_json='{"announcements_count": 1, "news_count": 2, "top_news_title": "test"}',
        fetched_at="2026-09-22T22:00:00+08:00",
        ifind_calls=2,
    )
    assert row.id is not None

    got = await reflection_context_cache_repo.get_today(today)
    assert got is not None
    assert got.fetch_date == today
    assert got.ifind_calls == 2


@pytest.mark.asyncio
async def test_get_today_missing_returns_none():
    from app.repositories.reflection_context_cache_repo import reflection_context_cache_repo
    from datetime import date, timedelta

    far_past = date.today() - timedelta(days=365)
    assert await reflection_context_cache_repo.get_today(far_past) is None
```

#### Step 2: 跑测试确认失败（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_reflection_context_cache_repo.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.repositories.reflection_context_cache_repo'`

#### Step 3: 改 orm.py（append-only）

编辑 `backend/app/models/orm.py`，**在文件末尾追加** 新 class：

```python
class ReflectionContextCache(Base):
    """ReflectionCard 22:00 消息面提示当日缓存 (改动 C)"""
    __tablename__ = "reflection_context_cache"

    id = column(Integer, primary_key=True)
    fetch_date = column(Date, nullable=False, unique=True, index=True)
    context_json = column(Text, nullable=False)
    fetched_at = column(DateTime, nullable=False)
    ifind_calls = column(Integer, nullable=False, default=2)
    created_at = column(DateTime, nullable=False, server_default=func.now())
    updated_at = column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
```

⚠️ **关键**：**只追加新 class**（约 12 行），**不动其他内容**。`Base` / `Date` / `DateTime` / `Integer` / `Text` / `func` / `column` 等 import 已在文件顶部存在（基于 Task 4 经验），**不**改 import 行。

#### Step 4: 写 Alembic 迁移

```bash
cd backend && .venv\Scripts\python.exe -m alembic revision --autogenerate -m "add reflection_context_cache table"
```

打开生成的迁移文件，**手动核对** upgrade()含 `op.create_table("reflection_context_cache", ...)`。

如 autogenerate 未识别（很可能，因为 SQLite 限制），**手动补完整** upgrade + downgrade：

```python
def upgrade() -> None:
    op.create_table(
        "reflection_context_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fetch_date", sa.Date, nullable=False),
        sa.Column("context_json", sa.Text, nullable=False),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.Column("ifind_calls", sa.integer, nullable=False, server_default="2"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_reflection_context_cache_fetch_date", "reflection_context_cache", ["fetch_date"]
    )
    op.create_index(
        "idx_reflection_context_cache_fetch_date",
        "reflection_context_cache",
        ["fetch_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_reflection_context_cache_fetch_date", table_name="reflection_context_cache")
    op.drop_table("reflection_context_cache")
```

**注意**：`down_revision` 必须是当前最新已 commit 的 migration revision（用户未提交的 `k3f4g5h6i7j8_drop_kline_cache.py` 不要 chain off）—— 让 alembic 自动选。**如果 alembic 检测到多个 head**，implementer 应该选 `e00ecf258b00`（Task 10 的最新 commit）作为 down_revision。

#### Step 5: 实现 repo

新建 `backend/app/repositories/reflection_context_cache_repo.py`：

```python
"""reflection_context_cache 仓储 (改动 C)"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import async_session
from app.models.orm import ReflectionContextCache


class ReflectionContextCacheRepo:
    @staticmethod
    async def get_today(fetch_date: date) -> Optional[ReflectionContextCache]:
        async with async_session() as session:
            stmt = select(ReflectionContextCache).where(ReflectionContextCache.fetch_date == fetch_date)
            return (await session.execute(stmt)).scalars().first()

    @staticmethod
    async def upsert(
        fetch_date: date,
        context_json: str,
        fetched_at: str,
        ifind_calls: int,
    ) -> ReflectionContextCache:
        async with async_session() as session:
            stmt = sqlite_insert(ReflectionContextCache).values(
                fetch_date=fetch_date,
                context_json=context_json,
                fetched_at=datetime.fromisoformat(fetched_at),
                ifind_calls=ifind_calls,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[ReflectionContextCache.fetch_date],
                set_={
                    "context_json": stmt.excluded.context_json,
                    "fetched_at": stmt.excluded.fetched_at,
                    "ifind_calls": stmt.excluded.ifind_calls,
                    "updated_at": datetime.now(),
                },
            )
            await session.execute(stmt)
            await session.commit()
            row = (await session.execute(
                select(ReflectionContextCache).where(ReflectionContextCache.fetch_date == fetch_date)
            )).scalars().first()
            await session.refresh(row)
            return row


reflection_context_cache_repo = ReflectionContextCacheRepo()


__all__ = ["reflection_context_cache_repo", "ReflectionContextCacheRepo"]
```

#### Step 6: 跑迁移 + 跑测试（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m alembic upgrade head
cd backend && .venv\Scripts\python.exe -m pytest tests/test_reflection_context_cache_repo.py -v
```

Expected: 2 passed

#### Step 7: Commit

```bash
git add backend/app/models/orm.py backend/app/repositories/reflection_context_cache_repo.py backend/migrations/versions/
git commit -m "feat(reflection-context-cache): 新增 reflection_context_cache 表 + 仓储 (改动 C)"
```

⚠️ **不要** git add `backend/migrations/versions/k3f4g5h6i7j8_drop_kline_cache.py` —— 用户未提交文件。

## Acceptance Criteria

- `backend/app/models/orm.py` **只在文件末尾** append 新 class `ReflectionContextCache`（约 12 行 additive）
- Alembic migration 含 upgrade + downgrade + down_revision chain 到 `e00ecf258b00`（Task 10 最新 commit）
- `ReflectionContextCacheRepo` 含 `get_today` + `upsert` 方法，**单例 `reflection_context_cache_repo`** 模块级导出
- `upsert` 用 SQLite `on_conflict_do_update` (基于 `fetch_date` unique index)
- 2/2 tests passing via `.venv\Scripts\python.exe`
- 1 commit on main，**仅含** orm.py additive diff + 新 repo 文件 + 新 migration 文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰（**特别是** `k3f4g5h6i7j8_drop_kline_cache.py` 不进 git add）
- orm.py **除追加新 class 外** 其他内容字节相同

## Ambiguity Resolution

- **orm.py 改 append-only**：用 `git diff HEAD~1..HEAD -- backend/app/models/orm.py` 验证只有 +N 行 additive，无删除/修改现有行
- **`Date` / `DateTime` / `Integer` / `Text` / `func` / `Base` / `column` import 已在 orm.py 顶部**（Task 4 经验 + 文件 review）—— **不**改 import 行
- **`down_revision`** 必须是 `e00ecf258b00`（Task 10 latest commit），让 alembic 自动选（如果 alembic 列出多个 head，implementer 选 e00ecf258b00）
- **alembic autogenerate 经常因 SQLite 限制不能识别**——必须手动核对迁移文件，按 Step 4 模板补完整
- **新增 migration 文件可能因 alembic 生成多个候选**—— implementer 应该选**最新生成**的那个 commit
- **mock 单例 + 静态方法** pattern：参考 `event_factor_cache_repo.py`（Task 4 同款）
- **`session.refresh(row)` 在 commit 后调用** —— 必要，否则返回的 ORM 对象可能 stale

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-14-report.md`

报告应包含：
- 实现了什么
- alembic migration revision + filename + down_revision
- RED + GREEN 命令 + 输出（用 `.venv\Scripts\python.exe`）
- **关键**：paste `git diff HEAD~1..HEAD -- backend/app/models/orm.py` 头部（确认 additive）+ 尾部（确认 ReflectionContextCache class）
- 文件变更列表
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concern