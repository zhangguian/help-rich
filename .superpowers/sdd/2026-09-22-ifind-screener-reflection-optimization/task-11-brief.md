# Task 11 Brief: 改动 B-3 — screener_service._apply_fundamental_filter

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-10 commits: `74d6448` → `84cba33` → `c8f9a0d` → `3be76ad` → `e493ee2` → `99a037a` → `7888122` → `dc24c10` → `e128eb7`
- 改动 A 完成 + Task 9 ifind_fundamentals wrapper + Task 10 ScreenerPick orm 扩列

本任务（Task 11 / 20）实现**改动 B 的核心业务逻辑**——`_apply_fundamental_filter` 函数，把基本面过滤接进 screener_service。

## Global Constraints

- 工作分支: `main`
- pytest 用 `.venv\Scripts\python.exe -m pytest`
- 失败语义（spec §6）：**任一票 ifind 调用失败 → 整体抛 IfindUnavailable**，不写库
- 不可达逻辑：spec §6 "失败就是失败"，无降级（与改动 A 不同）
- **本地 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些
- ⚠️ **`backend/app/services/screener_service.py` 是 22 modified 文件之一** —— **append-only**
- ⚠️ **`backend/app/core/config.py` 是 22 modified 文件之一** —— **append-only**
- ⚠️ **Task 7 已吃过用户 1 行 docstring 删除** —— 这次 implementer 必须**绝对不动** screener_service.py 已有内容（除了 append 2 行 import + 1 行 `_apply_fundamental_filter` 调用）

## Interfaces from Earlier Tasks

- Consumes:
  - `from app.data.ifind_fundamentals import is_hit_fundamental_filter`（Task 9）
  - `from app.data.ifind_events import IfindUnavailable`（Task 3）
  - `from app.core.config import SCREENER_FUNDAMENTAL_FILTER_ENABLED, SCREENER_FUNDAMENTAL_FILTER_QUERY, SCREENER_FUNDAMENTAL_KICKOUT_PENALTY`
- Produces:
  - `async _apply_fundamental_filter(picks: list) -> list`（in `screener_service.py`）

## Task Description

### Files
- Modify: `backend/app/services/screener_service.py`（**append-only** —— 2 行 import + 新函数 + 在 run_daily_pick 末尾插入 1 行调用）
- Modify: `backend/app/core/config.py`（**append-only** —— 追加 3 个常量）
- Create: `backend/tests/test_apply_fundamental_filter.py`

### Steps

#### Step 1: 在 config.py 加常量（append-only）

编辑 `backend/app/core/config.py`，**在文件末尾追加**：

```python
# 改动 B: screener Top N 基本面兜底过滤
SCREENER_FUNDAMENTAL_FILTER_ENABLED: bool = True
SCREENER_FUNDAMENTAL_FILTER_QUERY: str = "扣非ROE>0 PE<行业中位数 剔除ST"
SCREENER_FUNDAMENTAL_KICKOUT_PENALTY: int = 30
```

#### Step 2: 写失败测试

新建 `backend/tests/test_apply_fundamental_filter.py`：

```python
"""screener._apply_fundamental_filter 测试 (改动 B)"""
import pytest
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_apply_filter_all_pass_keeps_order():
    from app.services.screener_service import _apply_fundamental_filter

    picks = [
        SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None),
        SimpleNamespace(stock_code="000001.SZ", score=95, fundamental_filter_status=None),
    ]

    async def _hit(code, query):
        return True

    with patch("app.services.screener_service.is_hit_fundamental_filter", new=_hit):
        result = await _apply_fundamental_filter(picks)

    assert len(result) == 2
    assert all(p.fundamental_filter_status == "passed" for p in result)


@pytest.mark.asyncio
async def test_apply_filter_kicked_gets_penalty_and_resorts():
    from app.services.screener_service import _apply_fundamental_filter

    picks = [
        SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None),
        SimpleNamespace(stock_code="000001.SZ", score=99, fundamental_filter_status=None),
    ]

    async def _hit(code, query):
        return code != "000001.SZ"  # 000001 被踢

    with patch("app.services.screener_service.is_hit_fundamental_filter", new=_hit):
        result = await _apply_fundamental_filter(picks)

    assert result[0].stock_code == "600519.SH"
    assert result[0].fundamental_filter_status == "passed"
    assert result[1].stock_code == "000001.SZ"
    assert result[1].fundamental_filter_status == "kicked"
    assert result[1].score == 69


@pytest.mark.asyncio
async def test_apply_filter_failure_raises():
    """任一票基本面查失败 → 整体抛 IfindUnavailable"""
    from app.services.screener_service import _apply_fundamental_filter
    from app.data.ifind_events import IfindUnavailable

    picks = [
        SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None),
        SimpleNamespace(stock_code="000001.SZ", score=99, fundamental_filter_status=None),
    ]

    async def _hit(code, query):
        if code == "000001.SZ":
            raise IfindUnavailable("mocked")
        return True

    with patch("app.services.screener_service.is_hit_fundamental_filter", new=_hit):
        with pytest.raises(IfindUnavailable):
            await _apply_fundamental_filter(picks)


@pytest.mark.asyncio
async def test_apply_filter_disabled_short_circuits():
    """SCREENER_FUNDAMENTAL_FILTER_ENABLED=False 时原样返回"""
    from app.services.screener_service import _apply_fundamental_filter
    from app.core import config

    picks = [SimpleNamespace(stock_code="600519.SH", score=100, fundamental_filter_status=None)]

    with patch.object(config, "SCREENER_FUNDAMENTAL_FILTER_ENABLED", False):
        result = await _apply_fundamental_filter(picks)

    assert result == picks
    assert result[0].fundamental_filter_status is None
```

#### Step 3: 跑测试确认失败（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_apply_fundamental_filter.py -v
```

Expected: FAIL with `ImportError: cannot import name '_apply_fundamental_filter'`

#### Step 4: 在 screener_service.py 顶部加 import（append）

编辑 `backend/app/services/screener_service.py`，**追加**到 import 区（如果已经 import 了 `from app.data.ifind_events`，改那行）：

```python
from app.data.ifind_fundamentals import is_hit_fundamental_filter
from app.data.ifind_events import IfindUnavailable
```

#### Step 5: 实现 _apply_fundamental_filter

编辑 `backend/app/services/screener_service.py`，**在文件末尾追加**（建议紧跟 `run_daily_pick` 或主函数之后）：

```python
async def _apply_fundamental_filter(picks: list) -> list:
    """对 Top N 跑一次基本面兜底过滤; 任一失败直接抛 IfindUnavailable.

    行为:
    - SCREENER_FUNDAMENTAL_FILTER_ENABLED=False → 原样返
    - is_hit_fundamental_filter 返 True → fundamental_filter_status='passed', 分不变
    - 返 False → fundamental_filter_status='kicked', 扣 SCREENER_FUNDAMENTAL_KICKOUT_PENALTY
    - 任一票 ifind 调用失败 → 抛 IfindUnavailable, 不写库

    Args:
        picks: ScreenerPick 对象列表 (含 stock_code, score)

    Returns:
        重新排序的 picks 列表
    """
    from app.core.config import (
        SCREENER_FUNDAMENTAL_FILTER_ENABLED,
        SCREENER_FUNDAMENTAL_FILTER_QUERY,
        SCREENER_FUNDAMENTAL_KICKOUT_PENALTY,
    )
    if not SCREENER_FUNDAMENTAL_FILTER_ENABLED:
        return picks

    import asyncio

    # 并发查 Top N
    results = await asyncio.gather(
        *[is_hit_fundamental_filter(p.stock_code, SCREENER_FUNDAMENTAL_FILTER_QUERY) for p in picks],
        return_exceptions=True,
    )
    # 任一失败 → 整体抛
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            if isinstance(r, IfindUnavailable):
                raise r
            raise IfindUnavailable(f"基本面过滤异常: {picks[i].stock_code}: {r}") from r

    for pick, hit in zip(picks, results):
        if hit:
            pick.fundamental_filter_status = "passed"
        else:
            pick.fundamental_filter_status = "kicked"
            pick.score -= SCREENER_FUNDAMENTAL_KICKOUT_PENALTY

    picks.sort(key=lambda p: p.score, reverse=True)
    return picks
```

注：brief 原版在函数内 import config + asyncio — 我**已经把 import 移到函数顶部**（更清晰）。如果 implementer 想保留 brief 字面，可以放函数内。

#### Step 6: 在 run_daily_pick 末尾插入调用

找到 `run_daily_pick` 函数（Task 7 已确认这是实际主入口）。在**评分循环结束后、最终排序前**（或在最终排序后但未持久化前），**追加**：

```python
# 改动 B: 基本面兜底过滤 (失败 fail-fast)
await _apply_fundamental_filter(top_n_picks)
```

**关键**：brief 说"在 run_screener 末尾插入"，但实际主函数是 `run_daily_pick`（Task 7 已确认）。implementer 必须找到正确的入口 + 正确的 top_n_picks 变量名（可能是 `top_n_picks` / `final_picks` / 其他）。

#### Step 7: 跑测试确认通过（用 venv python）

```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/test_apply_fundamental_filter.py tests/test_screener.py tests/test_screener_with_event_factor.py -v
```

Expected: 全部通过

#### Step 8: 跑全量后端测试

```bash
cd backend && .venv\Scripts\python.exe -m pytest -x
```

Expected: 全部通过（spec §11 强调不破坏现有）

#### Step 9: Commit

```bash
git add backend/app/services/screener_service.py backend/app/core/config.py backend/tests/test_apply_fundamental_filter.py
git commit -m "feat(screener): Top N 基本面兜底过滤, 失败 fail-fast (改动 B)"
```

## Acceptance Criteria

- `_apply_fundamental_filter` 函数定义在 `screener_service.py` 末尾
- 3 个常量在 `config.py` 末尾
- 4 个 test 全过
- **全量后端测试**全部通过
- 1 commit on main，**仅含** 3 个 in-scope 文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰
- **`screener_service.py` 与 `config.py` 已有部分**字节相同**（仅 append）

## Ambiguity Resolution

- **`run_daily_pick` 是实际主入口**（Task 7 已确认）
- **`top_n_picks` 变量名** —— implementer 必须找到正确名（可能是 `top_n_picks` / `final_picks` / `scored_picks`）
- **brief 字面 try/except 在函数内** —— 我已改为顶部 import（更清晰），implementer 可用任一方式
- **失败语义**：spec §6 明确说 B 失败不展示 Top N（hard gate）。`raise IfindUnavailable` 让上层 caller 决定。**screener run 怎么 catch 这个异常** —— implementer 应该让 run_daily_pick **catch IfindUnavailable → log error + 不持久化 + 不展示**
- **`asyncio` import** —— 如果文件已经有 import，append `import asyncio`；否则 brief 字面放在函数内
- **`SCREENER_FUNDAMENTAL_FILTER_QUERY`** —— 默认 `"扣非ROE>0 PE<行业中位数 剔除ST"`，与 spec §4.2 一致

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-11-report.md`

报告应包含：
- 实现了什么
- 找到的 `run_daily_pick` 入口 + `top_n_picks` 变量实际名
- TDD evidence (RED + GREEN + 全量 via `.venv\Scripts\python.exe`)
- **关键**：`git diff HEAD~1..HEAD -- backend/app/services/screener_service.py` 末尾（确认 append-only）
- 文件变更列表 + 行数
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns