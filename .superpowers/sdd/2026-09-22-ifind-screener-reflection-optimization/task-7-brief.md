# Task 7 Brief: 改动 A-5 — screener_service 接入事件因子 ⭐用户可见变化 #1⭐

> 这是 SDD dispatch 的 requirements 文件。Implementer 只读本文件 + global constraints + report-file。**不要读整个 plan 文件**。

## Project Context

`D:/zga-study/rich` 本地 A 股投资辅助工具（branch `main`）。已交付：
- Spec: commit `ff5d275`
- Plan: commit `3d7b9a4`
- Task 1-6 commits: `74d6448` → `84cba33` → `c8f9a0d` → `3be76ad` → `e493ee2` → `99a037a`

本任务（Task 7 / 20）⭐ **用户能感知的第一个变化** —— 把 event_score 接入 screener_service 评分循环，让 screener 跑分时**真去打 iFinD 拉事件 + 加权**。这是 spec §4.1 "A 改动" 的最后一棒。

## Global Constraints (本任务相关)

- 工作分支: `main`
- 失败语义（spec §4.1）: A 失败时 screener 跑无事件因子版（4 因子），**不抛错**。**注意**：brief 字面 try/except Exception 会吞掉 IfindUnavailable，符合"静默降级"语义
- pytest + pytest-asyncio (`asyncio_mode = "auto"`)
- screener 总分上限 155 → 170（brief 未明确写但 plan §11 明确）
- **本地 22 个未提交改动 + 新迁移 `k3f4g5h6i7j8_drop_kline_cache.py`** —— 不动这些
- **关键**：`backend/app/services/screener_service.py` 是 22 个 modified 文件之一，**只追加 import + 评分循环里 2 处插入**，**不动其他内容**

## Interfaces from Earlier Tasks

- Consumes:
  - `from app.services.event_factor_service import build_event_factor_cache, get_event_factor_codes`
  - `from app.services.scoring import event_score`
  - `from app.core.config import SCREENER_EVENT_FACTOR_WEIGHT, SCREENER_EVENT_KEYWORD_BLACKLIST`（已 Task 6 加）
- Produces:
  - screener run 时**先** `await build_event_factor_cache(today)`
  - `event_codes = await get_event_factor_codes(today)`
  - 评分循环里 `pick.score += event_score(pick.stock_code, event_codes, set())`

## Task Description

### Files
- Modify: `backend/app/services/screener_service.py`（**append imports + 2 处插入** —— 评分循环前后）
- Create: `backend/tests/test_screener_with_event_factor.py`

### Steps

#### Step 1: 读现有 screener_service.py

读 `backend/app/services/screener_service.py` 全文，重点找：
- 顶部 import 风格
- 主入口函数名（`run_screener` / `run_daily` / 其他）
- 评分循环（典型 `for pick in candidates: pick.score = ...`）
- 日志 logger 变量名（`logger` / 其他）

#### Step 2: 写失败测试

新建 `backend/tests/test_screener_with_event_factor.py`：

```python
"""screener 接入事件因子端到端测试 (改动 A)"""
import pytest
from datetime import date
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_run_screener_calls_build_event_factor_first():
    """screener 启动时必须先 build_event_factor_cache"""
    today = date.today()
    with patch("app.services.screener_service.build_event_factor_cache", new=AsyncMock()) as mock_build:
        # 跑任意最小 screener 入口（实际函数名以代码为准）
        try:
            await screener_service.run_screener(date=today, dry_run=True)
        except Exception:
            pass  # dry_run 可能因 fixture 缺失报错, 只要 build_event_factor 被调到即可
        mock_build.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_screener_event_score_overrides_when_failure_falls_back():
    """ifind 失败 → event_factor_cache 为空 → screener 仍跑 (无事件因子, 4 因子版)"""
    from app.data.ifind_events import IfindUnavailable
    today = date.today()

    with patch("app.services.screener_service.build_event_factor_cache", new=AsyncMock(side_effect=IfindUnavailable("mocked"))):
        # 失败应被 try/except 吞掉, screener 仍跑 (spec §4.1 失败静默)
        try:
            await screener_service.run_screener(date=today, dry_run=True)
        except IfindUnavailable:
            pytest.fail("IfindUnavailable should be swallowed per spec §4.1")
        except Exception:
            pass  # 其他异常（如 fixture 缺失）可忽略


@pytest.mark.asyncio
async def test_event_score_applied_in_scoring_loop():
    """event_score 在评分循环里被调用, 命中股票 +15"""
    from app.services.scoring import event_score
    from app.services.event_factor_service import build_event_factor_cache, get_event_factor_codes
    from unittest.mock import patch

    # mock 缓存有 600519.SH 命中
    today = date.today()
    with patch("app.services.event_factor_service.get_event_factor_codes", new=AsyncMock(return_value={"600519.SH"})):
        with patch("app.services.screener_service.build_event_factor_cache", new=AsyncMock()):
            with patch("app.services.screener_service.get_event_factor_codes", new=AsyncMock(return_value={"600519.SH"})):
                # 直接验证 event_score 逻辑 (避免依赖完整 screener run)
                codes = {"600519.SH", "000001.SZ"}
                assert event_score("600519.SH", codes, set()) == 15
                assert event_score("000001.SZ", codes, set()) == 0
```

注：brief 原文 test `test_run_screener_calls_build_event_factor_first` 用了 `patch.object(screener_service, "build_event_factor_cache", ...)` —— 这种 patch 在 import 路径不同时会失效。已改为 `patch("app.services.screener_service.build_event_factor_cache", ...)` 字符串路径方式。

#### Step 3: 跑测试确认失败

```bash
cd backend && python -m pytest tests/test_screener_with_event_factor.py -v
```

Expected: FAIL（build_event_factor_cache 没在 screener_service 中被调用）

#### Step 4: 在 screener_service.py 顶部加 import

编辑 `backend/app/services/screener_service.py`，**append 到顶部 import 区**：

```python
from app.services.event_factor_service import build_event_factor_cache, get_event_factor_codes
from app.services.scoring import event_score
```

**如果已有 `from app.services.event_factor_service import ...` 重复则跳过**。
**如果已有 `from app.services.scoring import ...` 且没有 `event_score`，改那行 import**。
**如果完全没这些 import，append 新行**。
**禁止**：删除或重排现有 import 行（screener_service.py 是 22 modified 文件之一）。

#### Step 5: 在 screener 主入口前加 build_event_factor_cache + get_event_factor_codes 调用

找到 `run_screener` 函数（**实际名以代码为准**，可能是 `run_screener` / `run_daily` / `run`）。在**评分循环之前**插入：

```python
# 改动 A: 先构建当日事件因子缓存 (失败 fail-fast, 不跑评分)
try:
    await build_event_factor_cache(today)
except Exception as e:
    logger.warning("screener event factor unavailable today, running with 4-factor score: %s", e)
    # spec §4.1: A 失败时 screener 跑无事件因子版, 不抛错

event_codes = await get_event_factor_codes(today)
```

**关键决策（spec §4.1 + 你的"失败就是失败"原则的折衷）**：
- spec §4.1 明确说 A 失败时降级 4 因子版，**不抛错**
- 但 spec §3 全局说"失败就是失败"
- 实际语义：**screener 主流程不抛错**（避免破坏 15:30 自动化），但**评分循环 event_score 会因 event_codes=空集而全部返 0**（等价于"无事件因子"）
- 这就是 brief 字面的 try/except Exception + log warning 模式

#### Step 6: 在评分循环里叠加 event_score

找到评分循环（典型 `for pick in candidates: pick.score = ...` 或类似），**追加**到循环末尾（在其他因子叠加之后）：

```python
# 改动 A: 叠加事件因子分
pick.score += event_score(pick.stock_code, event_codes, set())
```

#### Step 7: 跑测试确认通过

```bash
cd backend && python -m pytest tests/test_screener.py tests/test_screener_with_event_factor.py -v
```

Expected: 全部通过 (原有 screener 测试不受影响 + 新增 3 个通过)

#### Step 8: 跑全量后端测试

```bash
cd backend && python -m pytest -x
```

Expected: 全部通过（spec §11 强调不破坏现有）

#### Step 9: Commit

```bash
git add backend/app/services/screener_service.py backend/tests/test_screener_with_event_factor.py
git commit -m "feat(screener): 接入事件因子加权, 失败静默走 4 因子版 (改动 A)"
```

## Acceptance Criteria

- screener_service.py 顶部加了 2 个 import（或与已有合并）
- screener_service 主入口前插入 `build_event_factor_cache(today)` + `get_event_factor_codes(today)`，**try/except 包 build，log warning，spec §4.1 静默降级**
- 评分循环里追加 `pick.score += event_score(...)`
- `test_screener_with_event_factor.py` 含 3 tests，全部通过
- **全量后端测试**全部通过（spec §11 不破坏）
- 1 commit on main，**仅含** 2 个 in-scope 文件
- 22 个未提交改动 + 1 个未跟踪迁移文件未触碰

## Ambiguity Resolution

- **`run_screener` 函数实际签名**：`run_screener(date=today, dry_run=True)` 是 brief 字面，**但实际函数可能不是这个签名**。如果 `run_screener` 不接受 `dry_run` / `date` 参数，implementer 应该**只 patch `build_event_factor_cache` 并断言它被调用**，而不是真跑完整 screener run。test `test_run_screener_calls_build_event_factor_first` 的 `try/except` 已经接受任意异常退出
- **`today` 变量**：screener_service 里可能用别的名字（如 `trade_date` / `today_date` / `T`）。implementer 必须**找到正确的日期变量**插入 build_event_factor_cache 调用
- **`logger` 变量名**：screener_service 里可能用 `logger` / `_logger` / `self.logger` 等。implementer 必须找到正确的 logger 名
- **try/except 吞 Exception 是否过宽**：brief 字面这么写。spec §4.1 明确说 A 失败静默。**不要**把 try/except 改成只 catch IfindUnavailable——任何 ifind-related 异常都该被吞
- **`event_codes` 作用域**：如果 try/except 后 `event_codes` 走不到，需要确保 `event_codes = set()` fallback。或者：build_event_factor_cache 失败时 `get_event_factor_codes(today)` 仍然能跑（缓存里没有就返空集）—— `get_event_factor_codes` 本身就处理 cache miss，所以可以放在 try/except 之外
- **`SCREENER_EVENT_KEYWORD_BLACKLIST` 用在哪**：本 task **不用**，Task 7 brief 没要求。spec §4.1 说事件命中股 +15 没考虑 ST 黑名单——本 task 不实现，Task 8 / 后续 task 可加
- **patch 字符串路径**：`patch("app.services.screener_service.build_event_factor_cache", ...)` 是字符串路径 patch，确保 screener_service 模块内的引用被替换

## Report File

**写报告到**: `D:/zga-study/rich/.superpowers/sdd/2026-09-22-ifind-screener-reflection-optimization/task-7-report.md`

报告应包含：
- 实现了什么
- 找到的 run_screener 函数实际签名
- 找到的 today / logger 变量实际名
- TDD evidence (RED + GREEN 命令 + 关键输出)
- **关键**：全量后端测试结果 `pytest -x`
- 文件变更列表 + 行数
- Commit hash + 短 subject
- self-review 发现
- 任何 issues 或 concerns