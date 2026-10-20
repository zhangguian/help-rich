# Task 10 Brief: 改动 B-2 — ScreenerPick orm 扩列 + 迁移

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-9 commits: `74d6448` → `84cba33` → `c8f9a0d` → `3be76ad` → `e493ee2` → `99a037a` → `7888122` → `dc24c10`
- 改动 A 完成（Tasks 1-8）
- Task 9 完成 ifind_fundamentals wrapper
- 本任务开始 screener_picks 表的 orm 扩列

## Global Constraints

- 工作分支: `main`
- pytest 用 `.venv\Scripts\python.exe -m pytest`
- alembic 用 `.venv\Scripts\python.exe -m alembic`
- **本地 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些
- ⚠️ **`backend/app/models/orm.py` 是 22 modified 文件之一** —— **append-only**，加一行新列 + 注释
- ⚠️ **Task 4 曾吃掉用户的 orm.py 改动**（KlineCache 删除 + 注释改动被打包进 Task 4 commit）。**这次** implementer **只 add 新列**，不动其他内容
- **本任务**改动 B 起步简变了（plan Task 10 Steps 3-4 vs spec）：
  - 原 Step 3: "在合适列位置追加 `fundamental_filter_status`" — **意味着** 在 `ScreenerPick` 类内 append
  - 原 Step 5: alembic upgrade + pytest（**用 venv python**）

## Interfaces from Earlier Tasks

- Consumes: 无
- Produces:
  - `ScreenerPick.fundamental_filter_status` 列，类型 `String`，nullable=True
  - Alembic migration `add screener_picks fundamental_filter_status`

## Task Description

### Files
- Modify: `backend/app/models/orm.py`（**append-only** —— 在 `ScreenerPick` class 内追加 1 行 `fundamental_filter_status = Column(...)`）
- Create: `backend/migrations/versions/<ts>_screener_picks_fundamental_status.py`
- Create: `backend/tests/test_screener_pick_fundamental_status.py`

### Steps

#### Step 1: 写失败测试

新建 `backend/tests/test_screener_pick_fundamental_status.py`：

```python
"""ScreenerPick.fundamental_filter_status 列测试 (改动 B)"""
import pytest
from app.models.orm import ScreenerPick
from sqlalchemy import inspect


def test_screener_pick_has_fundamental_filter_status_column():
    """验证 ORM 模型有 fundamental_filter_status 列"""
    cols = {c.name for c in ScreenerPick.__table__.columns}
    assert "fundamental_filter_status" in cols
```

#### Step 2: 跑测试确认失败（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_screener_pick_fundamental_status.py -v
```

Expected: FAIL with assertion error (`fundamental_filter_status` not in cols)

#### Step 3: 改 orm.py（append-only）

编辑 `backend/app/models/orm.py`，找到 `ScreenerPick` 类定义，**在最后一个现有列后**追加 1 行：

```python
fundamental_filter_status = Column(String, nullable=True)  # 'passed' / 'kicked' / NULL
```

⚠️ **关键**：**只追加 1 行**，**不动其他内容**。`String` 类型已在文件顶部 import，不需要改 import。

#### Step 4: 写 Alembic 迁移

```bash
cd backend && .venv\Scripts\python.exe -m alembic revision --autogenerate -m "add screener_picks fundamental_filter_status"
```

打开生成的迁移文件，**手动核对** upgrade() 含 `op.add_column("screener_picks", sa.Column("fundamental_filter_status", sa.String, nullable=True))`。

如 autogenerate 未识别（很可能，因为 SQLite ALTER TABLE 有约束），**手动补完整** upgrade + downgrade：

```python
def upgrade() -> None:
    op.add_column(
        "screener_picks",
        sa.Column("fundamental_filter_status", sa.String, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("screener_picks", "fundamental_filter_status")
```

**注意 SQLite ALTER TABLE 不支持 NOT NULL 列无默认值**——确保 `nullable=True`。

#### Step 5: 跑迁移 + 跑测试（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m alembic upgrade head
cd backend && .venv\Scripts\python.exe -m pytest tests/test_screener_pick_fundamental_status.py -v
```

Expected: 1 passed

#### Step 6: Commit

```bash
git add backend/app/models/orm.py backend/migrations/versions/
git commit -m "feat(screener-picks): 新增 fundamental_filter_status 列 (改动 B)"
```

## Acceptance Criteria

- `ScreenerPick.__table__.columns` 含 `fundamental_filter_status`
- Alembic migration 含 upgrade + downgrade
- 1/1 test passing
- 1 commit on main，**仅含** orm.py additive diff + 新 migration 文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- orm.py **除追加 1 行外** 其他内容字节相同

## Ambiguity Resolution

- **`or` 列在 ScreenerPick 类内 append**（不动 class 边界）
- **alembic autogenerate 经常因 SQLite 限制不能识别**——必须手动核对迁移文件
- **migration 文件 down_revision** 必须是当前最新已 commit 的 migration revision（用户未提交的 `k3f4g5h6i7j8_drop_kline_cache.py` 不要 chain off）—— 让 alembic 自动选
- **新增 migration 文件可能因 alembic 生成多个候选**—— implementer 应该选**最新生成**的那个 commit
- **`String` import** 已存在（基于 Task 4 经验 + orm.py 已有 `String`），**不**改 import 行

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-10-report.md`

报告应包含：
- 实现了什么
- alembic migration revision + filename
- RED + GREEN 命令 + 输出（用 `.venv\Scripts\python.exe`）
- **关键**：paste `git diff HEAD~1..HEAD -- backend/app/models/orm.py` 头部（确认 additive） + 尾部（确认 ScreenerPick 内追加）
- 文件变更列表
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns