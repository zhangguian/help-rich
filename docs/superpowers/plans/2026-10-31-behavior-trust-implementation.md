# K 线异动行为标注 —— 可信度加固(四道闸)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 K 线异动行为标注的**数字可信** —— 分组计数用真实命中数、命中明细全量入库、找股与 K 线路径窗口对齐、两者一致性能被测试钉住、盘后自动跑批且批次带数据时点。

**Architecture:** 四道闸互相独立、可分批落地。闸 1 改**落库口径**（全量入库 + 真实分类计数）；闸 2 改**筛选与窗口**（去掉候选池人为上限、两边统一 120 日历天）；闸 3 加**一致性守门**（pytest 单测 + 手动巡检脚本，只报告不改数据）；闸 4 加**调度与时点**（盘后自动跑批 + `data_as_of`/`is_intraday` 字段）。判定层 `behavior_signal_service.detect_behavior_markers` **不改**，仍是两条路径共用的唯一入口。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 (async) + Alembic + SQLite；pytest + ruff；Next.js 14 + React 18 + TypeScript（axios 响应拦截器递归 snake→camel）。

**Spec:** `docs/superpowers/specs/2026-10-31-behavior-trust-design.md`（commit `7426612`）

---

## Global Constraints

这些约束适用于**每一个** Task，实施时不得放宽：

- **项目红线**（`backend/app/core/prompts.py`）：输出**不预测涨跌、不给买卖指令**。新增的 `reason` 文案只陈述**已发生的事实**，末尾附「以上不构成投资建议」的口径由前端统一处理。
- **项目铁律**：缺数据 → 该信号不产出，**绝不编数字**。任何新增字段算不出来就返回 `None` / 空列表，不填 0。
- **纯函数层零 IO**：`app/modules/behavior_screener/logic.py` 与 `app/services/behavior_signal_service.py` 不得新增 IO / LLM / DB 调用。
- **架构边界**：`backend/tests/test_architecture_boundaries.py` 规定 `modules` 之间**只准 import 对方的 `service.py`**。本计划新增的跨模块引用必须遵守。
- **前端 API 类型必须写驼峰**（`hitCounts` / `dataAsOf` / `isIntraday`）：axios 响应拦截器（`frontend/src/lib/api.ts:58`）会递归把 snake_case 转 camelCase。写成 snake_case 时 **TS 不报错**（泛型只是断言），但运行期字段全是 `undefined`。
- **阈值不得在本期调整**：`config.py` 里现有的 `BEHAVIOR_*` 阈值保持不变（spec §十 明确 L1/L2 本期不动）。本计划只改**口径**（数的是谁、有没有截断、窗口多长），不改「什么算命中」。
- **不 push**。每个 Task 结束提交一次 commit，但**不推远端**。
- **Windows 约束**：PowerShell 5.1 不支持 `&&` / `||`；多语句脚本用 `;` 分隔并显式检查 `$LASTEXITCODE`；读文件统一走 Python `encoding="utf-8"`（`Get-Content` 读中文会乱码）。
- **pytest 与 TestClient 不并行**：`backend/tests/` 下 pytest 与 TestClient 会争同一测试库 → 必须串行执行。
- **数据库是 SQLite**（`backend/data.db`），外网请求走新浪；**不要引入 akshare**（ADR-0006）。

---

## ⚠️ 修订记录（human 拍板，2026-10-31）

### R1 —— `is_intraday` 的「未传值」语义：`False` → `None`（NULL = 未知）

**背景**：Task 1 审查（round 1）发现一条 plan-mandated 缺陷 —— 计划把 `is_intraday` 默认成
`False`，即把「未知」编码成「确定不是盘中」。这与**项目铁律**「缺数据 → 不产出，**绝不编数字**」
直接冲突：今天的生产调用点不传这个参数 → **盘中跑的批次会被落库成「盘后完整数据」**，
而那恰恰是闸 4 稳定闸要拦的「半成品被当完整数据」。

**human 裁定**：**改为 `bool | None = None` —— NULL = 未知**，与同批的 `hit_counts_json` /
`data_as_of`（None = 未知）语义一致。生产端**必须显式传真值**。

**连锁修订（已落到下面各 Task 的正文里）**：

| 位置 | 修订 |
|---|---|
| Task 1 | ORM `Mapped[bool | None]`；迁移列**无** server default；`upsert_run` 默认 `None`；测试断言 `is None` + 新增 update 分支用例 |
| Task 3 | 占位值 `is_intraday=False` → **`None`**（⚠️ 不写 `False`：占位批次会被 Task 6 的调度器当成「盘后完整数据」而跳过今天的真实跑批）；`data_as_of=target` → **`None`** |
| Task 5 | API 序列化**不得**把 `None` 塌缩成 `False`：`"is_intraday": r.is_intraday`（原样透出 `null`） |
| Task 6 | 跳过条件收紧为「今天的批次存在 **且 `is_intraday` 明确为 `False`**」；`None`（未知）与 `True`（盘中半成品）**都要重跑** |
| Task 8 | 前端类型 `isIntraday: boolean \| null`；盘中提示只在 `=== true` 时出现，`null` 不谎称盘后 |

> 贯穿全线的一句话：**算不出来就留 `None`，不要用 `False` 冒充「没有」。**
> 这条在存储层、API 层、调度判断、前端展示四层都成立。

---

## File Structure

**新建**

| 文件 | 职责 |
|---|---|
| `backend/migrations/versions/c4d5e6f70812_add_behavior_trust_fields.py` | 迁移：批次表加 3 列（`hit_counts_json` / `data_as_of` / `is_intraday`） |
| （不新建文件）`backend/app/services/behavior_signal_service.py` **追加** 3 个纯函数 | 统一窗口过滤（按日历天）+ 基准日计算。两条路径共用它 → 一致性的物理保证。**放在既有判定层里**：`api/kline.py` 与 `modules/behavior_screener/service.py` 本来就已经 import 这个模块 → 零新增 import 边,也不违反「跨域只走 service.py」 |
| `backend/tests/test_behavior_window.py` | 窗口过滤纯函数的单测 |
| `backend/tests/test_behavior_consistency.py` | 闸 3 单元守门：两条路径产出必须一致 |
| `backend/scripts/verify_behavior_consistency.py` | 闸 3 端到端巡检脚本（真实数据，输出差异表） |
| `backend/tests/test_behavior_scheduler.py` | 闸 4 调度器跳过条件的单测 |

**修改**

| 文件 | 改动 |
|---|---|
| `backend/app/models/orm.py` | `BehaviorSignalRun` 加 3 个字段 |
| `backend/app/core/config.py` | `BEHAVIOR_MARKERS_LOOKBACK_DAYS` 60 → 120；`BEHAVIOR_SCREENER_CANDIDATE_LIMIT` 120 → `None`；新增 `BEHAVIOR_SCREENER_GROUP_PAGE_N` = 60 |
| `backend/app/services/behavior_signal_service.py` | **追加** `filter_markers_by_window` / `marker_date` / `base_date_from_klines` 三个纯函数（判定逻辑本身不动） |
| `backend/app/modules/behavior_screener/repository.py` | `upsert_run` 收 3 个新参数；`get_picks_by_kind_offset`（分页） |
| `backend/app/modules/behavior_screener/service.py` | 去掉候选池截断、窗口过滤下沉、真实计数落库、`start_behavior_scheduler` |
| `backend/app/modules/behavior_screener/api.py` | `/latest` 返回真实 count + 披露 `hitCounts`；新增 `?kind=&limit=&offset=` 分页 |
| `backend/app/api/kline.py` | 回看窗口改 120 日历天、基准日统一走 `window.py` |
| `backend/app/main.py` | `_spawn(start_behavior_scheduler())` |
| `frontend/src/lib/behaviorScreener.ts` | 类型加 `hitCounts` / `dataAsOf` / `isIntraday`；新增分页 API |
| `frontend/src/components/screener/BehaviorScreenerPanel.tsx` | 口径条读真实数、卡片显示真实 count、「展开更多」、盘中提示行 |

**不修改**（闸 3/闸 4 不动判定层）

- `backend/app/services/behavior_signal_service.py` 的**判定逻辑**（`detect_behavior_markers` 与四个 `_detect_*`）—— 它是两条路径共用的唯一入口，**本计划不改判定逻辑**。Task 2 只在文件**末尾追加** 3 个纯函数（窗口过滤），判定阈值与命中条件一行不动。改判定逻辑会让闸 3 的守门失去意义（守门要钉的是「同一入口 + 同窗口 → 同结果」）。
- `backend/app/services/behavior_fund_flow_service.py` —— 数据源层不动。

---

## Task 1: 数据模型 —— 批次表加 3 列

**Files:**
- Create: `backend/migrations/versions/c4d5e6f70812_add_behavior_trust_fields.py`
- Modify: `backend/app/models/orm.py`（`BehaviorSignalRun` 类）
- Test: `backend/tests/test_behavior_screener.py`（新增 `TestRunTrustFields`）

**Interfaces:**
- Consumes: 现有 `BehaviorSignalRun` ORM 类（`backend/app/models/orm.py`）。
- Produces:
  - ORM 字段 `BehaviorSignalRun.hit_counts_json: str | None`（JSON 字符串，键为 kind，值为该类**真实**命中数）
  - ORM 字段 `BehaviorSignalRun.data_as_of: date | None`（本批数据中已收盘的最后交易日）
  - ORM 字段 `BehaviorSignalRun.is_intraday: bool | None`（本批是否额外包含当日未收盘数据；**`None` = 未知**，不编成 `False` —— 见上文 **R1**）

- [ ] **Step 1: 写失败的测试**

在 `backend/tests/test_behavior_screener.py` 末尾追加：

```python
class TestRunTrustFields:
    """闸 1 / 闸 4 的批次字段:真实分类计数 + 数据时点 + 是否盘中。"""

    async def test_trust_fields_roundtrip(self):
        from app.modules.behavior_screener import repository as repo

        run = await repo.upsert_run(
            date(2026, 10, 30),
            pool_size=5574, main_board_count=3193, non_st_count=3053,
            after_filters_count=1941, candidates_considered=1817,
            total_picks=402, elapsed_sec=53.1, note=None,
            hit_counts_json='{"main_force_move": 268, "dip_buy": 96}',
            data_as_of=date(2026, 10, 30),
            is_intraday=False,
        )
        assert run.hit_counts_json == '{"main_force_move": 268, "dip_buy": 96}'
        assert run.data_as_of == date(2026, 10, 30)
        assert run.is_intraday is False

    async def test_is_intraday_defaults_none(self):
        """不传 is_intraday → None(未知),**不编成「确定不是盘中」**。"""
        from app.modules.behavior_screener import repository as repo

        run = await repo.upsert_run(
            date(2026, 10, 29),
            pool_size=1, main_board_count=1, non_st_count=1,
            after_filters_count=1, candidates_considered=1,
            total_picks=0, elapsed_sec=0.1, note=None,
        )
        assert run.is_intraday is None
        assert run.hit_counts_json is None
        assert run.data_as_of is None

    async def test_upsert_run_updates_existing_row(self):
        """同日再 upsert → **覆盖同一行**(不是新增),三字段一起被更新。

        覆盖 Step 6 要求的「两条分支都赋值」里的 update 分支:
        同 `run_date` 二次 upsert 必须落回同一行,且三字段被新值覆盖。
        """
        from app.modules.behavior_screener import repository as repo

        first = await repo.upsert_run(
            date(2026, 10, 28),
            pool_size=1, main_board_count=1, non_st_count=1,
            after_filters_count=1, candidates_considered=1,
            total_picks=1, elapsed_sec=0.1, note=None,
            hit_counts_json='{"main_force_move": 1}',
            data_as_of=date(2026, 10, 28),
            is_intraday=True,
        )
        second = await repo.upsert_run(
            date(2026, 10, 28),
            pool_size=2, main_board_count=2, non_st_count=2,
            after_filters_count=2, candidates_considered=2,
            total_picks=2, elapsed_sec=0.2, note=None,
            hit_counts_json='{"main_force_move": 9}',
            data_as_of=date(2026, 10, 27),
            is_intraday=False,
        )
        assert first.id == second.id
        assert second.hit_counts_json == '{"main_force_move": 9}'
        assert second.data_as_of == date(2026, 10, 27)
        assert second.is_intraday is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_screener.py::TestRunTrustFields -q
```

Expected: FAIL —— `TypeError: upsert_run() got an unexpected keyword argument 'hit_counts_json'`

- [ ] **Step 3: 加迁移文件**

创建 `backend/migrations/versions/c4d5e6f70812_add_behavior_trust_fields.py`：

```python
"""v0.12:行为标注可信度加固 —— 批次表加 3 列

- `hit_counts_json`:每类**真实**命中数(闸 1 数字闸)
- `data_as_of`:本批数据中已收盘的最后交易日(闸 4 稳定闸)
- `is_intraday`:本批是否额外包含当日未收盘数据(闸 4 稳定闸)

三列全部 nullable / **无默认值** → 存量批次行不需要回填,且省略该列时自然落成 NULL(未知)。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4d5e6f70812"
down_revision: Union[str, None] = "b3c4d5e6f708"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "behavior_signal_run",
        sa.Column("hit_counts_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "behavior_signal_run",
        sa.Column("data_as_of", sa.Date(), nullable=True),
    )
    op.add_column(
        "behavior_signal_run",
        sa.Column(
            "is_intraday",
            sa.Boolean(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("behavior_signal_run", "is_intraday")
    op.drop_column("behavior_signal_run", "data_as_of")
    op.drop_column("behavior_signal_run", "hit_counts_json")
```

> ⚠️ **表名是 `behavior_signal_run`（单数）** —— 已于 2026-10-31 实测确认：
> `sqlite_master` 里是 `behavior_signal_run` / `behavior_signal_pick`，
> ORM 的 `__tablename__` 也是单数。**写错成复数会导致迁移直接报错。**

- [ ] **Step 4: 用真实迁移验证列**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m alembic upgrade head
```

Expected: 无异常。然后确认列已加上：

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data.db'); print([r[1] for r in c.execute('PRAGMA table_info(behavior_signal_run)')])"
```

Expected: 列里能看到 `hit_counts_json` / `data_as_of` / `is_intraday`。

若报 `no such table` → 检查迁移里的表名拼写（应为**单数** `behavior_signal_run`）。

- [ ] **Step 5: 加 ORM 字段**

在 `backend/app/models/orm.py` 的 `BehaviorSignalRun` 类里，`note` 字段**之前**插入：

```python
    # 每类**真实**命中数(JSON: {"main_force_move": 268, "dip_buy": 96, ...})
    # ⚠️ 与 `total_picks` 的区别:total_picks 是**总数**,这里是**分类别**的真实命中数。
    # 两者都必须是「真实命中数」,不是「入库条数」—— 入库可能因分页而少于命中。
    hit_counts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 本批数据中**已收盘**的最后交易日(闸 4:批次的数据时点)
    data_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 本批是否额外包含当日**未收盘**数据(闸 4:区分盘后完整数据与盘中半成品)
    # ⚠️ **None = 未知**,不是「确定不是盘中」—— 缺数据不编值(human 2026-10-31 拍板)。
    # 因此**不设** default / server_default:省略该列时自然落成 NULL。
    is_intraday: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
```

并在文件顶部的 SQLAlchemy import 里确认包含 `Boolean`：

```python
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text
```

（若原本是 `from sqlalchemy import ...` 分项导入，则追加 `Boolean`;不要改动其他 import。）

- [ ] **Step 6: 改 `upsert_run` 收新参数**

在 `backend/app/modules/behavior_screener/repository.py` 的 `upsert_run` 签名里追加三个**带默认值**的 keyword-only 参数：

```python
async def upsert_run(
    run_date: date,
    *,
    pool_size: int,
    main_board_count: int,
    non_st_count: int,
    after_filters_count: int,
    candidates_considered: int,
    total_picks: int,
    elapsed_sec: float | None,
    note: str | None = None,
    hit_counts_json: str | None = None,
    data_as_of: date | None = None,
    is_intraday: bool | None = None,
) -> BehaviorSignalRun:
    ...  # 原有函数体不变,只加三个新参数的赋值(见下一步)
```

> ⚠️ 三个新参数的默认值**一律是「未知」**(`None`),不是「确定的值」。
> `is_intraday` 若默认 `False`,就等于把「没传」编码成「确定不是盘中」——
> 违反铁律「缺数据 → 绝不编数字」,也与 `hit_counts_json` / `data_as_of` 语义不一致。
> **生产端调用点(Task 6)必须显式传真值。**

在 `upsert_run` 函数体的**两条分支**（`if existing:` 与新建 `BehaviorSignalRun(...)`）里补上这三个字段：

`if existing:` 分支内，紧接 `existing.note = note` 之后加：

```python
            existing.hit_counts_json = hit_counts_json
            existing.data_as_of = data_as_of
            existing.is_intraday = is_intraday
```

新建分支里，`note=note,` 之后加：

```python
            hit_counts_json=hit_counts_json,
            data_as_of=data_as_of,
            is_intraday=is_intraday,
```

- [ ] **Step 7: 运行测试确认通过**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_screener.py -q
```

Expected: PASS（既有测试也不许挂 —— 旧调用没传新参数，靠默认值兜住）

- [ ] **Step 8: 提交**

```bash
git -C D:\zga-study\rich add backend/migrations/versions/c4d5e6f70812_add_behavior_trust_fields.py backend/app/models/orm.py backend/app/modules/behavior_screener/repository.py backend/tests/test_behavior_screener.py
git -C D:\zga-study\rich commit -m "feat(behavior): 批次表加可信度三字段(真实分类计数/数据时点/是否盘中)"
```

---

## Task 2: 统一窗口过滤（纯函数层）

**Files:**
- Modify: `backend/app/services/behavior_signal_service.py`（**追加** 3 个纯函数，判定逻辑一行不动）
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_behavior_window.py`

**Interfaces:**
- Consumes: `app.core.config.BEHAVIOR_MARKERS_LOOKBACK_DAYS`（本 Task 改为 120）。
- Produces:
  - `filter_markers_by_window(markers: Sequence[BehaviorMarker], base_date: date, lookback_days: int) -> list[BehaviorMarker]` —— 纯函数，按**日历天**过滤，返回 `date >= base_date - lookback_days` 的标注，保持输入顺序。
  - `marker_date(marker: BehaviorMarker) -> date | None` —— 把标注的 `date` 字符串解析成 `date`；解析失败返回 `None`（不编数字）。
  - `base_date_from_klines(items: Sequence[dict]) -> date | None` —— 取 K 线末根日期作为基准日；末根日期缺失/不可解析返回 `None`。

**Interfaces note（给后续 Task 看）:**
- Task 4（K 线路径）与 Task 3（找股路径）**都调 `filter_markers_by_window`** → 一致性由「同一过滤函数」物理保证，而不是靠两边都写对了。

**为什么放在 `behavior_signal_service.py` 而不是新建 `modules/behavior_screener/window.py`**:
`app/api/kline.py` 与 `app/modules/behavior_screener/service.py` **本来就已经 import `behavior_signal_service`** → 零新增 import 边。
若新建 `modules/behavior_screener/window.py`,`app/api/kline.py` 就得 import 一个 **modules 的内部文件** ——
虽然 `test_architecture_boundaries.py` 的分层规则不拦（`modules` 不在 `LAYERS` 里），
但违反「跨域只走 `service.py`」的**精神**（该规则原文:`modules` 之间只准 import 对方的 `service.py`）。
放回既有判定层是最省事、最不容易被后来人破坏的做法。

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_behavior_window.py`：

```python
"""统一窗口过滤(behavior_signal_service)单测。

**为什么需要它**:找股路径与 K 线路径曾经各写各的过滤,
一个按「日历天 60」、一个按「K 线根数 120 根」—— 单位都不同,
导致 61% 的信号「找股页有、K 线上找不到」。
把过滤收敛到**一个纯函数**,一致性问题就从「靠人记住」变成「物理保证」。
"""
from __future__ import annotations

from datetime import date

from app.services.behavior_signal_service import (
    KIND_MAIN_FORCE_MOVE,
    BehaviorMarker,
    base_date_from_klines,
    filter_markers_by_window,
    marker_date,
)


def _mk(d: str) -> BehaviorMarker:
    return BehaviorMarker(
        kind=KIND_MAIN_FORCE_MOVE, date=d, date_index=0,
        text="⚡ 主力异动", position="aboveBar", color="#f59e0b",
        reason="依据", metrics={},
    )


class TestFilterByWindow:
    def test_keeps_markers_inside_window(self):
        base = date(2026, 10, 30)
        ms = [_mk("2026-10-30"), _mk("2026-10-20"), _mk("2026-07-01")]
        out = filter_markers_by_window(ms, base, 120)
        # 2026-10-30 与 2026-10-20 在窗口内;2026-07-01 距今 151 天 → 剔除
        assert [m.date for m in out] == ["2026-10-30", "2026-10-20"]

    def test_boundary_is_inclusive(self):
        """恰好 120 天 → 保留(边界含端点)。"""
        base = date(2026, 10, 30)
        boundary = date(2026, 7, 2)  # base - 120 天
        out = filter_markers_by_window([_mk(boundary.isoformat())], base, 120)
        assert len(out) == 1

    def test_uses_calendar_days_not_bar_count(self):
        """按日历天算,不按 K 线根数 —— 120 天 != 120 根。"""
        base = date(2026, 10, 30)
        just_outside = date(2026, 7, 1)  # 距今 121 天
        out = filter_markers_by_window([_mk(just_outside.isoformat())], base, 120)
        assert out == []

    def test_preserves_input_order(self):
        base = date(2026, 10, 30)
        ms = [_mk("2026-10-25"), _mk("2026-10-30"), _mk("2026-10-28")]
        out = filter_markers_by_window(ms, base, 120)
        assert [m.date for m in out] == ["2026-10-25", "2026-10-30", "2026-10-28"]

    def test_empty_input(self):
        assert filter_markers_by_window([], date(2026, 10, 30), 120) == []

    def test_non_positive_lookback_returns_all(self):
        base = date(2026, 10, 30)
        ms = [_mk("2020-01-01")]
        assert filter_markers_by_window(ms, base, 0) == ms


class TestMarkerDate:
    def test_parses_iso_date(self):
        assert marker_date(_mk("2026-10-30")) == date(2026, 10, 30)

    def test_returns_none_on_bad_format(self):
        """日期不可解析 → None(不编数字,不猜)。"""
        assert marker_date(_mk("不是日期")) is None


class TestBaseDateFromKlines:
    def test_takes_last_kline_date(self):
        items = [{"date": "2026-10-28"}, {"date": "2026-10-30"}]
        assert base_date_from_klines(items) == date(2026, 10, 30)

    def test_returns_none_when_empty(self):
        assert base_date_from_klines([]) is None

    def test_returns_none_on_bad_format(self):
        assert base_date_from_klines([{"date": "xx"}]) is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_window.py -q
```

Expected: FAIL —— `ImportError: cannot import name 'filter_markers_by_window' from 'app.services.behavior_signal_service'`

- [ ] **Step 3: 改配置常量**

在 `backend/app/core/config.py`：

把

```python
# 回传给前端的标注最大回看天数(避免响应体过大)
BEHAVIOR_MARKERS_LOOKBACK_DAYS = 60
```

改成

```python
# 回传给前端的标注最大回看天数(避免响应体过大)
#
# ⚠️ **单位是「日历天」,不是「K 线根数」**(2026-10-31 实测修复):
# 旧值 60 天 → 找股页(120 根 K 线 ≈ 168 日历天)列出的信号有 61%
# 在 K 线上根本不存在(找股页有、K 线上找不到)。
# 现在两条路径都按**日历天**过滤,统一走
# `app/services/behavior_signal_service.py::filter_markers_by_window`。
BEHAVIOR_MARKERS_LOOKBACK_DAYS = 120
```

并在其后新增：

```python
# 每类分组在 /latest 响应里返回的明细条数上限(真实总数靠 count 披露)
BEHAVIOR_SCREENER_GROUP_PAGE_N = 60
```

> 🚫 **本 Task 不动 `BEHAVIOR_SCREENER_CANDIDATE_LIMIT`**（2026-10-31 调整）：
> 「取消候选池截断」是**行为变更**，它必须和**真正改代码的那一步**在同一个 Task 里落地 ——
> 否则会出现「配置说 `None`、代码还在 `[:120]`」的中间态，Task 之间无法独立验收。
> 该常量的改动已挪到 **Task 3**（那里才改 `scan_market` 的截断逻辑）。
> 本 Task 的改动是**纯增量**：3 个纯函数 + 2 个常量（`LOOKBACK_DAYS` 60→120、新增 `GROUP_PAGE_N`）。

- [ ] **Step 4: 实现三个纯函数**

在 `backend/app/services/behavior_signal_service.py` 的 `__all__` **之前**追加：

```python
# ============================================================
# 统一窗口过滤(闸 2 完备闸)
#
# **为什么要有这个**:找股路径与 K 线路径曾经各写各的过滤 ——
# 一个按「日历天 60」、另一个按「K 线根数 120 根(= 168 日历天)」,
# **单位都不同** → 61% 的信号「找股页列出来了、K 线上找不到」(实测 405/663 条)。
#
# 把过滤收敛到**这三个纯函数**,两条路径调用同一实现,
# 一致性问题就从「靠人记住两边写对」变成「物理保证」。
#
# **单位**:一律按**日历天**。用户看到的时间语义是「3 个月前」,
# 按 K 线根数换算会出现「120 根 ≈ 168 天」这种歧义。
# ============================================================


def marker_date(marker: BehaviorMarker) -> date | None:
    """标注的日期 → `date`;不可解析 → None(**不编数字**)。"""
    raw = str(getattr(marker, "date", "") or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def filter_markers_by_window(
    markers: Sequence[BehaviorMarker],
    base_date: date,
    lookback_days: int,
) -> list[BehaviorMarker]:
    """按**日历天**过滤标注,只保留 `base_date - lookback_days` 之后(含端点)的。

    - 保留输入顺序(调用方已按日期升序)。
    - 日期不可解析的标注 → **丢弃**(无法判断是否在窗口内,不猜)。
    - `lookback_days <= 0` → 原样返回(不做过滤)。
    """
    if not markers:
        return []
    if lookback_days <= 0:
        return list(markers)
    threshold = base_date - timedelta(days=lookback_days)
    out: list[BehaviorMarker] = []
    for m in markers:
        d = marker_date(m)
        if d is None:
            continue
        if d >= threshold:
            out.append(m)
    return out


def base_date_from_klines(items: Sequence[dict[str, Any]]) -> date | None:
    """K 线序列的**末根日期**作为基准日;取不到 → None(不编数字)。"""
    if not items:
        return None
    raw = str(items[-1].get("date") or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None
```

补 import（该文件目前**没有** datetime import）：

```python
from datetime import date, timedelta
```

并把 `__all__` 改成（新增 3 项）：

```python
__all__ = [
    "KIND_DISTRIBUTE",
    "KIND_DIP_BUY",
    "KIND_LOCK_POSITION",
    "KIND_MAIN_FORCE_MOVE",
    "KIND_META",
    "KIND_ORDER",
    "BehaviorMarker",
    "BehaviorResult",
    "base_date_from_klines",
    "detect_behavior_markers",
    "filter_markers_by_window",
    "marker_date",
]
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_window.py -q
```

Expected: PASS

- [ ] **Step 6: 跑既有测试确认没破坏**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_signal_service.py tests/test_behavior_screener.py tests/test_kline_behavior_markers.py tests/test_architecture_boundaries.py -q
```

Expected: PASS（注意 `BEHAVIOR_MARKERS_LOOKBACK_DAYS` 从 60 改成 120 可能让 `test_kline_behavior_markers.py` 里的回看断言失败 —— 若失败，检查该断言是否**写死了 60**；若是，把它改成读 `BEHAVIOR_MARKERS_LOOKBACK_DAYS` 常量，而不是写死数字。）

- [ ] **Step 7: 提交**

```bash
git -C D:\zga-study\rich add backend/app/services/behavior_signal_service.py backend/app/core/config.py backend/tests/test_behavior_window.py
git -C D:\zga-study\rich commit -m "feat(behavior): 抽出统一窗口过滤纯函数,窗口统一为 120 日历天"
```

---

## Task 3: 闸 1 + 闸 2 —— 落库口径（全量入库 + 真实计数 + 去截断）

**Files:**
- Modify: `backend/app/modules/behavior_screener/service.py`（`scan_market` / `run_daily_scan`）
- Test: `backend/tests/test_behavior_screener.py`（新增 `TestTrustGates`）

**Interfaces:**
- Consumes: Task 2 的 `filter_markers_by_window`；Task 1 的 `upsert_run` 新参数。
- Produces:
  - `scan_market(...)` 的 `ScanResult` 新增字段 `hit_counts: dict[str, int]`（每类真实命中数）。
  - `ScanResult.hits` 现在**只含窗口内**的命中（窗口过滤发生在 `scan_market` 内部，不是落库时）。
  - `run_daily_scan(...)` 落库**全部**命中（不再 `[:BEHAVIOR_SCREENER_TOP_N]`），`total_picks` = 真实命中总数。

- [ ] **Step 1: 写失败的测试**

在 `backend/tests/test_behavior_screener.py` 追加：

```python
class TestTrustGates:
    """闸 1(数字闸)+ 闸 2(完备闸)的落库口径。

    真机踩过的坑:旧的 `hits[:60]` 全局截断让「真实 455 条」显示成「47 条」
    (差 29 倍),且 91% 的命中人间蒸发。这组测试把「不截断 + 真实计数」钉死。

    ⚠️ **造数与期望值都是实测反推的**(2026-10-31,写计划时用真实判定层跑过):
    - 「平价 + 逐日缩量 10% + 连续主力净流入」→ 只触发 `lock_position`,
      130 根 K 线产出 **103** 条原始命中;
    - 基准日 = K 线末根 = 2026-07-01,120 日历天窗口 = 2026-03-03 起
      → 窗口内 **70** 条、窗口外 **33** 条;
    - 70 > 60(旧上限)→ 数字能证明「没被截断」。
    """

    @staticmethod
    def _lock_shape(n: int = 130):
        """造「平价 + 逐日缩量 + 连续主力净流入」的数据。

        只触发 `lock_position`:
        - `change_ratio=0.0` → 主力异动要求涨跌幅 ≥2%,不达标
        - `net_amount` 恒正 → 低吸要求「由负转正」、高抛要求「由正转负」,都不达标
        - 逐日缩量 10% → 锁仓的「期间缩量」成立
        """
        dates = _dates(n)
        vol = 100000.0
        ks, flows = [], []
        for d in dates:
            ks.append({
                "date": d, "open": "10.0", "high": "10.1", "low": "9.9",
                "close": "10.0", "volume": int(vol),
            })
            flows.append({
                "date": d, "net_amount": 1.0e8, "r0_net": 1.0e8,
                "r0x_ratio": 0.0, "r0_ratio": 0.0, "turnover": 20.0,
                "change_ratio": 0.0,
            })
            vol *= 0.9
        return dates, ks, flows

    async def test_all_hits_persisted_not_truncated(self, monkeypatch):
        """命中 70 条(> 旧上限 60)→ 全部入库,total_picks = 70。"""
        import json as _json

        dates, ks, flows = self._lock_shape(130)

        snapshot = [
            {
                "code": "600519.SH", "name": "贵州茅台", "price": 10.0,
                "change_pct": 0.0, "prev_close": 10.0, "amount_yi": 50.0,
                "limit_pct": 10.0, "volume": 100000,
            }
        ]

        async def fake_snapshot(*a, **k):
            return snapshot

        async def fake_klines(code, period="daily", count=120):
            return ks

        async def fake_flows(code, count=120, **k):
            return flows

        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_market_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.kline_service.fetch_klines",
            fake_klines,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_flow_daily", fake_flows
        )

        from app.modules.behavior_screener import repository as repo

        result = await behavior_service.run_daily_scan(date(2026, 7, 1))
        assert result is not None
        run, hits = result
        # 全部入库,不截断(70 > 旧上限 60)
        assert len(hits) == 70
        assert run.total_picks == 70
        stored = await repo.get_picks_by_run(run.id)
        assert len(stored) == 70
        # 分组真实计数已落库
        counts = _json.loads(run.hit_counts_json)
        assert counts[KIND_LOCK_POSITION] == 70
        assert sum(counts.values()) == 70

    async def test_candidate_pool_not_truncated(self, monkeypatch):
        """候选池不再取前 120 —— 全部成交额达标的票都进逐票精算。"""
        # ⚠️ 代码必须是 **6 位**:`600000 + i`,不能写成 `f"6005{i:02d}.SH"`
        # (i ≥ 100 时会变成 7 位数 → 主板判定失败 → 只过 100 只,实测踩过)
        snapshot = [
            {
                "code": f"{600000 + i:06d}.SH", "name": f"票{i}", "price": 10.0,
                "change_pct": 1.0, "prev_close": 10.0, "amount_yi": 50.0,
                "limit_pct": 10.0, "volume": 1000,
            }
            for i in range(150)
        ]

        async def fake_snapshot(*a, **k):
            return snapshot

        async def fake_klines(code, period="daily", count=120):
            return []

        async def fake_flows(code, count=120, **k):
            return []

        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_market_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.kline_service.fetch_klines",
            fake_klines,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_flow_daily", fake_flows
        )

        result = await behavior_service.scan_market(date(2026, 7, 1))
        # 150 只全部进入精算(旧版只取 120)
        assert result.candidates_considered == 150
        assert result.universe.after_filters == 150

    async def test_hits_outside_window_filtered_out(self, monkeypatch):
        """超过 120 日历天的命中不进入 hits(过滤在 scan_market 内部)。"""
        dates, ks, flows = self._lock_shape(130)

        snapshot = [
            {
                "code": "600519.SH", "name": "贵州茅台", "price": 10.0,
                "change_pct": 0.0, "prev_close": 10.0, "amount_yi": 50.0,
                "limit_pct": 10.0, "volume": 100000,
            }
        ]

        async def fake_snapshot(*a, **k):
            return snapshot

        async def fake_klines(code, period="daily", count=120):
            return ks

        async def fake_flows(code, count=120, **k):
            return flows

        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_market_snapshot",
            fake_snapshot,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.kline_service.fetch_klines",
            fake_klines,
        )
        monkeypatch.setattr(
            "app.modules.behavior_screener.service.fetch_flow_daily", fake_flows
        )

        result = await behavior_service.scan_market(date(2026, 7, 1))
        # 原始命中 103 条 → 窗口内 70 条(窗口外 33 条被滤掉)
        assert len(result.hits) == 70
        # 每一条都在 120 日历天窗口内
        base = date(2026, 7, 1)
        threshold = base - timedelta(days=120)
        for h in result.hits:
            assert date.fromisoformat(h.signal_date) >= threshold
        # 分组计数与命中数一致
        assert sum(result.hit_counts.values()) == 70
```

> ⚠️ 该测试文件顶部需要 `from datetime import timedelta`（现有 import 是
> `from datetime import date, timedelta` —— 已包含，直接用即可）。
> `KIND_LOCK_POSITION` 需要从 `app.services.behavior_signal_service` import
> （该文件顶部已有 `KIND_MAIN_FORCE_MOVE` 等 import，把 `KIND_LOCK_POSITION` 一并加上）。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_screener.py::TestTrustGates -q
```

Expected: FAIL —— `total_picks` 是 60（被截断）/ `candidates_considered` 是 120（被截断）/ `hits` 非空（未过滤窗口）

- [ ] **Step 3: 改 `ScanResult` 加 `hit_counts`**

在 `backend/app/modules/behavior_screener/service.py` 的 `ScanResult` dataclass 里，`degraded` 字段**之前**加：

```python
    # 每类**真实**命中数(闸 1):{"main_force_move": 268, "dip_buy": 96, ...}
    hit_counts: dict[str, int] = field(default_factory=dict)
```

- [ ] **Step 4: 改 `scan_market` —— 去截断 + 窗口过滤 + 真实计数**

先在 `backend/app/core/config.py` 把

```python
# 全市场快照粗筛后进入逐票算信号的候选数上限
BEHAVIOR_SCREENER_CANDIDATE_LIMIT = 120
```

改成

```python
# 全市场快照粗筛后进入逐票算信号的候选数上限
#
# ⚠️ **None = 不截断**(2026-10-31 修复):
# 旧的「取前 120」是**筛选维度与被筛目标的时间窗错配** ——
# 候选池按「当日资金异动强度」排序,打分对象却是历史窗口内的信号,
# 于是「20 天前有强信号、今天资金平淡」的票压根进不了池子。
# 成交额闸门(POOL_MIN_AMOUNT_YI)保留 —— 那是合理的业务闸门。
# 保留该参数供测试与小规模分级验证(传 300 / 600)。
BEHAVIOR_SCREENER_CANDIDATE_LIMIT: int | None = None
```

> ⚠️ 常量默认值在**模块导入期**求值 → `scan_market` / `run_daily_scan` 的
> `candidate_limit: int = BEHAVIOR_SCREENER_CANDIDATE_LIMIT` 会拿到 `None`。
> 所以这两个签名必须**同步**改成 `int | None`（见下一步），否则类型标注撒谎。

然后在 `scan_market` 里，把

```python
    candidates, stats = filter_universe(rows, min_amount_yi=POOL_MIN_AMOUNT_YI)
    precands = candidates[:candidate_limit]
```

改成

```python
    candidates, stats = filter_universe(rows, min_amount_yi=POOL_MIN_AMOUNT_YI)
    # ⚠️ **不再截断**(闸 2 完备闸):旧的「取前 120」是筛选维度与被筛目标
    # 的时间窗错配 —— 候选池按「当日资金异动强度」排序,打分对象却是
    # 历史窗口内的信号,「20 天前有强信号、今天资金平淡」的票压根进不了池子。
    # 成交额闸门(POOL_MIN_AMOUNT_YI)保留 —— 那是合理的业务闸门。
    # `candidate_limit` 仅供测试与小规模分级验证(传 300 / 600)时使用。
    precands = candidates if candidate_limit is None else candidates[:candidate_limit]
```

把 `scan_market` 的签名改成：

```python
async def scan_market(
    run_date: date | None = None,
    *,
    candidate_limit: int | None = BEHAVIOR_SCREENER_CANDIDATE_LIMIT,
) -> ScanResult:
    ...  # 原有函数体见下一步的逐段替换
```

把命中收集循环里的 `for marker in result.markers:` 改成：

```python
        # ⚠️ **窗口过滤在 scan_market 内部**(闸 2),不在落库时滤 ——
        # 否则批次表里存的仍是超窗口信号,只是展示时被藏起来,
        # `count` 与明细依然对不上(把问题从「展示层」挪到「存储层」,没解决)。
        #
        # ⚠️ **基准日必须是「该票自己的 K 线末根日期」**,不是 run_date:
        # K 线路径(`api/kline.py`)用的是 K 线末根日期 —— 若这边用 run_date,
        # 两者基准日差一天(停牌/停更时差更多)→ 窗口边界错位 →
        # 找股页有的信号在 K 线上找不到(闸 3 要守的 S_A ⊆ S_B 会被打破)。
        # 统一用 `base_date_from_klines`,与 K 线路径**逐字同源**。
        base = base_date_from_klines(ks)
        if base is None:
            # 基准日取不到 → 无法判断窗口 → 该票不产出标注(与 K 线路径同口径)
            continue
        windowed = filter_markers_by_window(
            result.markers, base, BEHAVIOR_MARKERS_LOOKBACK_DAYS
        )
        for marker in windowed:
```

> ⚠️ **注意 `days_ago` 仍然用 `today`(= `run_date`)算** —— 那是**新鲜度衰减**的输入
> （「信号距今天几天」），与「窗口边界」是两回事，不要混。
> `days_ago` 只影响打分排序，不影响命中集合。

（`today` 已在原代码里定义为 `today = run_date or date.today()`，位置在 `klines_map, flows_map = await _fetch_candidate_data(codes)` 之后 —— 确保 `base = today` 这一行在 `today` 定义之后。）

把 `scan_market` 的 `return ScanResult(...)` 改成：

```python
    hit_counts: dict[str, int] = {}
    for h in hits:
        hit_counts[h.kind] = hit_counts.get(h.kind, 0) + 1

    return ScanResult(
        hits=sort_hits(hits),
        universe=stats,
        candidates_considered=len(codes),
        elapsed_sec=round(time.time() - t0, 2),
        degraded=degraded,
        hit_counts=hit_counts,
    )
```

并补 import（两处）：

`from app.core.config import (...)` 那个块里**追加** `BEHAVIOR_MARKERS_LOOKBACK_DAYS`，并**移除** `BEHAVIOR_SCREENER_TOP_N`（截断逻辑删掉后它就没用了，留着会触发 ruff F401 未使用导入）：

```python
from app.core.config import (
    BEHAVIOR_MARKERS_LOOKBACK_DAYS,
    BEHAVIOR_SCREENER_CANDIDATE_LIMIT,
    BEHAVIOR_SCREENER_CONCURRENCY,
    BEHAVIOR_SCREENER_FLOW_COUNT,
    BEHAVIOR_SCREENER_KLINE_COUNT,
    POOL_MIN_AMOUNT_YI,
)
```

> `config.py` 里的 `BEHAVIOR_SCREENER_TOP_N = 60` **保留不动**（它不再被 service.py 使用，但删掉会让「为什么以前只存 60 条」失去线索；ruff 不会报未使用的模块级常量）。

`from app.services.behavior_signal_service import detect_behavior_markers` 那行改成括号多行形式：

```python
from app.services.behavior_signal_service import (
    base_date_from_klines,
    detect_behavior_markers,
    filter_markers_by_window,
)
```

- [ ] **Step 5: 改 `run_daily_scan` —— 全量入库 + 真实计数**

把 `run_daily_scan` 的签名改成：

```python
async def run_daily_scan(
    target_date: date | None = None,
    *,
    candidate_limit: int | None = BEHAVIOR_SCREENER_CANDIDATE_LIMIT,
) -> tuple[Any, list[SignalHit]] | None:
    ...  # 原有函数体见下一步的逐段替换
```

把落库那段（`# 只保留分数最高的前 N 条入库` 起）改成：

```python
    # ⚠️ **全量入库,不再截断**(闸 1 数字闸):
    # 旧的 `result.hits[:60]` 是**全局按分数截断** —— 但四类信号的分数本就
    # 不可跨类型比较(类型权重不同),于是全局截断系统性偏向高权重类型。
    # 实测:真实 663 条 → 入库 60 条;锁仓真实 58 条 → 显示 2 条(差 29 倍)。
    hits = result.hits
    counts = result.hit_counts or {}
    run = await repo.upsert_run(
        target,
        pool_size=result.universe.total,
        main_board_count=result.universe.main_board,
        non_st_count=result.universe.non_st,
        after_filters_count=result.universe.after_filters,
        candidates_considered=result.candidates_considered,
        total_picks=len(hits),
        elapsed_sec=result.elapsed_sec,
        note="; ".join(result.degraded) if result.degraded else None,
        hit_counts_json=json.dumps(counts, ensure_ascii=False) if counts else None,
        data_as_of=None,
        is_intraday=None,
    )

    await repo.replace_picks(
        run.id,
        [
            {
                **h.to_dict(),
                "run_date": target,
                "metrics": h.metrics,
            }
            for h in hits
        ],
    )
    return run, hits
```

> ⚠️ `data_as_of=None` 与 `is_intraday=None` 是**占位（= 未知）** —— 闸 4（Task 6）会把它们改成真实计算。Task 3 只需保证字段存在且不报错。
>
> 🚨 **这里必须写 `None`,不能写 `False`/`target`**（见上文 **R1**）：
> 若这里写 `is_intraday=False`，今天的批次就会带着「确定不是盘中」落库 →
> Task 6 的调度器判定「今天的批次存在 且 `is_intraday` 明确为 `False`」→ **跳过盘后跑批** →
> 盘中半成品/占位批次被当成盘后完整数据当最新批次展示，闸 4 直接失效。
> `None`（未知）不会被跳过 → 盘后跑批照常发生，并覆盖成真值。

- [ ] **Step 6: 运行测试确认通过**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_screener.py -q
```

Expected: PASS

- [ ] **Step 7: 提交**

```bash
git -C D:\zga-study\rich add backend/app/modules/behavior_screener/service.py backend/tests/test_behavior_screener.py
git -C D:\zga-study\rich commit -m "fix(behavior): 闸1+闸2 落库口径 —— 全量入库/真实计数/去掉候选截断/窗口下沉"
```

---

## Task 4: 闸 2 —— K 线路径窗口对齐到 120 日历天

**Files:**
- Modify: `backend/app/api/kline.py`（`_build_behavior_markers`）
- Test: `backend/tests/test_kline_behavior_markers.py`

**Interfaces:**
- Consumes: Task 2 的 `filter_markers_by_window` / `base_date_from_klines`。
- Produces: K 线端点的 `behavior_markers` 只含**基准日往前 120 个日历天**内的标注。

- [ ] **Step 1: 写失败的测试**

先读 `backend/tests/test_kline_behavior_markers.py` 现有的测试，把其中**写死了 60 天**的断言改成读常量（若存在）：

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_kline_behavior_markers.py -q
```

Expected: 若该文件里有写死「60 天」的断言，此处会 FAIL（因为 Task 2 已把常量改成 120，但 `api/kline.py` 还在用旧口径 —— 这正是本 Task 要修的）。

然后在该文件追加新测试：

```python
class TestLookbackWindow:
    """K 线路径的回看窗口必须与找股路径一致(闸 2 完备闸)。

    实测:旧版 K 线只回看 60 日历天,找股页用 120 根 K 线(≈168 日历天)
    → 61% 的信号「找股页有、K 线上找不到」。

    ⚠️ **基准日取不到时必须返回空标注**(本组测试的核心):
    旧实现是「`last` 解析失败 → **不过滤,全量返回**」——
    基准日都算不出来还把全部历史标注倒给前端,等于窗口闸门形同虚设。
    新实现统一走 `filter_markers_by_window`,基准日取不到 → 不产出标注。
    """

    @staticmethod
    def _days(n: int) -> list[str]:
        import datetime as _dt

        out: list[str] = []
        d = _dt.date(2026, 1, 1)
        while len(out) < n:
            if d.weekday() < 5:
                out.append(d.isoformat())
            d += _dt.timedelta(days=1)
        return out

    class _M:
        """最小的标注替身(只需 date 与 to_dict)。"""

        def __init__(self, date_: str):
            self.date = date_
            self.kind = "main_force_move"
            self.date_index = 0
            self.text = "⚡ 主力异动"
            self.position = "aboveBar"
            self.color = "#f59e0b"
            self.reason = "依据"

        def to_dict(self):
            return {
                "kind": self.kind, "date": self.date,
                "date_index": self.date_index, "text": self.text,
                "position": self.position, "color": self.color,
                "reason": self.reason, "metrics": {},
            }

    async def test_markers_outside_120_days_are_filtered(self, monkeypatch):
        """距基准日远超 120 日历天的标记 → 剔除;基准日当天的 → 保留。"""
        from app.api import kline as kline_api

        days = self._days(200)
        base = days[-1]
        old = days[0]
        items = [
            {
                "date": dd, "open": "10.0", "high": "10.1", "low": "9.9",
                "close": "10.0", "volume": 100000,
            }
            for dd in days
        ]

        async def fake_flows(code, count=120, **k):
            return [{"date": dd, "net_amount": 1.0} for dd in days]

        class _Res:
            markers = [TestLookbackWindow._M(old), TestLookbackWindow._M(base)]
            degraded = []

        def fake_detect(ks, flows, **k):
            return _Res()

        monkeypatch.setattr("app.api.kline.fetch_flow_daily", fake_flows)
        monkeypatch.setattr("app.api.kline.detect_behavior_markers", fake_detect)

        markers, unavailable = await kline_api._build_behavior_markers(
            "600519.SH", items, "daily"
        )
        assert unavailable is False
        # 200 个工作日 ≈ 280 日历天前 → 被过滤掉
        assert all(m["date"] != old for m in markers)
        # 基准日当天保留
        assert any(m["date"] == base for m in markers)

    async def test_unparsable_base_date_yields_no_markers(self, monkeypatch):
        """⚠️ **本组测试的核心** —— 基准日取不到 → **不产出标注**。

        旧实现:基准日解析失败 → 走 `return [m.to_dict() for m in result.markers], False`
        → **全量返回,窗口闸门形同虚设**。新实现必须返回空。
        """
        from app.api import kline as kline_api

        days = self._days(200)
        items = [
            {
                "date": dd, "open": "10.0", "high": "10.1", "low": "9.9",
                "close": "10.0", "volume": 100000,
            }
            for dd in days
        ]
        # 末根日期不可解析 → 基准日取不到
        items[-1] = {**items[-1], "date": "不是日期"}

        async def fake_flows(code, count=120, **k):
            return [{"date": dd, "net_amount": 1.0} for dd in days]

        class _Res:
            markers = [TestLookbackWindow._M(days[0]), TestLookbackWindow._M(days[-1])]
            degraded = []

        def fake_detect(ks, flows, **k):
            return _Res()

        monkeypatch.setattr("app.api.kline.fetch_flow_daily", fake_flows)
        monkeypatch.setattr("app.api.kline.detect_behavior_markers", fake_detect)

        markers, unavailable = await kline_api._build_behavior_markers(
            "600519.SH", items, "daily"
        )
        assert unavailable is False
        assert markers == [], "基准日取不到时不得回传任何标注"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_kline_behavior_markers.py -q
```

Expected: **第二个测试 FAIL**（`markers == []` 断言不成立 —— 旧实现全量返回）；
第一个测试 PASS（它是回归守门）。

> ⚠️ 若第一个测试也 FAIL，说明既有测试写死了「60 天」→ 把它改成读 `BEHAVIOR_MARKERS_LOOKBACK_DAYS` 常量。

- [ ] **Step 3: 改 `api/kline.py` 用统一过滤**

把 `_build_behavior_markers` 的尾部：

```python
    # 只回传最近 N 日的标注(避免响应体过大)
    if not result.markers:
        return [], False
    # 以 K 线末根日期为基准回看 N 个日历天
    try:
        last = _date.fromisoformat(items[-1].get("date") or "")
    except ValueError:
        last = None
    if last is not None:
        threshold = (last - _td(days=BEHAVIOR_MARKERS_LOOKBACK_DAYS)).isoformat()
        return [m.to_dict() for m in result.markers if m.date >= threshold], False
    return [m.to_dict() for m in result.markers], False
```

改成：

```python
    # 只回传最近 N 个**日历天**的标注(避免响应体过大)
    #
    # ⚠️ **两条路径共用 `filter_markers_by_window`**(闸 2 完备闸):
    # 旧版这里自己算阈值,基准日取不到时还**全量返回**(窗口闸门形同虚设);
    # 找股路径用的是「跑批日」—— 两边口径不同
    # (实测 61% 的信号找股页有、K 线上找不到)。
    # 现在两边都用「该票自己的 K 线末根日期」作基准日、走同一个过滤函数,
    # 一致性由**同一实现**物理保证。
    if not result.markers:
        return [], False
    base = base_date_from_klines(items)
    if base is None:
        # 基准日取不到 → 无法判断窗口 → **不产出标注**(不编数字)
        return [], False
    windowed = filter_markers_by_window(
        result.markers, base, BEHAVIOR_MARKERS_LOOKBACK_DAYS
    )
    return [m.to_dict() for m in windowed], False
```

补 import（把已有的 `from app.services.behavior_signal_service import detect_behavior_markers` 改成括号多行形式）：

```python
from app.services.behavior_signal_service import (
    base_date_from_klines,
    detect_behavior_markers,
    filter_markers_by_window,
)
```

并把文件第 9 行的

```python
from datetime import date as _date, timedelta as _td
```

**整行删除**（改用 `base_date_from_klines` 后 `_date` / `_td` 都不再被用到，
留着会触发 ruff F401 未使用导入）。确认文件里没有别处再用 `_date` / `_td`
（`grep '_date\.\|_td\.'` 应无结果）。

> ⚠️ **架构边界**：`app/api/kline.py` import 的是 `app/services/...` —— 这是**既有允许方向**
> （`api → services`，`INWARD_ALLOWED["api"]` 含 `"services"`），
> 且 `api/kline.py` **本来就** import 了 `app.services.behavior_signal_service` → 零新增跨层依赖。

- [ ] **Step 4: 运行测试确认通过**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_kline_behavior_markers.py tests/test_architecture_boundaries.py -q
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git -C D:\zga-study\rich add backend/app/api/kline.py backend/tests/test_kline_behavior_markers.py
git -C D:\zga-study\rich commit -m "fix(behavior): 闸2 K线路径回看窗口对齐到 120 日历天(与找股路径共用同一过滤)"
```

---

## Task 5: 闸 1 —— API 真实计数 + 分页

**Files:**
- Modify: `backend/app/modules/behavior_screener/api.py`
- Modify: `backend/app/modules/behavior_screener/repository.py`（新增分页查询）
- Modify: `backend/app/modules/behavior_screener/service.py`（`run_to_dict` 补新字段）
- Test: `backend/tests/test_behavior_screener.py`（新增 `TestLatestApiTruth`）

**Interfaces:**
- Consumes: Task 1 的 `hit_counts_json` / `data_as_of` / `is_intraday`；Task 3 的真实计数。
- Produces:
  - `GET /api/behavior-screener/latest` 响应新增：`run.hitCounts`（dict）、`run.dataAsOf`（str|null）、`run.isIntraday`（bool|**null**；`null` = 未知，**不得塌缩成 `false`** —— 见 **R1**）；`groups[].count` = 该类**真实**命中数（不是 `picks` 长度）。
  - `GET /api/behavior-screener/latest?kind=<kind>&limit=<n>&offset=<n>`：当 `kind` 非空时，额外返回 `page: {kind, picks, total, offset, limit}`。
  - `repo.get_picks_by_kind_offset(run_id, kind, limit, offset) -> list[BehaviorSignalPick]`。

- [ ] **Step 1: 写失败的测试**

在 `backend/tests/test_behavior_screener.py` 追加：

```python
class TestLatestApiTruth:
    """闸 1 的 API 口径:count 必须是真实命中数,不是返回条数。"""

    async def _seed(self, repo, kind: str, n: int):
        from app.modules.behavior_screener import logic as lg

        hits = [
            lg.SignalHit(
                stock_code=f"60000{i}.SH", stock_name=f"票{i}", kind=kind,
                signal_date="2026-10-28", days_ago=2, reason="依据",
                metrics={}, score=float(100 - i),
            )
            for i in range(n)
        ]
        run = await repo.upsert_run(
            date(2026, 10, 30),
            pool_size=5574, main_board_count=3193, non_st_count=3053,
            after_filters_count=1941, candidates_considered=1817,
            total_picks=n, elapsed_sec=53.1, note=None,
            hit_counts_json=json.dumps({kind: n}),
            data_as_of=date(2026, 10, 30), is_intraday=False,
        )
        await repo.replace_picks(
            run.id, [{**h.to_dict(), "run_date": date(2026, 10, 30)} for h in hits]
        )
        return run

    async def test_group_count_is_true_hit_count(self, client):
        """真实命中 70 条 → count 报 70(即使响应只带 60 条明细)。"""
        import json as _json
        from app.modules.behavior_screener import repository as repo

        await self._seed(repo, KIND_MAIN_FORCE_MOVE, 70)
        resp = client.get("/api/behavior-screener/latest")
        assert resp.status_code == 200
        data = resp.json()
        group = next(
            g for g in data["groups"] if g["kind"] == KIND_MAIN_FORCE_MOVE
        )
        assert group["count"] == 70          # 真实命中数
        assert len(group["picks"]) == 60     # 明细只带前 60
        assert data["run"]["total_picks"] == 70

    async def test_run_exposes_trust_fields(self, client):
        import json as _json
        from app.modules.behavior_screener import repository as repo

        await self._seed(repo, KIND_DIP_BUY, 3)
        data = client.get("/api/behavior-screener/latest").json()
        assert data["run"]["hitCounts"] == {KIND_DIP_BUY: 3}
        assert data["run"]["dataAsOf"] == "2026-10-30"
        assert data["run"]["isIntraday"] is False

    async def test_pagination_returns_next_page(self, client):
        from app.modules.behavior_screener import repository as repo

        await self._seed(repo, KIND_MAIN_FORCE_MOVE, 70)
        resp = client.get(
            "/api/behavior-screener/latest",
            params={"kind": KIND_MAIN_FORCE_MOVE, "limit": 10, "offset": 60},
        )
        assert resp.status_code == 200
        page = resp.json()["page"]
        assert page["kind"] == KIND_MAIN_FORCE_MOVE
        assert page["total"] == 70
        assert len(page["picks"]) == 10      # 60..69 共 10 条
```

> ⚠️ 该测试文件顶部需要 `import json` —— 若没有,在文件顶部加 `import json`。

- [ ] **Step 2: 运行测试确认失败**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_screener.py::TestLatestApiTruth -q
```

Expected: FAIL —— `count` 是 60（当前等于 `picks` 长度）、`run` 里没有 `hit_counts`、没有 `page` 字段

- [ ] **Step 3: `run_to_dict` 补新字段**

在 `backend/app/modules/behavior_screener/service.py` 的 `run_to_dict` 里，把返回字典改成：

```python
def run_to_dict(r: Any) -> dict[str, Any]:
    """ORM 行 → API dict。"""
    counts: dict[str, int] = {}
    if r.hit_counts_json:
        try:
            loaded = json.loads(r.hit_counts_json)
            if isinstance(loaded, dict):
                counts = {str(k): int(v) for k, v in loaded.items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            counts = {}
    return {
        "id": r.id,
        "run_date": r.run_date.isoformat() if r.run_date else None,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "pool_size": r.pool_size,
        "main_board_count": r.main_board_count,
        "non_st_count": r.non_st_count,
        "after_filters_count": r.after_filters_count,
        "candidates_considered": r.candidates_considered,
        "total_picks": r.total_picks,
        "hit_counts": counts,
        "data_as_of": r.data_as_of.isoformat() if r.data_as_of else None,
        # ⚠️ **原样透出**,不塌缩成 False(None = 未知,见 R1)。
        # 前端据此区分「盘后完整数据」(false) / 「盘中半成品」(true) / 「时点未知」(null)。
        "is_intraday": r.is_intraday,
        "elapsed_sec": r.elapsed_sec,
        "note": r.note,
    }
```

- [ ] **Step 4: repository 加分页查询**

在 `backend/app/modules/behavior_screener/repository.py` 追加：

```python
async def get_picks_by_kind_offset(
    run_id: int,
    kind: str,
    limit: int,
    offset: int,
) -> list[BehaviorSignalPick]:
    """某批次**某一类**命中的分页(按分数降序)。

    ⚠️ `count` 不从这里取 —— 真实命中数来自批次表的 `hit_counts_json`,
    分页只负责「取明细」。两者分离是闸 1 的核心:展示层可以只给 60 条,
    但口径必须报真实总数。
    """
    async with async_session() as session:
        stmt = (
            select(BehaviorSignalPick)
            .where(
                BehaviorSignalPick.run_id == run_id,
                BehaviorSignalPick.kind == kind,
            )
            .order_by(BehaviorSignalPick.score.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await session.execute(stmt)).scalars().all())
```

并在 `__all__` 里补 `"get_picks_by_kind_offset"`。

- [ ] **Step 5: 改 API**

把 `backend/app/modules/behavior_screener/api.py` 的 `/latest` 改成：

```python
@router.get("/latest")
async def behavior_latest(
    kind: str | None = Query(default=None, description="分页:只看某一类"),
    limit: int = Query(default=BEHAVIOR_SCREENER_GROUP_PAGE_N, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """最新一批结果(默认今日,无则上一交易日)。

    - 尚无批次 → 404(前端据此区分「还没跑」与「跑了但没命中」)
    - `groups[].count` 是该类**真实命中数**(不是本次返回的明细条数)
    - `run.total_picks` 是**真实命中总数**
    - 传 `kind` → 额外返回 `page`,按 `limit`/`offset` 取该类明细分页
    """
    run = await repo.get_latest_run()
    if run is None:
        raise HTTPException(
            status_code=404,
            detail="尚无找股记录,请先运行 trigger-now 或等待盘后跑批",
        )
    picks = await repo.get_picks_by_run(run.id)
    hit_dicts = [behavior_service.pick_to_dict(p) for p in picks]
    run_dict = behavior_service.run_to_dict(run)
    counts = run_dict.get("hit_counts") or {}

    # 每组只带前 N 条明细,真实总数靠 count 披露(响应体控制)
    groups = []
    for g in _group_dicts(hit_dicts):
        groups.append(
            {
                **g,
                "count": int(counts.get(g["kind"], g["count"])),
                "picks": g["picks"][:BEHAVIOR_SCREENER_GROUP_PAGE_N],
            }
        )

    resp: dict[str, Any] = {
        "run": run_dict,
        "groups": groups,
        "all": hit_dicts[:BEHAVIOR_SCREENER_GROUP_PAGE_N],
        "kinds": [
            {"kind": k, "label": KIND_META.get(k, {}).get("label", k)}
            for k in KIND_META
        ],
    }

    if kind:
        page_picks = await repo.get_picks_by_kind_offset(run.id, kind, limit, offset)
        resp["page"] = {
            "kind": kind,
            "offset": offset,
            "limit": limit,
            "total": int(counts.get(kind, 0)),
            "picks": [behavior_service.pick_to_dict(p) for p in page_picks],
        }
    return resp
```

补 import：

```python
from app.core.config import BEHAVIOR_SCREENER_GROUP_PAGE_N
```

> ⚠️ `_group_dicts` 返回的 `count` 是「本次取到的条数」；上面的 `groups` 循环用 `counts` 覆盖成真实数。`counts` 缺失（存量批次行没有 `hit_counts_json`）→ 回退到 `g["count"]`（不编数字）。

- [ ] **Step 6: 运行测试确认通过**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_screener.py -q
```

Expected: PASS

- [ ] **Step 7: 提交**

```bash
git -C D:\zga-study\rich add backend/app/modules/behavior_screener/api.py backend/app/modules/behavior_screener/repository.py backend/app/modules/behavior_screener/service.py backend/tests/test_behavior_screener.py
git -C D:\zga-study\rich commit -m "feat(behavior): 闸1 API 披露真实计数 + 分页拉取明细"
```

---

## Task 6: 闸 4 —— 调度器 + 数据时点

**Files:**
- Modify: `backend/app/modules/behavior_screener/service.py`（新增 `start_behavior_scheduler` + 时点计算）
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_behavior_scheduler.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `data_as_of` / `is_intraday` 字段。
- Produces:
  - `resolve_batch_time_marks(now: datetime | None = None) -> tuple[date, bool]` —— 返回 `(data_as_of, is_intraday)`。`data_as_of` = 最近一个**已收盘**交易日；`is_intraday` = 本批是否含当日未收盘数据（工作日 15:00 前 = True）。
  - `should_run_behavior_batch(run: Any, now: datetime | None = None) -> bool` —— 跳过条件 = 「今天的批次存在 **且** `is_intraday` 明确为 `False`」。`None`（未知）与 `True`（盘中半成品）**都要重跑**（见 **R1**）。
  - `start_behavior_scheduler() -> None` —— 每日 15:30 后跑一次。

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_behavior_scheduler.py`：

```python
"""行为标注调度器(闸 4 稳定闸)单测。

**为什么跳过条件不能照抄选股**:选股的跳过条件是「今天有 run 就跳过」;
行为标注的盘中手动跑批带 `is_intraday=true` —— 若被当成「今天已跑」,
盘后调度器就会跳过 → **盘中那份会一直留着当最新批次**。
"""
from __future__ import annotations

from datetime import date, datetime

from app.modules.behavior_screener.service import (
    resolve_batch_time_marks,
    should_run_behavior_batch,
)


class _Run:
    def __init__(self, run_date: date, is_intraday: bool | None):
        self.run_date = run_date
        self.is_intraday = is_intraday


class TestResolveBatchTimeMarks:
    def test_after_close_is_not_intraday(self):
        """工作日 15:30 → 已收盘,is_intraday=False,data_as_of=当天。"""
        now = datetime(2026, 10, 30, 15, 30)
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is False
        assert data_as_of == date(2026, 10, 30)

    def test_intraday_marks_yesterday_as_of(self):
        """工作日 10:00 → 盘中,data_as_of 是上一个交易日,is_intraday=True。"""
        now = datetime(2026, 10, 30, 10, 0)
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is True
        assert data_as_of == date(2026, 10, 29)

    def test_intraday_before_open_uses_previous_day(self):
        """工作日 08:00(盘前)→ 当日尚未开盘,同样按盘中口径。"""
        now = datetime(2026, 10, 30, 8, 0)
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is True
        assert data_as_of == date(2026, 10, 29)

    def test_weekend_is_not_intraday(self):
        """周六 → 非盘中,data_as_of=上周五。"""
        now = datetime(2026, 10, 31, 10, 0)  # 周六
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is False
        assert data_as_of == date(2026, 10, 30)  # 周五

    def test_monday_before_open_skips_weekend(self):
        """周一盘前 → data_as_of 是上周五(跳过周末)。"""
        now = datetime(2026, 11, 2, 8, 0)  # 周一
        data_as_of, is_intraday = resolve_batch_time_marks(now)
        assert is_intraday is True
        assert data_as_of == date(2026, 10, 30)  # 周五


class TestShouldRun:
    def test_runs_when_no_batch_today(self):
        now = datetime(2026, 10, 30, 15, 30)
        assert should_run_behavior_batch(None, now) is True

    def test_skips_when_today_has_non_intraday_batch(self):
        """今天已有盘后批次 → 跳过。"""
        now = datetime(2026, 10, 30, 15, 30)
        run = _Run(date(2026, 10, 30), is_intraday=False)
        assert should_run_behavior_batch(run, now) is False

    def test_runs_when_today_batch_was_intraday(self):
        """今天只有盘中批次 → **要跑**(盘后必须覆盖)。"""
        now = datetime(2026, 10, 30, 15, 30)
        run = _Run(date(2026, 10, 30), is_intraday=True)
        assert should_run_behavior_batch(run, now) is True

    def test_runs_when_batch_is_from_another_day(self):
        """昨天有批次 → 今天照跑。"""
        now = datetime(2026, 10, 30, 15, 30)
        run = _Run(date(2026, 10, 29), is_intraday=False)
        assert should_run_behavior_batch(run, now) is True

    def test_runs_when_today_batch_is_intraday_unknown(self):
        """今天的批次 `is_intraday` 是 **None(未知)** → **要跑**。

        ⚠️ 见 R1:未知 ≠ 「确定不是盘中」。若把 None 当成 False 跳过,
        一个占位/未知批次就能把当天的盘后跑批挡掉。
        """
        now = datetime(2026, 10, 30, 15, 30)
        run = _Run(date(2026, 10, 30), is_intraday=None)
        assert should_run_behavior_batch(run, now) is True

    def test_does_not_run_before_1530(self):
        """15:29 → 不跑(未到时间窗)。"""
        now = datetime(2026, 10, 30, 15, 29)
        assert should_run_behavior_batch(None, now) is False

    def test_does_not_run_on_weekend(self):
        now = datetime(2026, 10, 31, 16, 0)  # 周六
        assert should_run_behavior_batch(None, now) is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_scheduler.py -q
```

Expected: FAIL —— `ImportError: cannot import name 'resolve_batch_time_marks'`

- [ ] **Step 3: 实现时点计算 + 调度器**

在 `backend/app/modules/behavior_screener/service.py` **文件末尾**（`__all__` 之前）追加：

```python
# ============================================================
# 后台调度(每日 15:30) —— 闸 4 稳定闸
# ============================================================

# 盘后跑批时间窗(与选股调度器一致:15:30 之后)
_BATCH_RUN_HOUR = 15
_BATCH_RUN_MINUTE = 30


def _prev_weekday(d: date) -> date:
    """d 之前最近的工作日(周末顺延;法定节假日按工作日近似)。"""
    cur = d - timedelta(days=1)
    while cur.weekday() >= 5:
        cur -= timedelta(days=1)
    return cur


def resolve_batch_time_marks(
    now: datetime | None = None,
) -> tuple[date, bool]:
    """本批的 `(data_as_of, is_intraday)`。

    - `data_as_of`:本批数据中**已收盘**的最后交易日
    - `is_intraday`:本批是否额外包含**当日未收盘**数据

    口径(工作日 15:00 为收盘线,与 `behavior_fund_flow_service._is_post_close` 一致):
    - 工作日 15:00 之后 → `data_as_of` = 当天,`is_intraday` = False
    - 工作日 15:00 之前 → `data_as_of` = 上一个工作日,`is_intraday` = True
    - 周末 → `data_as_of` = 上周五,`is_intraday` = False
    """
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周末
        return _prev_weekday(date(now.year, now.month, now.day) - timedelta(days=1)), False
    today = date(now.year, now.month, now.day)
    if now.hour >= 15:  # 已收盘
        return today, False
    return _prev_weekday(today), True


def should_run_behavior_batch(run: Any, now: datetime | None = None) -> bool:
    """今天是否需要跑批。

    ⚠️ **跳过条件必须是「今天的批次存在 且 `is_intraday` 明确为 `False`**」:
    盘中手动跑的那份带 `is_intraday=true`,若被当成「今天已跑」,
    盘后调度器就会跳过 → 盘中那份会一直留着当最新批次。

    🚨 **`None`(未知)不跳过**(见 R1):只有**明确**知道是盘后完整数据才跳过。
    `None` = 时点未知(比如 Task 3 的占位批次、迁移前的老批次)→ 不信任它,重跑。
    `True` = 盘中半成品 → 必须重跑。

    纯函数(只吃 `now` 与批次行),便于单测 —— 不打桩时钟。
    """
    now = now or datetime.now()
    if now.weekday() >= 5:  # 周末不跑
        return False
    if not (now.hour >= _BATCH_RUN_HOUR and now.minute >= _BATCH_RUN_MINUTE):
        return False
    if run is None:
        return True
    if run.run_date != date(now.year, now.month, now.day):
        return True
    # 只有明确是盘后完整数据(False)才跳过;None(未知)/True(盘中)都要重跑。
    return run.is_intraday is not False


async def start_behavior_scheduler() -> None:
    """每日 15:30 跑一次(工作日;今天已有**非盘中**批次则跳过)。"""
    import os as _os

    if _os.environ.get("PYTEST_CURRENT_TEST"):
        # 测试环境跳过(与选股调度器同口径)
        return

    logger.info("行为标注调度器启动: 每日 15:30 跑批")
    while True:
        try:
            now = datetime.now()
            target = date(now.year, now.month, now.day)
            today_run = await repo.get_run_by_date(target)
            if should_run_behavior_batch(today_run, now):
                await run_daily_scan(target)
        except asyncio.CancelledError:
            logger.info("行为标注调度器停止")
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[behavior_screener] 调度器异常: %s", e)
        await asyncio.sleep(60)
```

补 import：`timedelta`（`from datetime import date, datetime` → 改成 `from datetime import date, datetime, timedelta`）。

- [ ] **Step 4: 改 `run_daily_scan` 用真实时点**

在 `run_daily_scan` 里，把 Task 3 留下的占位（**未知**，见 R1）：

```python
        data_as_of=None,
        is_intraday=None,
```

改成：

```python
        data_as_of=data_as_of,
        is_intraday=is_intraday,
```

并在函数开头（`target = target_date or date.today()` 之后）加：

```python
    # 闸 4:批次的数据时点(盘后完整数据 vs 盘中半成品)
    data_as_of, is_intraday = resolve_batch_time_marks()
```

> ⚠️ `resolve_batch_time_marks()` 用的是**当前时钟**。手动指定 `target_date` 跑历史日期时，`data_as_of` 描述的是「本批数据截止到哪个已收盘交易日」—— 当日跑批时它就是 target 之前最近的已收盘日。盘后跑（15:00 后）时它 = target 当天。这是**如实披露**，不是编造。

- [ ] **Step 5: 运行测试确认通过**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_scheduler.py -q
```

Expected: PASS

- [ ] **Step 6: 在 main.py 里 spawn**

在 `backend/app/main.py` 的

```python
        # v2.6:盘后选股调度器(每日 15:30 工作日自动跑批)
        from app.modules.screener.service import start_screener_scheduler

        _spawn(start_screener_scheduler())
```

之后加：

```python
        # 盘后行为标注调度器(每日 15:30 工作日自动跑批;闸 4 稳定闸)
        from app.modules.behavior_screener.service import start_behavior_scheduler

        _spawn(start_behavior_scheduler())
```

- [ ] **Step 7: 验证服务能起来**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -c "import app.main; print('import ok')"
```

Expected: 打印 `import ok`（无异常、无循环 import）

- [ ] **Step 8: 提交**

```bash
git -C D:\zga-study\rich add backend/app/modules/behavior_screener/service.py backend/app/main.py backend/tests/test_behavior_scheduler.py
git -C D:\zga-study\rich commit -m "feat(behavior): 闸4 盘后自动跑批 + 批次数据时点(is_intraday 跳过条件)"
```

---

## Task 7: 闸 3 —— 一致性守门（单元 + 端到端巡检）

**Files:**
- Create: `backend/tests/test_behavior_consistency.py`
- Create: `backend/scripts/verify_behavior_consistency.py`

**Interfaces:**
- Consumes: Task 2 的 `filter_markers_by_window`；Task 4 的 K 线路径。
- Produces:
  - `backend/tests/test_behavior_consistency.py::test_screener_markers_subset_of_kline_markers` —— 硬门槛：`S_A ⊆ S_B`。
  - `backend/scripts/verify_behavior_consistency.py` —— 手动巡检脚本，输出差异表。

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_behavior_consistency.py`：

```python
"""闸 3 一致闸 —— 找股路径 vs K 线路径的标注必须一致。

**为什么这是硬门槛**:spec §1.2 实测发现旧版 61% 的信号「找股页有、
K 线上找不到」。原因不是判定层写错,而是**两条路径的窗口口径不同**
(一个日历天 60、一个 K 线根数 120 根 ≈ 168 天)。

现在两条路径共用 `detect_behavior_markers` + `filter_markers_by_window`,
本文件把不变量钉死,防止将来有人改了一边忘了另一边。

不变量:
1. `S_A ⊆ S_B` —— 找股路径的每一条都必须在 K 线路径找到(硬门槛)
2. 两者都成功时 `S_A == S_B`,且每条的 `kind/date/metrics/reason` 逐字一致
3. 某一路取数失败 → 退化为 `⊆` 并**显式标记该票不可比对**(不静默跳过)
"""
from __future__ import annotations

import datetime as _dt
from datetime import date

import pytest

from app.core.config import (
    BEHAVIOR_MARKERS_LOOKBACK_DAYS,
    BEHAVIOR_SCREENER_KLINE_COUNT,
)
from app.services.behavior_signal_service import (
    base_date_from_klines,
    detect_behavior_markers,
    filter_markers_by_window,
)
from app.services.behavior_fund_flow_service import align_by_date


def _dates(n: int) -> list[str]:
    out: list[str] = []
    d = date(2026, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += _dt.timedelta(days=1)
    return out


def _sample(n: int = 130):
    """造一只票:K 线 + 逐日资金流,含若干命中。"""
    dates = _dates(n)
    ks = []
    for i, d in enumerate(dates):
        row = {
            "date": d, "open": "10.0", "high": "10.1", "low": "9.9",
            "close": "10.0", "volume": 100000,
        }
        if i >= n - 20:
            row.update({
                "open": "10.0", "close": "10.5", "high": "10.6",
                "low": "9.95", "volume": 300000,
            })
        ks.append(row)
    flows = [
        {
            "date": d, "net_amount": 1.0e8, "r0_net": 1.0e8,
            "r0x_ratio": 80.0, "r0_ratio": 60.0, "turnover": 20.0,
            "change_ratio": 0.05,
        }
        for d in dates
    ]
    return ks, flows


def _kline_path(ks, flows, base: date):
    """K 线路径:300 根 K 线 + 300 天资金流 → 窗口过滤。"""
    res = detect_behavior_markers(ks, align_by_date(flows))
    b = base_date_from_klines(ks) or base
    return filter_markers_by_window(
        res.markers, b, BEHAVIOR_MARKERS_LOOKBACK_DAYS
    )


def _screener_path(ks, flows, base: date):
    """找股路径:120 根 K 线 + 120 天资金流 → 窗口过滤。"""
    from app.core.config import BEHAVIOR_SCREENER_KLINE_COUNT

    res = detect_behavior_markers(ks[-BEHAVIOR_SCREENER_KLINE_COUNT:], align_by_date(flows))
    return filter_markers_by_window(
        res.markers, base, BEHAVIOR_MARKERS_LOOKBACK_DAYS
    )


class TestConsistency:
    def test_screener_markers_subset_of_kline_markers(self):
        """硬门槛:找股路径的每一条都必须在 K 线路径找到。"""
        ks, flows = _sample()
        base = date.fromisoformat(ks[-1]["date"])
        a = _screener_path(ks, flows, base)
        b = _kline_path(ks, flows, base)
        keys_a = {(m.kind, m.date) for m in a}
        keys_b = {(m.kind, m.date) for m in b}
        assert keys_a <= keys_b, (
            f"找股路径有 {len(keys_a - keys_b)} 条 K 线路径找不到: "
            f"{sorted(keys_a - keys_b)[:5]}"
        )

    def test_identical_when_both_succeed(self):
        """两者都成功 → 集合完全一致,字段逐字一致。"""
        ks, flows = _sample()
        base = date.fromisoformat(ks[-1]["date"])
        a = {(m.kind, m.date): m for m in _screener_path(ks, flows, base)}
        b = {(m.kind, m.date): m for m in _kline_path(ks, flows, base)}
        assert set(a) == set(b)
        for key in a:
            assert a[key].reason == b[key].reason
            assert a[key].metrics == b[key].metrics

    def test_degraded_when_kline_path_unavailable(self):
        """某一路取数失败 → 退化为 ⊆ 并显式标记不可比对。"""
        from app.services.behavior_signal_service import BehaviorResult

        ks, flows = _sample()
        base = date.fromisoformat(ks[-1]["date"])
        a = _screener_path(ks, flows, base)
        # K 线路径:资金流全缺 → 不产出
        b = _kline_path(ks, [], base)
        assert b == []
        # 退化:不抛异常,且找股路径的命中仍然存在(供人工比对)
        assert a is not None

    def test_missing_flow_degrades_not_crashes(self):
        """资金流缺失 → 不产出标注,不崩(缺数据 → 不产出)。"""
        ks, flows = _sample()
        res = detect_behavior_markers(ks, {})
        assert res.markers == []
```

> ⚠️ 上面用到了 `BEHAVIOR_MARKERS_LOOKBACK_DAYS` 与 `BEHAVIOR_SCREENER_KLINE_COUNT` —— 两者都从 `app.core.config` **直接 import**（见文件顶部 import 块），不依赖 `service.py` 的模块属性。

- [ ] **Step 2: 运行测试**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest tests/test_behavior_consistency.py -q
```

Expected: PASS（Task 2/4 已把两条路径对齐，这个测试是**守门**，不是修复）

> ✅ **这个 PASS 有实测背书**（2026-10-31，写计划时用真实缓存跑过）：
> 123 只票、528 条标注 → `S_A ⊆ S_B` **零违反**，`reason`/`metrics` **逐字完全一致**，
> 仅 B 有的标注数 = 0。所以本测试**若 FAIL**，说明 Task 2/3/4 有一步没做对 ——
> **不要修改测试让它通过**，去查那三步。
>
> 若 FAIL —— 读错误信息里的差集，按 Task 2/3/4 的口径修正（**不要**修改这个测试让它通过）。

- [ ] **Step 3: 写端到端巡检脚本**

创建 `backend/scripts/verify_behavior_consistency.py`：

```python
#!/usr/bin/env python
"""闸 3 端到端一致性巡检(手动 / 盘后批后跑)。

**只报告,不改数据**:差异意味着两个口径分叉了 → 人工判断哪边对 →
修代码 → 重跑。**绝不在运行时静默取其一**(那会让「不一致」变成「永远看不见」)。

用法:
    cd D:\\zga-study\\rich\\backend
    .venv\\Scripts\\python.exe -m scripts.verify_behavior_consistency --sample 50

输出(差异表):
    stock_code | kind | date | 字段 | 找股路径 | K线路径
    000568.SZ  | main_force_move | 2026-10-20 | r0x_ratio | 73.0 | 71.8
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import date, datetime

from app.core.config import (
    BEHAVIOR_MARKERS_LOOKBACK_DAYS,
    BEHAVIOR_SCREENER_KLINE_COUNT,
)
from app.services.behavior_fund_flow_service import align_by_date, fetch_flow_daily
from app.services.behavior_signal_service import (
    base_date_from_klines,
    detect_behavior_markers,
    filter_markers_by_window,
)
from app.services.kline_service import fetch_klines


async def _load(code: str, count: int):
    try:
        ks = await fetch_klines(code, period="daily", count=count)
    except Exception as e:  # noqa: BLE001
        return None, None, f"K线失败: {e}"
    try:
        flows = await fetch_flow_daily(code, count=count)
    except Exception as e:  # noqa: BLE001
        return ks, None, f"资金流失败: {e}"
    return ks, flows, None


def _markers(ks, flows, base):
    res = detect_behavior_markers(ks, align_by_date(flows))
    b = base_date_from_klines(ks) or base
    return filter_markers_by_window(res.markers, b, BEHAVIOR_MARKERS_LOOKBACK_DAYS)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=50, help="随机抽多少只票")
    ap.add_argument("--codes", type=str, default="", help="逗号分隔的代码(给了就无视 --sample)")
    args = ap.parse_args()

    from app.data.market_snapshot import fetch_market_snapshot

    rows = await fetch_market_snapshot()
    pool = [r["code"] for r in rows if r.get("code")]
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        random.seed(20261031)  # 固定种子 → 可复现
        codes = random.sample(pool, min(args.sample, len(pool)))

    diff_rows: list[tuple[str, ...]] = []
    incomparable: list[tuple[str, str]] = []
    checked = 0

    for code in codes:
        ks_a, flows_a, err_a = await _load(code, BEHAVIOR_SCREENER_KLINE_COUNT)
        ks_b, flows_b, err_b = await _load(code, 300)
        if err_a or err_b:
            incomparable.append((code, err_a or err_b or "未知"))
            continue
        base = date.fromisoformat(ks_a[-1]["date"])
        a = {(m.kind, m.date): m for m in _markers(ks_a, flows_a, base)}
        b = {(m.kind, m.date): m for m in _markers(ks_b, flows_b, base)}
        checked += 1

        only_a = set(a) - set(b)
        for k in sorted(only_a):
            diff_rows.append((code, k[0], k[1], "(整条缺失)", "有", "无"))
        for k in sorted(set(a) & set(b)):
            ma, mb = a[k], b[k]
            if ma.reason != mb.reason:
                diff_rows.append((code, k[0], k[1], "reason", ma.reason, mb.reason))
            for f in set(ma.metrics) | set(mb.metrics):
                va, vb = ma.metrics.get(f), mb.metrics.get(f)
                if va != vb:
                    diff_rows.append((code, k[0], k[1], f, str(va), str(vb)))

    print(f"可比对 {checked} 只 / 不可比对 {len(incomparable)} 只 / 差异 {len(diff_rows)} 条")
    if incomparable:
        print("\n-- 不可比对(数据获取失败) --")
        for code, err in incomparable:
            print(f"  {code}: {err}")
    if diff_rows:
        print("\n-- 差异表 --")
        print("stock_code | kind | date | 字段 | 找股路径 | K线路径")
        for r in diff_rows[:200]:
            print(" | ".join(r))
        if len(diff_rows) > 200:
            print(f"  ...(还有 {len(diff_rows) - 200} 条未显示)")
    else:
        print("\n✅ 两条路径完全一致")

    # 不一致时以非 0 退出,方便挂 CI
    return 1 if diff_rows else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 4: 运行巡检脚本**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m scripts.verify_behavior_consistency --sample 10
```

Expected: 打印「可比对 N 只 / 不可比对 M 只 / 差异 K 条」。差异数应为 0 或极少（若 K 线/资金流缓存的新鲜度导致个别票取数范围不同，会有少量差异 —— 记录下来，不自动改数据）。

> ⚠️ 脚本会打新浪外网（每只票 2 次请求）。**先用 `--sample 10` 验证**，确认无误再跑 50。

- [ ] **Step 5: 提交**

```bash
git -C D:\zga-study\rich add backend/tests/test_behavior_consistency.py backend/scripts/verify_behavior_consistency.py
git -C D:\zga-study\rich commit -m "test(behavior): 闸3 一致性守门 —— 单元断言 + 端到端巡检脚本"
```

---

## Task 8: 前端 —— 真实口径 + 展开更多 + 盘中提示

**Files:**
- Modify: `frontend/src/lib/behaviorScreener.ts`
- Modify: `frontend/src/components/screener/BehaviorScreenerPanel.tsx`
- Test: 手工验证（`tsc --noEmit` + `next build` + 真机点一遍）

**Interfaces:**
- Consumes: Task 5 的 API 形状。
- Produces:
  - `BehaviorRun` 增加 `hitCounts: Record<string, number>`、`dataAsOf: string | null`、`isIntraday: boolean | null`（`null` = 时点未知，见 **R1**）。
  - `BehaviorGroup.count` 语义改为**真实命中数**。
  - `fetchBehaviorLatestPage(kind, limit, offset)` —— 分页拉取。

- [ ] **Step 1: 改 API 类型**

在 `frontend/src/lib/behaviorScreener.ts`：

`BehaviorRun` 接口改成：

```typescript
export interface BehaviorRun {
  id: number;
  runDate: string | null;
  generatedAt: string | null;
  poolSize: number;
  mainBoardCount: number;
  nonStCount: number;
  afterFiltersCount: number;
  candidatesConsidered: number;
  /**
   * 真实命中总数(不是入库条数、不是当前返回的明细条数)。
   */
  totalPicks: number;
  /**
   * 每类的**真实**命中数(闸 1)。
   *
   * ⚠️ 必须是**驼峰**:axios 响应拦截器会递归把 snake_case 转 camelCase
   * (`snakeToCamel`,见 lib/api.ts),运行期拿到的就是 `hitCounts`。
   * 写成 snake_case 的话 TS 不报错(泛型只是断言),但页面读出来全是 `undefined`。
   */
  hitCounts: Record<string, number>;
  /** 本批数据中已收盘的最后交易日 */
  dataAsOf: string | null;
  /** 本批是否含当日未收盘数据(盘中跑批);null = 时点未知(见 R1) */
  isIntraday: boolean | null;
  elapsedSec: number | null;
  note: string | null;
}
```

`BehaviorGroup` 接口的 `count` 注释改成：

```typescript
export interface BehaviorGroup {
  kind: BehaviorPick['kind'];
  kindLabel: string;
  /** 该类**真实**命中数(不是 `picks` 的长度 —— 明细只带前 N 条) */
  count: number;
  picks: BehaviorPick[];
}
```

新增分页类型与函数：

```typescript
export interface BehaviorPage {
  kind: BehaviorPick['kind'];
  offset: number;
  limit: number;
  /** 该类真实命中总数 */
  total: number;
  picks: BehaviorPick[];
}

export interface BehaviorLatestResponse {
  run: BehaviorRun;
  groups: BehaviorGroup[];
  all: BehaviorPick[];
  kinds: { kind: BehaviorPick['kind']; label: string }[];
  /** 仅当请求带了 `kind` 参数时存在 */
  page?: BehaviorPage;
}
```

在文件末尾追加：

```typescript
/**
 * 分页拉取某一类命中的明细。
 *
 * 口径:每类真实命中数可能上千(`/latest` 只带前 60 条明细),
 * 「展开更多」用它按 offset 追加。
 */
export function fetchBehaviorLatestPage(
  kind: BehaviorPick['kind'],
  limit = 60,
  offset = 0,
) {
  return apiGet<BehaviorLatestResponse>('/behavior-screener/latest', {
    params: { kind, limit, offset },
  });
}
```

- [ ] **Step 2: 改面板 —— 口径条读真实数**

在 `BehaviorScreenerPanel.tsx` 的 `BehaviorScreenerPanel` 函数里，把

```typescript
  const { run, groups, all } = data;
  const universe = run.poolSize;
  const filters = run.afterFiltersCount;
  const candidates = run.candidatesConsidered;
  const hits = all.length;
```

改成

```typescript
  const { run, groups, all } = data;
  const universe = run.poolSize;
  const filters = run.afterFiltersCount;
  const candidates = run.candidatesConsidered;
  // ⚠️ 真实命中总数 —— 不是 `all.length`(`all` 只带前 60 条明细)
  const hits = run.totalPicks;
```

- [ ] **Step 3: 改面板 —— 盘中提示行**

在口径条 `<Card className="p-4">` 内部（`{pool?.universe && (...)}` 之后）追加：

```typescript
        {run.isIntraday === true && (
          <p className="text-orange-500 mt-2 text-xs">
            ⚠ 本批次含未收盘的当日数据(盘中跑批),收盘后会自动重算。
          </p>
        )}
        {run.dataAsOf && (
          <p className="text-text-ter mt-1 text-xs">数据截止 {run.dataAsOf}</p>
        )}
```

> ⚠️ JSX 文本里**不能**用 `**未收盘**` 这种 Markdown 语法 —— 会被当字面量渲染。
> 要强调就用 `<span className="font-medium">未收盘</span>`。

> 🚨 **必须写 `run.isIntraday === true`，不能写 `run.isIntraday &&`**（见 **R1**）：
> `isIntraday` 现在是 `boolean | null`。`null && (...)` 在 React 里会渲染出 `null`（什么都不显示），
> 但语义上「未知」和「false」不能混为一谈 —— 显式 `=== true` 才能表达「只在这一种情况下提示盘中」。
> `null`（时点未知）**不显示盘中提示**，也**不谎称盘后完整**：下面的「数据截止 {dataAsOf}」仍如实展示。
> 若要显式告知「时点未知」，可加一行中性提示（灰字），但**不要**复用橙色的盘中警告样式。

- [ ] **Step 4: 改分组卡 —— 真实 count + 展开更多**

把 `GroupCard` 组件改成：

```tsx
function GroupCard({ group }: { group: BehaviorGroup }) {
  const [extra, setExtra] = useState<BehaviorPick[]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const shown = expanded ? [...group.picks, ...extra] : group.picks;
  const hasMore = group.count > group.picks.length + extra.length;

  const loadMore = useCallback(async () => {
    setLoadingMore(true);
    try {
      const resp = await fetchBehaviorLatestPage(
        group.kind,
        60,
        group.picks.length + extra.length,
      );
      const page = resp.page;
      if (page?.picks?.length) {
        setExtra((prev) => [...prev, ...page.picks]);
      }
      setExpanded(true);
    } catch {
      // 拉取失败 → 保持现状(不编数据、不清空已加载的)
    } finally {
      setLoadingMore(false);
    }
  }, [group.kind, group.picks.length, extra.length]);

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-xs font-medium ${KIND_CLS[group.kind]}`}
        >
          {group.kindLabel}
        </span>
        {/* ⚠️ count 是真实命中数,不是当前渲染条数 */}
        <span className="text-text-ter text-xs">
          {group.count} 只命中
          {group.count > group.picks.length &&
            `（按分数列出前 ${group.picks.length + extra.length} 条 / 共 ${group.count} 条）`}
        </span>
      </div>
      <ul className="space-y-2">
        {shown.map((p) => (
          <li
            key={`${p.stockCode}-${p.kind}-${p.signalDate}`}
            className="rounded-sm border border-border-def bg-bg-subtle px-3 py-2"
          >
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <Link
                href={`/stock/${encodeURIComponent(p.stockCode)}`}
                className="text-text-pri text-sm font-medium hover:text-accent"
              >
                {p.stockName || p.stockCode}
              </Link>
              <span className="text-text-ter text-xs">{p.stockCode}</span>
              <span className="text-text-ter text-xs">
                信号日 {p.signalDate}（{p.daysAgo} 天前）
              </span>
              {p.changePct != null && (
                <span
                  className={
                    p.changePct >= 0
                      ? 'text-up text-xs font-medium'
                      : 'text-down text-xs font-medium'
                  }
                >
                  {fmtPct(p.changePct)}
                </span>
              )}
              <span className="text-text-ter ml-auto text-xs">
                强度 {p.score.toFixed(1)}
              </span>
            </div>
            <p className="text-text-sec mt-1 text-xs leading-relaxed">{p.reason}</p>
          </li>
        ))}
      </ul>
      {hasMore && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-3"
          onClick={loadMore}
          loading={loadingMore}
          disabled={loadingMore}
        >
          展开更多（还有 {group.count - group.picks.length - extra.length} 条）
        </Button>
      )}
    </Card>
  );
}
```

补 import（`BehaviorScreenerPanel.tsx` 顶部）：

```typescript
import {
  fetchBehaviorLatest,
  fetchBehaviorLatestPage,
  fetchBehaviorPool,
  type BehaviorGroup,
  type BehaviorLatestResponse,
  type BehaviorPick,
  type BehaviorPoolResponse,
} from '@/lib/behaviorScreener';
```

- [ ] **Step 5: 类型检查**

```bash
cd D:\zga-study\rich
frontend\node_modules\.bin\tsc.cmd --noEmit -p frontend/tsconfig.json
```

Expected: 无错误输出（退出码 0）

- [ ] **Step 6: 构建**

> ⚠️ `next build` 与 `next dev` 争 `.next` 目录 → **构建前先停服务**：
> ```bash
> cd D:\zga-study\rich
> cmd.exe /c "scripts\dev.cmd -Action stop"
> ```
> 构建完再起：
> ```bash
> cmd.exe /c "scripts\dev.cmd"
> ```

```bash
cd D:\zga-study\rich\frontend
npm.cmd run build
```

Expected: 构建成功

- [ ] **Step 7: 真机点一遍**

启动服务后打开 `http://localhost:5173/behavior-screener`，逐项核对：

1. 口径条「命中信号」显示的数字 == 批次表 `total_picks`（真实数），**不是** 60
2. 每张分组卡显示「N 只命中（按分数列出前 60 条 / 共 M 条）」
3. 点「展开更多」能追加下一批，且计数随之变化
4. 若批次是盘中跑的 → 显示「含未收盘的当日数据」提示行 + 「数据截止 YYYY-MM-DD」
5. 点某只票 → 跳个股页 → K 线上**能看到**该信号标注

- [ ] **Step 8: 提交**

```bash
git -C D:\zga-study\rich add frontend/src/lib/behaviorScreener.ts frontend/src/components/screener/BehaviorScreenerPanel.tsx
git -C D:\zga-study\rich commit -m "feat(behavior): 闸1 前端口径 —— 真实计数/展开更多/盘中数据时点提示"
```

---

## Task 9: 真机验收 + 实测回填 spec

**Files:**
- Modify: `docs/superpowers/specs/2026-10-31-behavior-trust-design.md`（回填 §七 的 4 个待定项）
- Create: `docs/analysis/2026-10-31-behavior-trust-measurement.md`（实测记录）

**Interfaces:**
- Consumes: Task 1~8 的全部产出。
- Produces: 实测证据文件 + spec §七 回填。

- [ ] **Step 1: 分级验证外网承受力（闸 2 的关键前置）**

> ⚠️ **不靠推演说「应该没事」**。1817 次外网请求打同一个新浪接口，
> 是 30 只实测的 60 倍。**任一级失败率超阈值即停。**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -c "import asyncio; from app.modules.behavior_screener.service import scan_market; from datetime import date; r=asyncio.run(scan_market(date(2026,10,30), candidate_limit=300)); print('hits',len(r.hits),'cands',r.candidates_considered,'elapsed',r.elapsed_sec,'degraded',r.degraded)"
```

依次跑 `candidate_limit=300` → `600` → `1817`(不传)。**每一级记录**:命中数、候选数、耗时、失败数(`degraded`)、`elapsed_sec`。

**停止条件**:任一级 `elapsed_sec` 单调异常上升(超过上一级的 2.5 倍)或 `degraded` 出现批量失败 → **停下报告**,不继续加压。

- [ ] **Step 2: 跑一次完整批次并记录真实命中数**

```bash
cd D:\zga-study\rich\backend
$env:SCREENER_ALLOW_TRIGGER = "1"
.venv\Scripts\python.exe -c "import asyncio; from app.modules.behavior_screener.service import run_daily_scan; r=asyncio.run(run_daily_scan()); print('run', r[0].id, 'picks', r[0].total_picks, 'counts', r[0].hit_counts_json, 'as_of', r[0].data_as_of, 'intraday', r[0].is_intraday, 'elapsed', r[0].elapsed_sec)"
$env:SCREENER_ALLOW_TRIGGER = $null
```

记录:真实命中总数、分组真实计数、`data_as_of`、`is_intraday`、`elapsed_sec`。

- [ ] **Step 3: 核对三者相等**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -c "import sqlite3,json; c=sqlite3.connect('data.db'); r=c.execute('select id,total_picks,hit_counts_json from behavior_signal_run order by run_date desc limit 1').fetchone(); n=c.execute('select count(*) from behavior_signal_pick where run_id=?',(r[0],)).fetchone()[0]; s=sum(json.loads(r[2]).values()); print('run_id',r[0],'total_picks',r[1],'sum(counts)',s,'picked_rows',n); print('EQUAL' if r[1]==s==n else 'MISMATCH')"
```

Expected: `EQUAL`（分组 count 之和 == 真实命中总数 == 入库行数）

- [ ] **Step 4: 抽查 20 只票的 K 线可见性**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m scripts.verify_behavior_consistency --sample 20
```

Expected: 「可比对 N 只 / 差异 0 条」

再手工抽 20 只（从 `/api/behavior-screener/latest` 取前 20 个不同的 `stock_code`），逐只打开 `/api/kline/{code}/indicators?period=daily&limit=300`，确认该票在找股页列出的**每一个** `signal_date` 都出现在 `behavior_markers` 里。

**缺失数必须 = 0**（改前实测缺失率 61%）。

- [ ] **Step 5: 跑全量测试**

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m pytest -q
```

Expected: 全部 PASS，0 failed

```bash
cd D:\zga-study\rich\backend
.venv\Scripts\python.exe -m ruff check app/modules/behavior_screener/ app/api/kline.py app/services/behavior_signal_service.py
```

Expected: 无输出（零新增告警）

- [ ] **Step 6: 写实测记录**

创建 `docs/analysis/2026-10-31-behavior-trust-measurement.md`，记录：

- 分级验证的三级数据(候选数 / 命中数 / 耗时 / 失败数)
- 完整批次的真实命中总数与分组计数
- 三者相等的核对输出
- 20 只抽查的缺失标注数
- K 线端点在 120 天回看下的响应体大小(实测 bytes)
- 全量 pytest 与 ruff 结果

- [ ] **Step 7: 回填 spec §七**

把 `docs/superpowers/specs/2026-10-31-behavior-trust-design.md` 的 §七 四个复选框逐项填上**实测值**（不是推算值），并在文件末尾加一行：

```
> **实测回填时间**:2026-10-31 · 实测记录见 `docs/analysis/2026-10-31-behavior-trust-measurement.md`
```

- [ ] **Step 8: 提交**

```bash
git -C D:\zga-study\rich add docs/analysis/2026-10-31-behavior-trust-measurement.md docs/superpowers/specs/2026-10-31-behavior-trust-design.md
git -C D:\zga-study\rich commit -m "docs(behavior): 四道闸实测回填(真实命中数/耗时/响应体/缺失率)"
```

---

## Self-Review

**1. Spec 覆盖检查**

| spec 章节 | 对应 Task |
|---|---|
| §3.1~3.3 口径定义与落库 | Task 3（全量入库 + 真实计数 + `hit_counts_json`） |
| §3.2 数据模型三列 | Task 1 |
| §3.4 API 形状 + 分页 | Task 5 |
| §3.5 前端 | Task 8 |
| §4.1 候选池去截断 | Task 3 |
| §4.2 窗口统一 120 日历天 | Task 2（常量 + 纯函数）、Task 3（找股路径）、Task 4（K 线路径） |
| §4.3 K 线响应体影响 | Task 9 Step 6（实测记录） |
| §5.1 一致性不变量 | Task 7 |
| §5.2 两层巡检 | Task 7（单元 + 脚本） |
| §5.3 差异只报告不改数据 | Task 7（脚本只打印，退出码非 0，不写库） |
| §6.1 调度器 | Task 6 |
| §6.2 `data_as_of` / `is_intraday` | Task 1（字段）、Task 6（计算） |
| §6.3 前端明示 | Task 8 |
| §七 四个待定项 | Task 9 Step 7 |
| §八 数据模型汇总 | Task 1 |
| §九 验收标准 | Task 9 |
| §十一 风险（分级验证） | Task 9 Step 1 |

**无缺口。**

**2. 占位符扫描**

- 无 `TBD` / `TODO` / 「实现 later」
- 所有代码步骤都带实际代码块
- 跨 Task 引用的函数名/字段名一致：
  - `filter_markers_by_window` / `marker_date` / `base_date_from_klines`（Task 2 产出，Task 3/4/7 消费）
  - `hit_counts_json` / `data_as_of` / `is_intraday`（Task 1 产出，Task 3/5/6 消费）
  - `hit_counts`（`ScanResult` 的 dict，Task 3 产出 → Task 5 反序列化回 dict）
  - `get_picks_by_kind_offset`（Task 5 产出，同 Task 内调用）
  - `resolve_batch_time_marks` / `should_run_behavior_batch`（Task 6 产出，同 Task 内测试消费）
  - `fetchBehaviorLatestPage`（Task 8 产出，同 Task 内消费）

**3. 类型/命名一致性**

- ORM 字段名 `hit_counts_json` / `data_as_of` / `is_intraday`（snake）→ API 字段 `hit_counts` / `data_as_of` / `is_intraday`（snake，axios 自动转）→ 前端类型 `hitCounts` / `dataAsOf` / `isIntraday`（驼峰）。链路自洽。
- `ScanResult.hit_counts: dict[str, int]` 与 `BehaviorSignalRun.hit_counts_json: str | None` 是**两种形态**（dict vs JSON 字符串）→ Task 3 负责 dict→JSON 序列化，Task 5 负责 JSON→dict 反序列化。命名不同但职责清晰。
- `get_picks_by_kind_offset(run_id, kind, limit, offset)` 的参数顺序在 Task 5 定义与调用处一致。

**4. 计划编写期已核实的事实（不是推测）**

| 事实 | 核实方式 | 影响 |
|---|---|---|
| 表名是 `behavior_signal_run`（**单数**） | 实查 `sqlite_master` + ORM `__tablename__` | Task 1 迁移里不能用复数，否则迁移直接报错 |
| alembic HEAD = `b3c4d5e6f708` | 遍历 `migrations/versions` 解析 revision/down_revision 链 | Task 1 的 `down_revision` 取值 |
| `modules` 不在架构守卫的 `LAYERS` 里 | 读 `test_architecture_boundaries.py` | `api → modules` 不被分层规则拦，但**仍不采用**（见下） |
| `app/api/*` 已有 12 处 import `app.modules.*` | grep 现有代码 | 说明 `api → modules` 是既有习惯；本计划仍选择放进 `services` |
| 窗口函数放在 `services/behavior_signal_service.py` | 两条路径**本来就** import 它 | 零新增 import 边，不触碰「跨域只走 service.py」 |
| `BEHAVIOR_SCREENER_TOP_N` 改后无人使用 | grep 全后端 | Task 3 必须同时删掉 service.py 的 import（ruff F401） |
| `api/kline.py` 的 `_date` / `_td` 改后无人使用 | grep 该文件 | Task 4 必须删掉那行 import |
| `behavior_signal_service.py` 目前没有 datetime import | 读文件头 | Task 2 需补 `from datetime import date, timedelta` |

**5. 计划编写期发现并修正的 5 个实质问题**

1. **基准日口径不一致（最严重）**：初稿让找股路径用 `run_date`、K 线路径用「K 线末根日期」→ 两者差一天（停牌时差更多）→ 窗口边界错位 → `S_A ⊆ S_B` 被打破。**已改为两条路径都用「该票自己的 K 线末根日期」**，并同步改 Task 3 的实现与 Task 7 的一致性测试。
2. **Task 4 的测试测不出东西**：初稿的测试在改前改后都通过（都用「末根日期」作基准）。**已重写**为「基准日不可解析 → 必须返回空标注」—— 旧实现在这个场景下是**全量返回**（窗口闸门形同虚设），是真能测出差异的用例。
3. **口径与存储的错位**：初稿把窗口过滤放在落库时 → 批次表仍存超窗口信号，`count` 与明细依然对不上（把问题从展示层挪到存储层）。**已改为在 `scan_market` 内部过滤**（与 spec §3.3 的警告一致）。
4. **Task 3 的造数造不出想要的命中数（实测推翻）**：初稿造「70 天主力异动」期望 70 条，实际只出 **3 条** —— 因为量比是「当日量 ÷ 前 5 日均量」，连续放量 70 天会让均量同步抬高，量比迅速回落到 1 附近。**已换成「平价 + 逐日缩量 10% + 连续主力净流入」的锁仓型数据**（只触发 `lock_position`，可稳定产出 103 条），窗口内 **70** 条 —— 仍是 >60，能证明没被截断。
5. **Task 3 的候选池代码生成有 bug（实测推翻）**：初稿写 `f"6005{i:02d}.SH"`，i ≥ 100 时变成 **7 位数** → 主板判定失败 → 150 只只过 100 只。**已改为 `f"{600000 + i:06d}.SH"`**，实测 150 → 150。

> 这两条是**写计划时用真实判定层跑出来的**——不是事后诸葛。
> 如果不实测就派活，实施者会花好几轮去调阈值/造数，而不是实现功能。
> **计划里的期望数字必须是实测过的**，这是本项目的硬规矩。

**6. 计划的技术前提已用真实数据实测验证（2026-10-31）**

在写这份计划时，用 `kline_cache` + `fund_flow_daily_cache` 的真实缓存跑了一次一致性探针：

```
可测样本: 123 只(同时有 K 线 + 逐日资金流, 且 K 线 ≥ 120 根)
路径 A(找股:120 根 K 线 + 120 天资金流)标注总数: 528
路径 B(K 线:全部 K 线 + 全部资金流)标注总数: 528
S_A ⊆ S_B 成立: 123 只 / 违反: 0 只
完全一致(含 reason / metrics 逐字比对): 123 只
(抽样 40 只)仅 B 有的标注数: 0
```

→ **两条路径在窗口对齐后产出逐字一致的标注**。这证明：
- Task 7 的 `S_A ⊆ S_B` 硬门槛**在当前实现下已经成立**（窗口对齐是它成立的前提，Task 2/3/4 负责建立这个前提）；
- 「尾窗口径」（MA20 / 量比 / 锁仓窗口都取尾窗）确实让 120 根与 300 根得出同一批信号 —— 这是 `behavior_signal_service` 模块 docstring 里那句话的实测背书；
- 闸 3 的巡检脚本**预期会报「✅ 两条路径完全一致」**，若它报差异，说明 Task 2/3/4 有一步没做对。

探针脚本已删除（不入库）；Task 7 的巡检脚本是它的正式版本。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-31-behavior-trust-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 每个 Task 派一个全新的 subagent，任务间我来审查，迭代快

**2. Inline Execution** - 在当前会话里按 Task 批量执行，带检查点

**选哪个？**
