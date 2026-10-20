# Task 6 Report: 改动 A-4 — scoring.event_score + config 常量

## 实现内容

1. **`backend/app/core/config.py`** — 文件末尾追加 2 个常量：
   - `SCREENER_EVENT_FACTOR_WEIGHT: int = 15`
   - `SCREENER_EVENT_KEYWORD_BLACKLIST: list[str] = ["ST", "*ST", "退市"]`

2. **`backend/app/services/scoring.py`**：
   - 顶部 `from app.core.config import (...)` 块**追加 1 个名字** (`SCREENER_EVENT_FACTOR_WEIGHT,`)—— 按 brief ambiguity 段「如果 `from app.core.config import` 已存在但没有新常量，**改**那行 import (追加名字)」的明确指示
   - 文件末尾**追加** `event_score(stock_code, event_stock_codes, event_keywords) -> int` 纯函数 + docstring

3. **`backend/tests/test_scoring.py`** — 文件末尾追加 1 个 `from app.services.scoring import event_score` import 行（沿用现有 `build_reason` 的分离 import 模式） + 4 个新 test 函数

## TDD 证据

### RED（先写测试，确认失败）

命令：
```bash
cd D:/zga-study/rich/backend
.venv/Scripts/python.exe -m pytest tests/test_scoring.py::test_event_score_hit_returns_full tests/test_scoring.py::test_event_score_miss_returns_zero tests/test_scoring.py::test_event_score_case_insensitive tests/test_scoring.py::test_event_score_empty_inputs -v
```

关键输出：
```
ImportError while importing test module 'D:\zga-study\rich\backend\tests\test_scoring.py'.
tests\test_scoring.py:296: in <module>
    from app.services.scoring import event_score
E   ImportError: cannot import name 'event_score' from 'app.services.scoring'
ERROR tests/test_scoring.py
============================== 1 error in 0.45s ==============================
```

✅ 期望失败原因（`ImportError: cannot import name 'event_score'`）—— 与 brief 一致。

### GREEN（实现后，全 34 项通过）

命令：
```bash
cd D:/zga-study/rich/backend
.venv/Scripts/python.exe -m pytest tests/test_scoring.py -v
```

关键输出（末尾）：
```
tests/test_scoring.py::test_event_score_hit_returns_full PASSED          [ 91%]
tests/test_scoring.py::test_event_score_miss_returns_zero PASSED          [ 94%]
tests/test_scoring.py::test_event_score_case_insensitive PASSED           [ 97%]
tests/test_scoring.py::test_event_score_empty_inputs PASSED               [100%]

============================= 34 passed in 0.31s ==============================
```

✅ 全部 34 测试通过。**新增 4 项** + **原有 30 项**，原有 0 回归。

### 测试清单
- pre-existing: 30
- new (`event_score`): 4
- total: 34

## 关键 git diff（验证 append-only）

### `backend/app/services/scoring.py`（头部 — 仅 import 追加 1 行）

```diff
diff --git a/backend/app/services/scoring.py b/backend/app/services/scoring.py
index 6bc9077..6f3d82a 100644
--- a/backend/app/services/scoring.py
+++ b/backend/app/services/scoring.py
@@ -16,6 +16,7 @@ from dataclasses import dataclass, field
 from app.core.config import (
     SCREENER_CHANGE_PCT_RANGE,
     SCREENER_CONSECUTIVE_UP_BONUS,
+    SCREENER_EVENT_FACTOR_WEIGHT,
     SCREENER_MAIN_INFLOW_MAX,
     SCREENER_MAIN_INFLOW_POINTS_STEP,
     SCREENER_MAIN_INFLOW_THRESHOLD_YI,
```

### `backend/app/services/scoring.py`（尾部 — event_score 纯追加）

```diff
@@ -258,4 +259,25 @@ def build_reason(features: StockFeatures, bd: ScoreBreakdown | None = None) -> s
     truncated = "，".join(parts[:4]) + "等。"
     if len(truncated) <= 100:
         return truncated
-    return truncated[:97] + "..."
\ No newline at end of file
+    return truncated[:97] + "..."
+
+
+def event_score(stock_code: str, event_stock_codes: set[str], event_keywords: set[str]) -> int:
+    """事件命中分 (改动 A)
+
+    命中热门事件相关股: SCREENER_EVENT_FACTOR_WEIGHT (默认 15)
+    未命中: 0
+
+    Args:
+        stock_code: 当前候选股票代码(规整后)
+        event_stock_codes: 当日热门事件相关股代码集合 (来自 event_factor_cache)
+        event_keywords: 当日热门事件关键词 (保留参数, 未来扩展用)
+
+    Returns:
+        int: 0 或 SCREENER_EVENT_FACTOR_WEIGHT
+    """
+    if not stock_code or not event_stock_codes:
+        return 0
+    if stock_code.upper() in {c.upper() for c in event_stock_codes}:
+        return SCREENER_EVENT_FACTOR_WEIGHT
+    return 0
\ No newline at end of file
```

### `backend/app/core/config.py`（仅末尾追加）

```diff
@@ -88,4 +88,8 @@ SCREENER_SECTOR_MAX = 25

 SCREENER_MIN_AMOUNT_YI = 1.0        # 最小成交额(亿元),过滤流动性极差
 SCREENER_MIN_SCORE = 30             # 综合分门槛
-SCREENER_MAX_DROP_PCT_5D = -15.0    # 近 5 日跌幅超过 -15% 一律剔除(避雷)
\ No newline at end of file
+SCREENER_MAX_DROP_PCT_5D = -15.0    # 近 5 日跌幅超过 -15% 一律剔除(避雷)
+
+# 改动 A: screener 事件因子加权 (iFinD 驱动)
+SCREENER_EVENT_FACTOR_WEIGHT: int = 15
+SCREENER_EVENT_KEYWORD_BLACKLIST: list[str] = ["ST", "*ST", "退市"]
\ No newline at end of file
```

### `backend/tests/test_scoring.py`（仅末尾追加）

```diff
@@ -288,4 +288,33 @@ def test_build_reason_length_cap():
 def test_build_reason_negative_change_warning():
     """回调涨幅 → 含「注意回调」"""
     r = build_reason(_features(change_pct=-2.5))
-    assert "注意回调" in r
\ No newline at end of file
+    assert "注意回调" in r
+
+
+# === event_score(改动 A: 事件命中分) ===
+
+from app.services.scoring import event_score
+
+
+def test_event_score_hit_returns_full():
+    """命中事件相关股 → SCREENER_EVENT_FACTOR_WEIGHT (15)"""
+    codes = {"600519.SH", "300750.SZ"}
+    assert event_score("600519.SH", codes, {"AI"}) == 15
+
+
+def test_event_score_miss_returns_zero():
+    """未命中事件相关股 → 0"""
+    codes = {"600519.SH"}
+    assert event_score("000001.SZ", codes, {"AI"}) == 0
+
+
+def test_event_score_case_insensitive():
+    """代码大小写不敏感: 集合中 '600519.sh' 小写也能命中 '600519.SH'"""
+    codes = {"600519.sh"}  # 小写
+    assert event_score("600519.SH", codes, set()) == 15
+
+
+def test_event_score_empty_inputs():
+    """空 stock_code 或空 event_stock_codes → 0(安全边界)"""
+    assert event_score("600519.SH", set(), set()) == 0
+    assert event_score("", set(), set()) == 0
\ No newline at end of file
```

## 文件变更统计

| 文件 | 改动 | 行为 |
|---|---|---|
| `backend/app/services/scoring.py` | +22 行（1 行 import 名 + 21 行 `event_score` 含 docstring） | 现有 4 个函数 / 1 个 dataclass 完全未动 |
| `backend/app/core/config.py` | +4 行（1 行注释 + 2 行常量 + 1 空行） | 现有 89 行配置完全未动 |
| `backend/tests/test_scoring.py` | +29 行（1 行 import + 1 行注释 + 4 个新 test 函数 27 行） | 现有 30 个 test 完全未动 |

总计：3 文件，**+58 / -3**（git stat 输出 `58 insertions(+), 3 deletions(-)`，3 个删除是 3 个 `\ No newline at end of file` 标记—— 文件末尾加新内容后 marker 行变化，与原文件同样无 trailing newline）

## Commit

- **Hash:** `99a037a`
- **Subject:** `feat(scoring): 加 event_score 纯计算 + SCREENER_EVENT_FACTOR_WEIGHT 常量 (改动 A)`
- **Files:** 仅 3 个 modified 文件（与 brief 一致）

```
[main 99a037a] feat(scoring): 加 event_score 纯计算 + SCREENER_EVENT_FACTOR_WEIGHT 常量 (改动 A)
 3 files changed, 58 insertions(+), 3 deletions(-)
```

## Self-Review (Append-Only 不变量)

✅ **22 个 modified 文件 + 1 untracked migration** 未触碰（git status 确认，Task 6 前后的 `git status --short` 输出除新 commit 之外完全一致）

✅ **scoring.py**：
- 顶部 import 块 —— 仅在 `from app.core.config import (...)` 块**追加** 1 行 `SCREENER_EVENT_FACTOR_WEIGHT,`（brief ambiguity 段明确许可"改那行 import (追加名字)"）
- 函数区 —— 原有 4 个评分函数 + 2 个 dataclass 完全未动
- 文件末尾 —— 纯追加 `event_score`（含 docstring）

✅ **config.py**：原有 89 行配置未动；仅末尾追加 2 个常量

✅ **test_scoring.py**：原有 30 个 test 函数未动；仅末尾追加 1 个 import + 4 个新 test（沿用现有 `from app.services.scoring import build_reason` 的分离 import 模式，未污染原有 8-18 行的 tuple-import 块）

✅ **trailing newline 保留**：3 个原文件都无 trailing newline，append 后依然无 trailing newline（diff 显示 `\ No newline at end of file` 在 + 和 - 两侧都有）

✅ **全部现有 test 仍通过**：30 个 pre-existing test 全 PASSED，无回归

## 备注

- 测试运行依赖 `backend/.venv`（项目自带 venv），`pydantic_settings` 不在系统 Python 中。命令使用 `.venv/Scripts/python.exe`，与项目约定一致
- brief 中"`from app.core.config import settings, SCREENER_EVENT_FACTOR_WEIGHT`"提到 `settings` 形式，但实际项目用的是多行 tuple import 形式，本任务**追加名字**到该 tuple 内（按 ambiguity 段指示），不修改其他行
- `SCREENER_EVENT_KEYWORD_BLACKLIST` 在 Task 6 未被调用（brief 明确说明 Task 7 才会用），仅声明常量
- `event_keywords` 参数在 `event_score` 内未使用（brief 明确"保留参数，未来扩展用"），保留为签名一部分