# Task 10 Report: 改动 B-2 — ScreenerPick orm 扩列 + 迁移

## 实现内容

- `ScreenerPick` ORM 类新增 1 列 `fundamental_filter_status` (`String`, nullable=True)
- Alembic 自动生成迁移 `e00ecf258b00_add_screener_picks_fundamental_filter_.py`
- 新增 1 测试用例验证 ORM 模型含有该列

## Alembic Migration

- **Filename**: `backend/migrations/versions/e00ecf258b00_add_screener_picks_fundamental_filter_.py`
- **Revision**: `e00ecf258b00`
- **down_revision**: `92cf5f8e1dc8` (当前已 commit 的最新 head, **未** chain off 未跟踪的 `k3f4g5h6i7j8_drop_kline_cache.py`)
- **upgrade**: `with op.batch_alter_table('screener_picks', schema=None) as batch_op: batch_op.add_column(sa.Column('fundamental_filter_status', sa.String(), nullable=True))`
- **downgrade**: `with op.batch_alter_table('screener_picks', schema=None) as batch_op: batch_op.drop_column('fundamental_filter_status')`
- ⚠️ autogenerate 这次**成功**识别了新列(可能是 `Mapped[str | None] = mapped_column(...)` 风格对 SQLite 的兼容更好;最终走 `batch_alter_table` 包装,符合 SQLite ALTER TABLE 约束)

## TDD 证据

### RED 阶段 (Step 2)

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_screener_pick_fundamental_status.py -v
```

```
collected 1 item

tests\test_screener_pick_fundamental_status.py::test_screener_pick_has_fundamental_filter_status_column FAILED [100%]

================================== FAILURES ===================================
___________ test_screener_pick_has_fundamental_filter_status_column ___________

    def test_screener_pick_has_fundamental_filter_status_column():
        """验证 ORM 模型有 fundamental_filter_status 列"""
        cols = {c.name for c in ScreenerPick.__table__.columns}
>       assert "fundamental_filter_status" in cols
E       AssertionError: assert 'fundamental_filter_status' in {'change_pct', 'consecutive_up_days', 'id', 'main_net_inflow_yi', 'rank', 'reason', ...}

tests\test_screener_pick_fundamental_status.py:10: AssertionError
=========================== short test summary info ============================
FAILED tests/test_screener_pick_fundamental_status.py::test_screener_pick_has_fundamental_filter_status_column
============================== 1 failed in 1.02s ==============================
```

### GREEN 阶段 (Step 5)

```bash
cd backend && .venv\Scripts\python.exe -m alembic upgrade head
```

```
INFO  [alembic.runtime.migration] Context impl SQLiteImpl.
INFO  [alembic.runtime.migration] Will assume non-transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 92cf5f8e1dc8 -> e00ecf258b00, add screener_picks fundamental_filter_status
```

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_screener_pick_fundamental_status.py -v
```

```
tests/test_screener_pick_fundamental_status.py::test_screener_pick_has_fundamental_filter_status_column PASSED [100%]

============================== 1 passed in 0.87s ==============================
```

## ⚠️ 关键验证: git diff HEAD~1..HEAD -- backend/app/models/orm.py

```diff
diff --git a/backend/app/models/orm.py b/backend/app/models/orm.py
index 6b93d40..53e8739 100644
--- a/backend/app/models/orm.py
+++ b/backend/app/models/orm.py
@@ -6,6 +6,7 @@ from datetime import date, datetime
 
 from sqlalchemy import (
     Boolean,
+    Column,
     Date,
     DateTime,
     Float,
@@ -494,6 +495,7 @@ class ScreenerPick(Base):
     triggered_rules: Mapped[str] = mapped_column(Text, default="[]")
     # v2.6.1:本地规则拼接的入选理由(1-2 句中文)— 跑批时生成,NULL 表示旧 run 未补算
     reason: Mapped[str | None] = mapped_column(Text, nullable=True)
+    fundamental_filter_status = Column(String, nullable=True)  # 'passed' / 'kicked' / NULL
 
     __table_args__ = (
         Index("idx_screener_picks_run", "run_id"),
```

### 关于 diff 的说明 (与 brief 期望有偏差,需透明记录)

**Brief 原期望**: 仅 1 行添加,不动 import。
**实际 diff**: 2 行添加,1 行是 `Column,` import (alembic/env.py import `app.models.orm` 触发 `NameError: name 'Column' is not defined` 后发现)。

**原因**: brief 的 `String import 已存在` 实现 row 是基于 Task 4 implementer 的经验判断(那时 `Column` 被假设已 import),但实际上 `orm.py` 全面使用新风格 `Mapped[T] = mapped_column(...)`,**没有** 直接 import `Column`。所以必须把 `Column` 加到 `from sqlalchemy import (...)` 块才能让 `Column(String, nullable=True)` 这行编译通过。

**影响范围**:
- 仅在 import 块里**加 1 行** `Column,`,没有删除/修改任何其他 import。
- 该 import 是**纯 additive**,不影响任何已有 ORM 类(全部继续用 `mapped_column` 新风格)。
- 没有触碰 brief 警告的 KlineCache 删除/注释改动(那些早被 Task 4 commit 吃掉,本任务**未触及**任何 22 modified 文件的其他改动)。
- 任何下游代码可以继续用 `Mapped[T] = mapped_column(...)`,旧风格 `Column(...)` 只用于新增的 `fundamental_filter_status` 一处。

## 文件变更列表

| 文件 | 类型 | 行数 |
|---|---|---|
| `backend/app/models/orm.py` | modified (additive) | +2 lines (1 import + 1 column) |
| `backend/migrations/versions/e00ecf258b00_add_screener_picks_fundamental_filter_.py` | new | +33 lines |
| `backend/tests/test_screener_pick_fundamental_status.py` | new | +10 lines |

总计: **3 files changed, 46 insertions(+)** (per `git show --stat HEAD`)

## Commit

- **Hash**: `e128eb7`
- **Subject**: `feat(screener-picks): 新增 fundamental_filter_status 列 (改动 B)`

## Self-Review 发现

1. ✅ 仅 22 modified 文件中的 `backend/app/models/orm.py` 被修改,其他 21 个 modified 文件 + 1 deleted 文件 + 1 deleted frontend cache 未触碰。
2. ✅ 未跟踪的 `backend/migrations/versions/k3f4g5h6i7j8_drop_kline_cache.py` 未触碰,未跟踪的 `.superpowers/` 未触碰。
3. ✅ 新迁移 down_revision 选为 `92cf5f8e1dc8` (committed head),**未** chain off 未跟踪的 `k3f4g5h6i7j8`,符合 brief 的 `让 alembic 自动选` 指示。
4. ✅ alembic upgrade head 成功,测试 1/1 通过。
5. ⚠️ 透明披露: 实际 diff 比 brief 期望多 1 行 `Column,` import(必要 — brief 写代码前没确认 `Column` 已在 import 块)。这是 additive only,不动任何已有 import。

## Issues / Concerns

- **import 偏差**: brief 的"`String` import 已存在,不需要改 import"是基于错误假设 — 实际 `Column` 不在 import 块。我选择 add `Column` 到 import(1 行 additive)而非用 `sqlalchemy.Column`(后者需要 import sqlalchemy 整个 module,变更更大)。
- **alembic 状态兼容性**: Task 4 commit `3be76ad` 把 `92cf5f8e1dc8` 的 down_revision 设为 `k3f4g5h6i7j8`(未跟踪文件),导致 DB 实际 head 是 committed 92cf5f8e1dc8,但 alembic 版本链跨过了未跟踪的 k3f4g5h6i7j8。新迁移正确选 down_revision = `92cf5f8e1dc8`,避免了双重 chain off 同一未跟踪文件的问题。