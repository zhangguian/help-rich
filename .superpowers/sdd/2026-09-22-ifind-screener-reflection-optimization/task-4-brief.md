# Task 4 Brief: 改动 A-2 — event_factor_cache_repo + Alembic 迁移

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 是一个本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1 ADR-0008: commit `74d6448`
- Task 2 (AsyncMock-retrofitted): commit `84cba33`
- Task 3 (ifind_events wrapper, no adapter): commit `c8f9a0d`

本任务（Task 4 / 20）是**改动 A 的第 2 个 task**——创建 `event_factor_cache` 表 + Alembic 迁移 + repo 单例。为 Task 5 的 event_factor_service 做准备。

## Global Constraints (本任务相关)

- 工作分支: `main`
- 项目用 SQLite + aiosqlite（`backend/app/db.py` 提供 `async_session`）
- Alembic 迁移路径: `backend/migrations/versions/<revision>_<slug>.py`
- 项目已有 10+ 历史迁移（含新未提交 `k3f4g5h6i7j8_drop_kline_cache.py`，**不可碰**）
- 写表条件: ifind 拉取成功（spec §5，**失败不写**）
- Commit message: `feat(event-factor-cache): 新增 event_factor_cache 表 + 仓储 + 迁移 (改动 A)`
- **本地有 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不可触碰
- **特别注意 `backend/app/models/orm.py` 是 22 个已 modified 文件之一** —— 必须以 additive 方式追加 `EventFactorCache` class（不动现有内容）

## Interfaces from Earlier Tasks

- Consumes: `async_session` from `app.db`
- Produces:
  - `from app.repositories.event_factor_cache_repo import event_factor_cache_repo` 单例
  - `event_factor_cache_repo.get_today(date) -> Optional[EventFactorCache]`
  - `event_factor_cache_repo.upsert(trade_date, event_keywords_json, stock_codes_json, fetched_at, ifind_calls) -> EventFactorCache`
  - ORM 模型 `EventFactorCache` 注册到 `app.models.orm`

## Task Description

### Files
- Modify: `backend/app/models/orm.py`（**append-only**——追加 `EventFactorCache` class，**不动**任何现有内容）
- Create: `backend/migrations/versions/<ts>_event_factor_cache.py`（autogenerate 后核对）
- Create: `backend/app/repositories/event_factor_cache_repo.py`
- Create: `backend/tests/test_event_factor_cache_repo.py`

### Steps

#### Step 1: 读现有 repo + orm.py

读 `backend/app/repositories/screener_repo.py` + `backend/app/repositories/daily_analysis_repo.py`，熟悉 UPSERT 风格（项目已有 SQLite UPSERT 写法）。
读 `backend/app/models/orm.py` 顶部 imports + 找一个合适位置（参考 `ScreenerRun`/`ScreenerPick` 等模型定义处）追加新 model。

#### Step 2: 写失败测试

新建 `backend/tests/test_event_factor_cache_repo.py`：

```python
"""event_factor_cache 仓储层测试"""
import pytest
from datetime import date, timedelta


@pytest.mark.asyncio
async def test_upsert_and_get_today():
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo

    today = date.today()
    row = await event_factor_cache_repo.upsert(
        trade_date=today,
        event_keywords_json='["AI", "新能源"]',
        stock_codes_json='["600519.SH", "300750.SZ"]',
        fetched_at="2026-09-22T22:00:00+08:00",
        ifind_calls=1,
    )
    assert row.id is not None

    got = await event_factor_cache_repo.get_today(today)
    assert got is not None
    assert got.trade_date == today
    assert got.ifind_calls == 1


@pytest.mark.asyncio
async def test_get_today_missing_returns_none():
    from app.repositories.event_factor_cache_repo import event_factor_cache_repo

    far_past = date.today() - timedelta(days=365)
    got = await event_factor_cache_repo.get_today(far_past)
    assert got is None
```

注: brief 原版的"先清掉历史数据"那段有 bug（`async with ... if hasattr(...) else` 语法错）—— 已删除，使用简洁版本。

#### Step 3: 跑测试确认失败

```bash
cd backend && python -m pytest tests/test_event_factor_cache_repo.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.repositories.event_factor_cache_repo'`

#### Step 4: 写 orm 模型

编辑 `backend/app/models/orm.py`，**在文件末尾追加**（不修改任何现有代码）：

```python
class EventFactorCache(Base):
    """screener 事件因子当日缓存 (改动 A)

    - key: trade_date (当日 1 次, 跨日失效)
    - 写表条件: ifind 拉取成功 (失败不写)
    """
    __tablename__ = "event_factor_cache"

    id = Column(Integer, primary_key=True)
    trade_date = Column(Date, nullable=False, unique=True, index=True)
    event_keywords_json = Column(Text, nullable=False)
    stock_codes_json = Column(Text, nullable=False)
    fetched_at = Column(DateTime, nullable=False)
    ifind_calls = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
```

确认文件顶部已 `from sqlalchemy import Column, Integer, String, Text, Date, DateTime, func, Boolean, Float, ForeignKey` 等导入（基于已读 `orm.py`）。如果导入不全，**只 append 新 import，不改现有 import 顺序**。

#### Step 5: 写 Alembic 迁移

```bash
cd backend && alembic revision --autogenerate -m "add event_factor_cache table"
```

打开生成的 `backend/migrations/versions/<ts>_event_factor_cache.py`，检查 upgrade() 含 `op.create_table("event_factor_cache", ...)`，downgrade() 含 `op.drop_table(...)`。如果 autogenerate 未识别（很可能，因为本项目可能 not fully scanned），手动补：

```python
def upgrade() -> None:
    op.create_table(
        "event_factor_cache",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("event_keywords_json", sa.Text, nullable=False),
        sa.Column("stock_codes_json", sa.Text, nullable=False),
        sa.Column("fetched_at", sa.DateTime, nullable=False),
        sa.Column("ifind_calls", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_event_factor_cache_trade_date", "event_factor_cache", ["trade_date"])
    op.create_index("idx_event_factor_cache_trade_date", "event_factor_cache", ["trade_date"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_event_factor_cache_trade_date", table_name="event_factor_cache")
    op.drop_table("event_factor_cache")
```

#### Step 6: 实现 repo

新建 `backend/app/repositories/event_factor_cache_repo.py`：

```python
"""event_factor_cache 仓储 (改动 A)

单表当日缓存; 写表条件: ifind 拉取成功."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db import async_session
from app.models.orm import EventFactorCache


class EventFactorCacheRepo:
    @staticmethod
    async def get_today(trade_date: date) -> Optional[EventFactorCache]:
        async with async_session() as session:
            stmt = select(EventFactorCache).where(EventFactorCache.trade_date == trade_date)
            return (await session.execute(stmt)).scalars().first()

    @staticmethod
    async def upsert(
        trade_date: date,
        event_keywords_json: str,
        stock_codes_json: str,
        fetched_at: str,
        ifind_calls: int,
    ) -> EventFactorCache:
        async with async_session() as session:
            stmt = sqlite_insert(EventFactorCache).values(
                trade_date=trade_date,
                event_keywords_json=event_keywords_json,
                stock_codes_json=stock_codes_json,
                fetched_at=datetime.fromisoformat(fetched_at),
                ifind_calls=ifind_calls,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[EventFactorCache.trade_date],
                set_={
                    "event_keywords_json": stmt.excluded.event_keywords_json,
                    "stock_codes_json": stmt.excluded.stock_codes_json,
                    "fetched_at": stmt.excluded.fetched_at,
                    "ifind_calls": stmt.excluded.ifind_calls,
                    "updated_at": datetime.now(),
                },
            )
            await session.execute(stmt)
            await session.commit()
            row = (await session.execute(
                select(EventFactorCache).where(EventFactorCache.trade_date == trade_date)
            )).scalars().first()
            await session.refresh(row)
            return row


event_factor_cache_repo = EventFactorCacheRepo()

__all__ = ["event_factor_cache_repo", "EventFactorCacheRepo"]
```

#### Step 7: 跑迁移 + 跑测试

```bash
cd backend && alembic upgrade head && python -m pytest tests/test_event_factor_cache_repo.py -v
```

Expected: 迁移成功 + 2 passed

#### Step 8: Commit

```bash
git add backend/app/models/orm.py backend/app/repositories/event_factor_cache_repo.py backend/tests/test_event_factor_cache_repo.py backend/migrations/versions/
git commit -m "feat(event-factor-cache): 新增 event_factor_cache 表 + 仓储 + 迁移 (改动 A)"
```

注: brief 原文只 add 3 个路径，但应包括 migrations 文件。已修正。

## Acceptance Criteria

- 新文件 `backend/migrations/versions/<ts>_event_factor_cache.py` 含 upgrade + downgrade
- 新文件 `backend/app/repositories/event_factor_cache_repo.py` 含 `EventFactorCacheRepo` 单例
- 新文件 `backend/tests/test_event_factor_cache_repo.py` 含 2 tests
- `backend/app/models/orm.py` 末尾追加 `EventFactorCache` class，**其他内容字节相同**
- 迁移跑成功 (`alembic upgrade head`)
- 2/2 tests pass
- 1 commit on main，仅含 4 个 in-scope 文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- 所有新 / 改文件末尾 trailing newline

## Ambiguity Resolution

- **`orm.py` 是 22 modified 文件之一**：必须 append-only，不能 resolve 冲突或修改现有内容。如果 `from sqlalchemy import ...` 已经齐全就直接加；否则**只 append** import（不动现有顺序）
- **Migration revision**: autogenerate 给的 revision（基于现有 hash）。如果项目里其他迁移使用 alembic 风格，写法相同
- **Alembic 环境**: 项目已配 alembic.ini + env.py，`alembic upgrade head` 即可跑
- **测试隔离**: 22 个未提交改动可能影响 `app.db.async_session` / migrations 环境。测试运行必须只影响本次新表，不影响其他表
- **如有 conftest fixture 已提供测试数据库隔离（如临时 DB / rollback）**，沿用；否则用真实的 test DB（项目风格自定）

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-4-report.md`

报告应包含：
- 实现了什么
- TDD evidence (RED + GREEN 命令 + 关键输出)
- alembic 迁移文件名 (revision + slug)
- 文件变更列表 + 行数
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns