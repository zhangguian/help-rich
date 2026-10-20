# Task 6 Brief: 改动 A-4 — scoring.event_score + config 常量

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1 ADR-0008: `74d6448`
- Task 2 fixture (AsyncMock): `84cba33`
- Task 3 ifind_events wrapper: `c8f9a0d`
- Task 4 event_factor_cache_repo + migration: `3be76ad`
- Task 5 event_factor_service: `e493ee2`

本任务（Task 6 / 20）实现**改动 A 的纯计算层**：
- `scoring.event_score()` 函数（命中事件 +15 分）
- `SCREENER_EVENT_FACTOR_WEIGHT = 15` 常量
- Task 7（下一 task）会把 event_score 接入 screener_service 评分循环

## Global Constraints (本任务相关)

- 工作分支: `main`
- 纯计算函数，无 I/O，幂等
- pytest 跑测试时不需要 DB（纯函数）
- **本地 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些
- **关键**：`backend/app/services/scoring.py` 是 22 个 modified 文件之一，**只追加** `event_score` 函数 + 必要的 import，**不动其他内容**

## Interfaces from Earlier Tasks

- Consumes: 无
- Produces:
  - `from app.services.scoring import event_score`
  - `event_score(stock_code, event_stock_codes, event_keywords) -> int` 返回 0 或 15
  - `from app.core.config import SCREENER_EVENT_FACTOR_WEIGHT` 常量 (int = 15)
  - `from app.core.config import SCREENER_EVENT_KEYWORD_BLACKLIST` 常量 (list[str] = ["ST", "*ST", "退市"])

## Task Description

### Files
- Modify: `backend/app/services/scoring.py`（**append-only** —— 在文件末尾追加 `event_score` 函数 + 必要的 import）
- Modify: `backend/app/core/config.py`（**append-only** —— 追加 2 个常量）
- Modify: `backend/tests/test_scoring.py`（**append-only** —— 追加 4 个新 test 函数）

### Steps

#### Step 1: 读现有 scoring.py

读 `backend/app/services/scoring.py` 全文，理解现有 4 个评分函数签名风格（`main_inflow_score`/`volume_ratio_score`/`momentum_score`/`sector_strength_score`）+ 顶部 import 风格。

#### Step 2: 写失败测试

编辑 `backend/tests/test_scoring.py`，**在文件末尾追加**（不动现有 tests）：

```python
"""scoring.event_score 单元测试 (改动 A)"""
from app.services.scoring import event_score


def test_event_score_hit_returns_full():
    codes = {"600519.SH", "300750.SZ"}
    assert event_score("600519.SH", codes, {"AI"}) == 15


def test_event_score_miss_returns_zero():
    codes = {"600519.SH"}
    assert event_score("000001.SZ", codes, {"AI"}) == 0


def test_event_score_case_insensitive():
    codes = {"600519.sh"}  # 小写
    assert event_score("600519.SH", codes, set()) == 15


def test_event_score_empty_inputs():
    assert event_score("600519.SH", set(), set()) == 0
    assert event_score("", set(), set()) == 0
```

注：这些 tests 不要重复 `from app.services.scoring import event_score` 如果文件已有导入（已有同名 import 会冲突）。检查现有 imports。

#### Step 3: 跑测试确认失败

```bash
cd backend && python -m pytest tests/test_scoring.py::test_event_score_hit_returns_full -v
```

Expected: FAIL with `ImportError: cannot import name 'event_score'`

#### Step 4: 在 config.py 加常量

编辑 `backend/app/core/config.py`，**在文件末尾追加**：

```python
# 改动 A: screener 事件因子加权 (iFinD 驱动)
SCREENER_EVENT_FACTOR_WEIGHT: int = 15
SCREENER_EVENT_KEYWORD_BLACKLIST: list[str] = ["ST", "*ST", "退市"]
```

#### Step 5: 在 scoring.py 加 event_score

编辑 `backend/app/services/scoring.py`，**在文件末尾追加**：

```python
def event_score(stock_code: str, event_stock_codes: set[str], event_keywords: set[str]) -> int:
    """事件命中分 (改动 A)

    命中热门事件相关股: SCREENER_EVENT_FACTOR_WEIGHT (默认 15)
    未命中: 0

    Args:
        stock_code: 当前候选股票代码(规整后)
        event_stock_codes: 当日热门事件相关股代码集合 (来自 event_factor_cache)
        event_keywords: 当日热门事件关键词 (保留参数, 未来扩展用)

    Returns:
        int: 0 或 SCREENER_EVENT_FACTOR_WEIGHT
    """
    if not stock_code or not event_stock_codes:
        return 0
    if stock_code.upper() in {c.upper() for c in event_stock_codes}:
        return SCREENER_EVENT_FACTOR_WEIGHT
    return 0
```

**确保文件顶部有 `from app.core.config import SCREENER_EVENT_FACTOR_WEIGHT` 或类似 import**：
- 如果文件顶部**已经** `from app.core.config import settings` —— 你需要再追加 import `SCREENER_EVENT_FACTOR_WEIGHT`（用 `from app.core.config import settings, SCREENER_EVENT_FACTOR_WEIGHT`）
- **只 append 必要 import**，**不动现有 import 行**

#### Step 6: 跑测试确认通过

```bash
cd backend && python -m pytest tests/test_scoring.py -v
```

Expected: 全部通过 (含原有 + 4 个新增)

#### Step 7: Commit

```bash
git add backend/app/services/scoring.py backend/app/core/config.py backend/tests/test_scoring.py
git commit -m "feat(scoring): 加 event_score 纯计算 + SCREENER_EVENT_FACTOR_WEIGHT 常量 (改动 A)"
```

## Acceptance Criteria

- `event_score` 函数定义在 `scoring.py` 末尾
- 2 个常量在 `config.py` 末尾
- 4 个新 test 在 `test_scoring.py` 末尾
- **全部现有 tests 仍然通过**（不破坏现有 scoring 函数）
- 1 commit on main，**仅含** 3 个 modified 文件
- 22 个未提交改动 + 1 个未跟踪迁移文件**未触碰**
- 所有改动的文件 trailing newline 保留

## Ambiguity Resolution

- **`scoring.py` 是 22 modified 文件之一**：只 append，不修改现有 import 行。如果 `from app.core.config import` 已经存在但**没有** `SCREENER_EVENT_FACTOR_WEIGHT`，**改**那行 import（追加名字）。如果完全没这个 import，append 一行新 import
- **`config.py` 也是 22 modified 文件之一**：只 append 常量，不动其他配置
- **`test_scoring.py` 也是 22 modified 文件之一**：只 append 4 个新 test 函数。如果现有文件已有 `from app.services.scoring import ...` 行，**不重复 import**（Python 会报错重复定义或 noop，但保持清洁）
- **case_insensitive 测试 `event_score("600519.SH", codes={"600519.sh"}, set()) == 15`**：测试大小写不敏感，pass。`event_keywords` 在 test 中是空 set 但**不是空 events**——event_score 不看 keywords，只看 codes（按 brief）
- **`event_keywords` 参数暂时没用**：brief 说"保留参数，未来扩展用"——保留但不调用
- **`SCREENER_EVENT_KEYWORD_BLACKLIST` 常量加了但 Task 6 不调用**：Task 7 才会用，提前加上避免后续 task 修改 config.py

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-6-report.md`

报告应包含：
- 实现了什么
- TDD evidence (RED + GREEN 命令 + 关键输出)
- **关键**：paste `git diff HEAD -- backend/app/services/scoring.py` 头部（验证 import 是 append-only）+ 尾部（验证 event_score append）
- 文件变更列表 + 行数
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns