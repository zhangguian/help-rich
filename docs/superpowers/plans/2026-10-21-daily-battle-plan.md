# 每日作战计划（复盘 + 明日操作预期）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让股民在今天收盘后拿到一份「今日复盘 + 明日市场预期 + 明日逐票操作预案」的作战日报，明天开盘前就知道每只票什么价位做什么动作，昨天的计划兑现了没有。

**Architecture:** 后端三个**纯函数**模块（明日预期规则 / 决策→预案转换 / 兑现比对）产出结构化结论，一个编排服务取数并落库，前端独立页面 `/plan` 呈现。**全程零 LLM**——所有数字来自真实数据源或对其显式四则运算，因果可复算，日后才能验证判断对错。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0（Mapped 风格）+ Alembic + pytest；Next.js 14 App Router + TypeScript + Tailwind + axios。

**Spec:** `docs/superpowers/specs/2026-10-21-daily-battle-plan-design.md`（commit `fa8be50`）

---

## Global Constraints

以下约束**逐条适用于本计划的所有任务**（来自 spec §十 与项目既有铁律）：

1. **全部数据真实，零 mock**。生产代码不得出现任何假数据兜底；缺数据 → 该项为 `None` + 写入 `degraded` 标记，**绝不编造数字、绝不因字段缺失隐藏整块内容**。
2. **LLM 只翻译不计算**。本设计**完全不使用 LLM**；文案由模板拼装。
3. **决策层纯函数、零 IO、零 LLM**。`outlook_service` / `plan_item_builder` / `fulfillment_checker` 三个模块**不得 import 任何 IO 服务**（不 import `fetch_klines` / `QuoteService` / `db` / `repository`），只接受已取好的 `dict` / `list`。
4. **价格必须来自 indicators / 报价 / 持仓，或其显式四则运算**。触发价直接继承决策引擎已算好的 `action["price"]`；失效条件里的 `×0.97` / `×1.03` 是显式四则运算。
5. **统一用 `effective_price(ctx)`**。转换层不自行取价。
6. **红 = 买 / 看多 / 涨；绿 = 卖 / 看空 / 跌**（A 股红涨绿跌）。青 `#22D3EE` 只给选中/焦点；琥珀 `#F5A524` 只给预警。**浮盈用红色、浮亏用绿色**（与盯盘台持仓页签一致）。
7. **首屏不留大片虚空**。空态/加载态/错误态都要有实质内容。
8. **回测闸门先定、事后不得下调**。明日预期的规则参数（1.10 / 0.90 / 60% / 40%）在本计划中**先定死**，后续回测校准**只能改参数、不能事后调门槛美化结论**。
9. **命令一律用 PowerShell 语法**（本机 Windows 5.1，无 `&&`）。`$env:VAR` 设环境变量，单引号字面量。
10. **测试必须先设 3 个环境变量**，否则污染开发库 / collect 失败：
    ```powershell
    $env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
    $env:PYTHONIOENCODING='utf-8'
    $env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
    ```
11. **`npm run build` 与 dev server 共用 `.next`，必须先停 dev 再 build**。
12. **测文件内容用 grep / node 逐字节读**；**Python 调试脚本写成 `.py` 文件再跑**（`python -c` 在本环境会被 shell 吃掉引号）。
13. **前端配色必须用项目语义 class，不得用 Tailwind 默认色**（2026-10-21 实测编译 Tailwind 得到的权威清单）：
    - 行情色：`text-up`（红=买/看多/涨）、`text-down`（绿=卖/看空/跌）、`text-warn`（琥珀=预警）
    - 语义底色：`bg-up-bg`、`bg-warn-bg`、`bg-down-bg`、`bg-bg-subtle`
    - 边框：`border-border-def`、`border-border-str`、`border-up/40`、`border-down/40`、`border-warn/40`
    - 文字：`text-text-pri`、`text-text-sec`、`text-text-ter`
    - 强调：`text-accent`、`bg-accent`、`border-accent`、`text-bg-base`
    - ⚠️ **`text-red-500` / `text-green-500` / `text-amber-500` / `border-line` / `border-def` / `text-pri` 在本项目不存在**，用它们会**静默掉样式**（typecheck 查不出来，只有实拍才发现）。`text-red-500` 虽被少数旧文件使用，但新代码一律用 `text-up`。

---

## File Structure

### 后端新增

| 文件 | 单一职责 | IO |
|---|---|---|
| `backend/app/services/position_status.py` | 持仓盈亏状态判定（**从 api/stock.py 提取的共享口径**） | 无（纯函数） |
| `backend/app/services/outlook_service.py` | 明日市场预期：四维度规则推断 + 关键位 | 无（纯函数） |
| `backend/app/services/plan_item_builder.py` | 决策输出 → 明日预案项 / 今日待办 | 无（纯函数） |
| `backend/app/services/fulfillment_checker.py` | 昨日预案 × 今日行情+流水 → 兑现状态 | 无（纯函数） |
| `backend/app/services/battle_plan_service.py` | 取数 → 调用三模块 → 落库 → 回填兑现 | 有 |
| `backend/app/repositories/battle_plan_repo.py` | `battle_plans` / `battle_plan_items` 读写 | 有 |
| `backend/app/api/battle_plan.py` | 三个 HTTP 端点 | 有 |

### 后端修改

| 文件 | 改动 |
|---|---|
| `backend/app/api/stock.py` | 三个私有 helper 改为从 `position_status.py` 导入的**薄封装**（保留原私有名，既有 13 处测试 import 不破） |
| `backend/app/models/orm.py` | +2 表（`BattlePlan` / `BattlePlanItem`） |
| `backend/migrations/versions/<new_rev>_add_battle_plan_tables.py` | 新增迁移，`down_revision = "f6a7b8c9d0e1"` |
| `backend/app/main.py` | +`app.include_router(battle_plan_router, prefix="/api")` |

### 前端新增

| 文件 | 职责 |
|---|---|
| `frontend/src/app/(app)/plan/page.tsx` | 页面壳 |
| `frontend/src/components/plan/PlanPanel.tsx` | 主容器（三段编排 + 三态） |
| `frontend/src/components/plan/OutlookCard.tsx` | 明日市场预期 |
| `frontend/src/components/plan/PlanItemList.tsx` | 明日预案清单 |
| `frontend/src/components/plan/ReviewCard.tsx` | 今日复盘 |

### 前端修改

| 文件 | 改动 |
|---|---|
| `frontend/src/lib/api/advanced.ts` | +3 个 API 函数 + 顶部加 type import |
| `frontend/src/lib/planTypes.ts` | +计划相关类型（**新建独立文件** —— `types.ts` 会被 `npm run gen-types` 覆盖） |
| `frontend/src/components/shell/NavRail.tsx` | +「作战计划」导航项 |

### 测试新增

```
backend/tests/test_outlook_service.py
backend/tests/test_plan_item_builder.py
backend/tests/test_fulfillment_checker.py
backend/tests/test_battle_plan_service.py
backend/tests/test_battle_plan_api.py
```

---

## 跨任务锁定的接口契约

**后续任务必须严格按此调用，签名/字段名不得漂移。**

```python
# app/services/position_status.py
def resolve_position_status(position, current_price, fallback_price=None) -> tuple[str, float | None]
    # 返回 (status, cost_basis_pct);status ∈ {"empty","profit","loss"}

def kline_fallback_price(klines: list[dict] | None) -> str | None

def sanitize_current_price(quote, klines: list[dict] | None) -> tuple[str | None, str | None]


# app/services/outlook_service.py
def build_outlook(
    index_klines: list[dict],          # 升序日K: {date,open,high,low,close,volume(int)}
    sentiment: dict | None,            # {up_total:int, down_total:int, ...}
    sector_flows: list[dict] | None,   # [{name:str, netamount_yi:float}, ...]
) -> dict
    # 返回 §4.3.5 结构


# app/services/plan_item_builder.py
def build_items(decision: dict, position: dict | None) -> list[dict]
def build_todos(decision: dict) -> list[dict]


# app/services/fulfillment_checker.py
def check_fulfillment(
    items: list[dict],                   # 预案项(含 trigger_price/direction/item_kind)
    target_klines: dict[str, list[dict]],# {stock_code: [{date,open,high,low,close}]}
    transactions: list[dict],            # [{stock_code,action("buy"/"sell"),shares,price,trade_date}]
) -> list[dict]                          # 每项补 fulfillment / fulfillment_note


# app/services/battle_plan_service.py
async def resolve_target_stocks() -> list[dict]
    # [{stock_code, stock_name, in_position: bool, is_favorite: bool}]

async def build_plan(plan_date: date) -> dict
async def get_plan(plan_date: date) -> dict | None
```

**决策引擎输出结构（`build_decision` 的返回值，转层的输入）**——已核实：

```python
{
  "stock_code": str, "stock_name": str|None,
  "verdict": str, "headline": str, "confidence": str, "role": str,
  "position_status": "empty"|"profit"|"loss",
  "actions": [ {"kind","label","condition","price","basis":[str],"status"} ],
      # kind ∈ entry|add|exit|stop|t_sell|t_buyback|watch
      # status ∈ now|armed|blocked
  "stop_loss": {"price": float, "basis": str} | None,
  "position_pct": str,
  "do_not": [str, ...],
  "t_plan": {"suitable": bool, "t_high": float|None, "t_low": float|None,
             "amplitude_pct": float|None, "sell_trigger": str, "buyback_trigger": str,
             "base_position_pct": str, "unsuitable_signals": str, "needs_position": bool},
  "trend_state": {...}, "market_env": {...},
  "data_quality": {"degraded": bool},
}
```

**预案项结构（落库与 API 的统一形状）**：

```python
{
  "stock_code": str, "stock_name": str|None,
  "item_kind": str,     # entry|add|exit|stop|t_sell|t_buyback|watch|unlock|do_not
  "direction": str,     # buy|sell|none
  "label": str,
  "trigger_price": float|None,
  "trigger_condition": str,
  "basis": [str, ...],
  "invalid_if": str,
  "status_now": str,    # now|armed|blocked
  "fulfillment": str,   # pending|touched|executed|missed|n_a
  "fulfillment_note": str,
}
```

---

## Task 1: 提取持仓状态判定为共享模块

**Why first:** `battle_plan_service` 要复用「持仓盈亏状态」判定，但该逻辑现在住在 `api/stock.py` 的私有函数里，注释明确写着「**唯一来源**」。复制一份就会出现两个判定口径——已持仓者可能被判成空仓，进而对着深套持仓说「可以建仓」（这是 2026-10-21 评审发现过的真实事故）。先提取、后复用。

**Files:**
- Create: `backend/app/services/position_status.py`
- Modify: `backend/app/api/stock.py`（三个私有函数改为薄封装）
- Test: `backend/tests/test_decision_api.py`（既有，验证行为不变）、`backend/tests/test_stock_advice.py`（既有）

**Interfaces:**
- Consumes: 无（从既有代码搬移）
- Produces: `app.services.position_status.{resolve_position_status, kline_fallback_price, sanitize_current_price}`

- [ ] **Step 1: 记录基线（证明提取前后行为一致）**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_decision_api.py tests/test_stock_advice.py -q --no-header -p no:cacheprovider
```

Expected: 全部 PASS（记录数字，后续对比必须一致）。

- [ ] **Step 2: 创建共享模块**

创建 `backend/app/services/position_status.py`：

```python
"""持仓盈亏状态判定(共享口径)

**为什么从 api/stock.py 提取出来(spec 阶段9 任务1)**:
`position_status` 的判定规则是全项目**唯一来源**——决策卡、作战计划、
复盘都要用同一个口径。原先它住在 `api/stock.py` 的私有函数里,
新服务(作战计划)若复制一份,就会出现"两个判定口径"的问题:
一个真实持有 700 股 @23.04 的用户,拿不到报价时会被判成「空仓」→
对着已深套的持仓说「首仓 30%,可以建仓」(2026-10-21 评审发现的真实事故)。

本模块**纯函数、零 IO**,只接受已取好的数据。
`api/stock.py` 保留同名私有名做薄封装,既有 13 处测试 import 不破。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_position_status(
    position, current_price: str | None, fallback_price: str | None = None
) -> tuple[str, float | None]:
    """根据持仓 + 现价判断 role:empty / profit / loss

    Returns:
        (status, cost_basis_pct)
        status: empty / profit / loss
        cost_basis_pct: 基于持仓成本的盈亏百分比(0.05 = +5%);空仓 / 价格不可得时为 None
    """
    if position is None or position.shares <= 0:
        return "empty", None
    price = current_price if current_price is not None else fallback_price
    if price is None:
        # 有持仓但连收盘价都拿不到 → 无法判定盈亏,保守按 'loss' 处理
        return "loss", None
    try:
        cur = float(price)
        cost = float(position.avg_cost)
        if cost <= 0 or cur <= 0:
            return "loss", None
        pct = (cur / cost - 1.0)
        # 持平也归 'profit'(规则是 >= )—— 绝不能归 'empty':
        # 'empty' 会让决策卡给出「建仓参考 / 首仓 X%」,对已持仓者是误导。
        if cur >= cost:
            return "profit", pct
        return "loss", pct
    except (ValueError, TypeError):
        return "loss", None


def kline_fallback_price(klines: list[dict] | None) -> str | None:
    """K 线最新收盘价 —— 实时报价缺失时判定持仓盈亏的兜底价(§5 effective_price)"""
    if not klines:
        return None
    try:
        close = klines[-1].get("close")
        return str(close) if close is not None else None
    except (AttributeError, IndexError, TypeError):
        return None


def sanitize_current_price(
    quote, klines: list[dict] | None
) -> tuple[str | None, str | None]:
    """校验 current_price 与 K 线最新 close 的偏离度;偏差 > 10% 视为数据源异常,降级 None。

    Returns:
        (current_price_str, current_price_date_str) — 校验通过返回;否则 (None, None)
    """
    if quote is None:
        return None, None
    price = quote.current_price
    if price is None:
        return None, None
    current_price = str(price)
    current_price_date = quote.timestamp.date().isoformat() if quote.timestamp else None
    if klines:
        try:
            latest_close = float(klines[-1]["close"])
            cur = float(current_price)
            if latest_close > 0:
                deviation = abs(cur - latest_close) / latest_close
                if deviation > 0.10:
                    logger.warning(
                        "current_price 与 K 线 close 偏差过大: quote=%s kline=%s 偏差 %.2f%%, 降级",
                        current_price, latest_close, deviation * 100,
                    )
                    return None, None
        except (ValueError, TypeError):
            pass
    return current_price, current_price_date


__all__ = [
    "kline_fallback_price",
    "resolve_position_status",
    "sanitize_current_price",
]
```

- [ ] **Step 3: `api/stock.py` 改为薄封装**

在 `backend/app/api/stock.py` 的 import 区加入：

```python
from app.services.position_status import (
    kline_fallback_price as _kline_fallback_price,
    resolve_position_status as _resolve_position_status,
    sanitize_current_price as _sanitize_current_price,
)
```

**删除**这三个函数的原有定义（`_resolve_position_status`、`_kline_fallback_price`、`_sanitize_current_price`），保留它们的原注释要点已迁移到新模块。

> ⚠️ `_resolve_position_status` 的 docstring 里有一段 2026-10-21 的事故复盘记录，是这个判定规则存在的原因证据——它已随函数体迁到新模块，**不要删掉那段文字**。

- [ ] **Step 4: 验证行为完全一致**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_decision_api.py tests/test_stock_advice.py -q --no-header -p no:cacheprovider
```

Expected: 与 Step 1 **完全相同的通过数**（不多不少）。

- [ ] **Step 5: 静态检查**

```powershell
Set-Location 'D:\zga-study\rich\backend'
& '.\.venv\Scripts\python.exe' -m ruff check app/services/position_status.py app/api/stock.py
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/services/position_status.py backend/app/api/stock.py
git commit -m "refactor(portfolio): 持仓状态判定提取为共享模块 position_status

- resolve_position_status / kline_fallback_price / sanitize_current_price
  从 api/stock.py 提取到 services/position_status.py(纯函数、零 IO)
- api/stock.py 保留同名私有名做薄封装,既有 13 处测试 import 不破
- 动机: 作战计划要复用同一判定口径,复制一份会出现两个口径
  (持仓者被判空仓 → 对深套持仓说'可以建仓')"
```

---

## Task 2: 明日市场预期（outlook_service）

**Files:**
- Create: `backend/app/services/outlook_service.py`
- Test: `backend/tests/test_outlook_service.py`

**Interfaces:**
- Consumes: 无（纯函数）
- Produces: `build_outlook(index_klines, sentiment, sector_flows) -> dict`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_outlook_service.py`：

```python
"""明日市场预期规则(纯函数、零 IO、零 LLM)

设计文档 §4.3
"""
from __future__ import annotations

import pytest

from app.services.outlook_service import build_outlook


def _klines(closes: list[float], volumes: list[float] | None = None,
            highs: list[float] | None = None, lows: list[float] | None = None) -> list[dict]:
    """构造升序日K;volumes/highs/lows 缺省时用 close 派生"""
    n = len(closes)
    vols = volumes if volumes is not None else [100.0] * n
    his = highs if highs is not None else list(closes)
    los = lows if lows is not None else list(closes)
    return [
        {
            "date": f"2026-01-{i + 1:02d}",
            "open": c, "high": his[i], "low": los[i], "close": c, "volume": int(vols[i]),
        }
        for i, c in enumerate(closes)
    ]


def _dim(outlook: dict, key: str) -> dict:
    return next(d for d in outlook["dims"] if d["key"] == key)


# ---------------- 量能维度 ----------------

def test_volume_bull_when_today_110pct_of_avg5():
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]  # 今日 110,前5日均 100
    out = build_outlook(_klines(closes, volumes), None, None)
    d = _dim(out, "volume")
    assert d["score"] == 1
    assert d["state"] == "bull"


def test_volume_bear_when_today_90pct_of_avg5():
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 90.0]
    out = build_outlook(_klines(closes, volumes), None, None)
    assert _dim(out, "volume")["score"] == -1


def test_volume_neutral_between_90_and_110():
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 105.0]
    out = build_outlook(_klines(closes, volumes), None, None)
    assert _dim(out, "volume")["score"] == 0


def test_volume_missing_when_klines_lt_6():
    out = build_outlook(_klines([10.0] * 3), None, None)
    assert _dim(out, "volume")["state"] == "missing"
    assert _dim(out, "volume")["score"] == 0


# ---------------- 涨跌家数维度 ----------------

def test_sentiment_bull_when_up_ratio_ge_60pct():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 60, "down_total": 40}, None)
    assert _dim(out, "sentiment")["score"] == 1


def test_sentiment_bear_when_up_ratio_le_40pct():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 30, "down_total": 70}, None)
    assert _dim(out, "sentiment")["score"] == -1


def test_sentiment_neutral_between_40_and_60():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 50, "down_total": 50}, None)
    assert _dim(out, "sentiment")["score"] == 0


def test_sentiment_missing_when_zero_total():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 0, "down_total": 0}, None)
    assert _dim(out, "sentiment")["state"] == "missing"


def test_sentiment_missing_when_none():
    out = build_outlook(_klines([10.0] * 30), None, None)
    assert _dim(out, "sentiment")["state"] == "missing"


# ---------------- 均线维度 ----------------

def test_ma_bull_when_close_above_ma5_above_ma10():
    closes = [10.0] * 10 + [12.0]
    out = build_outlook(_klines(closes), None, None)
    assert _dim(out, "ma")["score"] == 1


def test_ma_bear_when_close_below_ma5_below_ma10():
    closes = [12.0] * 10 + [10.0]
    out = build_outlook(_klines(closes), None, None)
    assert _dim(out, "ma")["score"] == -1


def test_ma_missing_when_klines_lt_11():
    out = build_outlook(_klines([10.0] * 10), None, None)
    assert _dim(out, "ma")["state"] == "missing"


# ---------------- 板块资金维度 ----------------

def test_flow_bull_when_net_total_positive():
    """净流入总额为正(+3.2 - 1.0 = +2.2)→ 偏多"""
    flows = [{"name": "电子元件", "netamount_yi": 3.2}, {"name": "煤炭", "netamount_yi": -1.0}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    assert _dim(out, "flow")["score"] == 1


def test_flow_bear_when_all_negative():
    flows = [{"name": "煤炭", "netamount_yi": -1.0}, {"name": "钢铁", "netamount_yi": -2.0}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    assert _dim(out, "flow")["score"] == -1


def test_flow_neutral_when_mixed():
    """净流入与净流出抵消(+1.0 - 1.0 = 0)→ 中性"""
    flows = [{"name": "电子元件", "netamount_yi": 1.0}, {"name": "煤炭", "netamount_yi": -1.0}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    assert _dim(out, "flow")["score"] == 0


def test_flow_missing_when_empty_list():
    out = build_outlook(_klines([10.0] * 30), None, [])
    assert _dim(out, "flow")["state"] == "missing"


def test_flow_neutral_when_float_sum_is_zero():
    """浮点零和:[38.6, -12.4, -26.2] 的和是 3.55e-15 而非精确 0,必须归一到 0 → 中性"""
    flows = [{"name": "A", "netamount_yi": 38.6}, {"name": "B", "netamount_yi": -12.4},
             {"name": "C", "netamount_yi": -26.2}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    d = _dim(out, "flow")
    assert d["score"] == 0
    assert d["state"] == "flat"


def test_flow_missing_when_all_netamount_are_none():
    """全部板块净额为 None = 根本没有板块资金数据 → missing(不能算 flat)"""
    flows = [{"name": "A", "netamount_yi": None}, {"name": "B", "netamount_yi": None}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    d = _dim(out, "flow")
    assert d["state"] == "missing"
    assert d["score"] == 0


def test_flow_bear_detail_has_no_double_negative():
    """净流出文案用绝对值,不出现「净流出合计 -3.00 亿」这种双重否定"""
    flows = [{"name": "煤炭", "netamount_yi": -1.0}, {"name": "钢铁", "netamount_yi": -2.0}]
    out = build_outlook(_klines([10.0] * 30), None, flows)
    detail = _dim(out, "flow")["detail"]
    assert "-3.00" not in detail
    assert "3.00" in detail


# ---------------- 结论合成 ----------------

def test_unknown_when_all_dims_missing():
    out = build_outlook([], None, None)
    assert out["stance"] == "unknown"
    assert out["dims_effective"] == 0
    assert out["degraded"] is True


def test_bullish_requires_at_least_2_effective_dims():
    """只靠单一维度不得判偏多(过度自信)"""
    # 只有量能 +1,其余全缺
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 110.0]
    out = build_outlook(_klines(closes, volumes), None, None)
    assert out["dims_effective"] == 1
    assert out["stance"] == "neutral"


def test_bullish_when_2_dims_and_score_ge_1():
    # 10 根 K:均线维度因不足 11 根而 missing,有效维度恰为 2(量能 + 涨跌家数)
    closes = [10.0] * 10
    volumes = [100.0] * 9 + [110.0]
    out = build_outlook(_klines(closes, volumes), {"up_total": 60, "down_total": 40}, None)
    assert out["dims_effective"] == 2
    assert out["score"] == 2
    assert out["stance"] == "bullish"


def test_bearish_allows_single_dim():
    """偏空判定不对称:单条强证据即可成立(风险侧保守优于激进)"""
    closes = [10.0] * 6
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 90.0]
    out = build_outlook(_klines(closes, volumes), None, None)
    assert out["dims_effective"] == 1
    assert out["stance"] == "bearish"


def test_stance_label_mapping():
    out = build_outlook([], None, None)
    assert out["stance_label"] == "数据不足"


# ---------------- 关键位 ----------------

def test_support_only_below_close():
    closes = [10.0] * 10 + [12.0]
    highs = [11.0] * 10 + [13.0]
    lows = [9.0] * 10 + [11.5]
    out = build_outlook(_klines(closes, highs=highs, lows=lows), None, None)
    kl = out["key_levels"]
    assert 12.0 not in kl["support"]          # 收盘价本身不作支撑
    assert all(v < 12.0 for v in kl["support"])
    assert all(v > 12.0 for v in kl["resistance"])


def test_key_levels_include_close_and_ma():
    out = build_outlook(_klines([10.0] * 30), None, None)
    kl = out["key_levels"]
    assert kl["close"] == 10.0
    assert kl["ma5"] == 10.0
    assert kl["ma10"] == 10.0
    assert kl["ma20"] == 10.0


def test_disclaimer_always_present_and_says_not_prediction():
    out = build_outlook(_klines([10.0] * 30), {"up_total": 60, "down_total": 40}, None)
    assert "非预测" in out["disclaimer"]


def test_dims_always_four_items():
    out = build_outlook(_klines([10.0] * 30), None, None)
    assert len(out["dims"]) == 4
    assert {d["key"] for d in out["dims"]} == {"volume", "sentiment", "ma", "flow"}
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_outlook_service.py -q --no-header -p no:cacheprovider
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.outlook_service'`

- [ ] **Step 3: 实现**

创建 `backend/app/services/outlook_service.py`：

```python
"""明日市场预期(纯函数、零 IO、零 LLM)

设计文档 §4.3。

**定位**:纪律锚点,不是预测器。
四维度规则打分 → 偏多/震荡/偏空 + 关键位。所有数字取自真实数据源
(上证指数日K / 涨跌家数 / 板块资金流),或对其显式四则运算。

**铁律**:
- 文案只写「倾向」,禁写「必涨/必跌/一定」;disclaimer 必含「非预测」。
- 缺数据的维度记 0 且**不计入**有效维度数;绝不编造。
- 有效维度 < 2 时不得判「偏多」(单条证据不足以定向);
  但「偏空」允许单维度成立(风险侧保守优于激进)—— 这是**刻意的不对称**。
"""
from __future__ import annotations

from typing import Any, Optional

# ---- 规则参数(先定死;后续回测校准只能改参数,不得事后调门槛美化结论) ----
VOLUME_BULL_RATIO = 1.10     # 今日量 >= 5日均量 × 1.10 → 偏多
VOLUME_BEAR_RATIO = 0.90     # 今日量 <= 5日均量 × 0.90 → 偏空
SENTIMENT_BULL_PCT = 0.60    # 上涨占比 >= 60% → 偏多
SENTIMENT_BEAR_PCT = 0.40    # 上涨占比 <= 40% → 偏空
VOLUME_AVG_WINDOW = 5        # 量能对比窗口(前 N 日均量,不含今日)
MIN_KLINES_VOLUME = 6        # 今日 + 前 5 日
MIN_KLINES_MA10 = 11         # 算 MA10 至少 11 根
MIN_KLINES_MA20 = 21         # 算 MA20 至少 21 根
BULLISH_MIN_EFFECTIVE_DIMS = 2  # 判「偏多」所需的最少有效维度数
FLOW_TOTAL_EPS = 1e-9           # 板块资金净额归零阈值(浮点零和保护)


def _f(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _ma(closes: list[float], n: int) -> Optional[float]:
    """简单均线;数据不足返回 None"""
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _dim(key: str, label: str, score: int, state: str, detail: str) -> dict[str, Any]:
    return {"key": key, "label": label, "score": score, "state": state, "detail": detail}


# ============================ 各维度 ============================

def _volume_dim(klines: list[dict]) -> dict[str, Any]:
    """量能:今日量 vs 前 5 日均量"""
    if len(klines) < MIN_KLINES_VOLUME:
        return _dim("volume", "量能", 0, "missing", "K 线不足,无法比较量能")
    vols: list[float] = []
    for k in klines:
        v = _f(k.get("volume"))
        vols.append(v if v is not None else 0.0)
    today = vols[-1]
    avg5 = sum(vols[-1 - VOLUME_AVG_WINDOW:-1]) / VOLUME_AVG_WINDOW
    if avg5 <= 0:
        return _dim("volume", "量能", 0, "missing", "历史成交量为 0,无法比较量能")
    ratio = today / avg5
    if ratio >= VOLUME_BULL_RATIO:
        score = 1
    elif ratio <= VOLUME_BEAR_RATIO:
        score = -1
    else:
        score = 0
    detail = f"今日量为近 5 日均量的 {ratio:.2f} 倍"
    if score == 1:
        detail += ",放量"
    elif score == -1:
        detail += ",缩量"
    else:
        detail += ",量能平稳"
    return _dim("volume", "量能", score, "bull" if score > 0 else ("bear" if score < 0 else "flat"), detail)


def _sentiment_dim(sentiment: dict | None) -> dict[str, Any]:
    """涨跌家数"""
    if not isinstance(sentiment, dict):
        return _dim("sentiment", "涨跌家数", 0, "missing", "涨跌家数数据不可用")
    up = _f(sentiment.get("up_total"))
    down = _f(sentiment.get("down_total"))
    if up is None or down is None or (up + down) <= 0:
        return _dim("sentiment", "涨跌家数", 0, "missing", "涨跌家数数据不可用")
    ratio = up / (up + down)
    if ratio >= SENTIMENT_BULL_PCT:
        score = 1
    elif ratio <= SENTIMENT_BEAR_PCT:
        score = -1
    else:
        score = 0
    detail = f"上涨 {int(up)} 家 / 下跌 {int(down)} 家(上涨占比 {ratio * 100:.0f}%)"
    return _dim("sentiment", "涨跌家数", score, "bull" if score > 0 else ("bear" if score < 0 else "flat"), detail)


def _ma_dim(closes: list[float]) -> dict[str, Any]:
    """指数均线位置"""
    if len(closes) < MIN_KLINES_MA10:
        return _dim("ma", "指数均线", 0, "missing", "K 线不足,无法计算 MA10")
    close = closes[-1]
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    if ma5 is None or ma10 is None:
        return _dim("ma", "指数均线", 0, "missing", "均线数据不完整")
    if close > ma5 > ma10:
        score = 1
    elif close < ma5 < ma10:
        score = -1
    else:
        score = 0
    detail = f"收盘 {close:.2f},MA5 {ma5:.2f},MA10 {ma10:.2f}"
    return _dim("ma", "指数均线", score, "bull" if score > 0 else ("bear" if score < 0 else "flat"), detail)


def _flow_dim(sector_flows: list[dict] | None) -> dict[str, Any]:
    """板块资金(真实板块资金流,非估算)

    判定按**净流入总额符号**,不是「有无正流入」——
    「有正有负」蕴含「存在正流入」,按有无判定会让偏多与中性两档互相排斥。
    总额: >0 偏多 / <0 偏空 / ==0 中性。

    ⚠️ 两个诚实性要点(2026-10-21 复审发现,必须保留):
    1. **浮点零和**: [38.6, -12.4, -26.2] 的和是 3.55e-15 而非精确 0,
       直接用 `total > 0` 判会误判成偏多,并渲染出「净流入合计 0.00 亿」这种
       自相矛盾的文案。故用 FLOW_TOTAL_EPS 把 |total| < 1e-9 归一为 0。
    2. **全部板块净额都是 None** 时 = 根本没有板块资金数据,必须判 **missing**
       而不是 flat。否则会在完全没有该维度数据时对外宣称「4/4 维度规则推断」。
    """
    if not sector_flows:
        return _dim("flow", "板块资金", 0, "missing", "板块资金流数据不可用")
    total = 0.0
    valid = 0
    top: tuple[float, str] | None = None
    for f in sector_flows:
        if not isinstance(f, dict):
            continue
        net = _f(f.get("netamount_yi"))
        if net is None:
            continue
        valid += 1
        total += net
        if net > 0 and (top is None or net > top[0]):
            top = (net, str(f.get("name") or ""))
    if valid == 0:
        return _dim("flow", "板块资金", 0, "missing", "板块资金流无有效净额数据")
    if abs(total) < FLOW_TOTAL_EPS:
        total = 0.0
    if total > 0:
        # total > 0 必然蕴含至少一个 net > 0,故此处 top 一定非 None(无需 None 兜底分支)
        score = 1
        detail = f"板块资金净流入合计 {total:.2f} 亿,主攻 {top[1]} {top[0]:.2f} 亿"
    elif total < 0:
        score = -1
        detail = f"板块资金净流出合计 {abs(total):.2f} 亿,无主攻方向"
    else:
        score = 0
        detail = "板块资金多空抵消,无明确主攻方向"
    state = "bull" if score > 0 else ("bear" if score < 0 else "flat")
    return _dim("flow", "板块资金", score, state, detail)


# ============================ 关键位 ============================

def _key_levels(klines: list[dict], closes: list[float]) -> dict[str, Any]:
    """支撑 / 压力:全部取自真实日K,不做虚构点位"""
    close = closes[-1] if closes else None
    ma5 = _ma(closes, 5)
    ma10 = _ma(closes, 10)
    ma20 = _ma(closes, 20) if len(closes) >= MIN_KLINES_MA20 else None
    last = klines[-1] if klines else {}
    high = _f(last.get("high"))
    low = _f(last.get("low"))

    support: list[float] = []
    if ma5 is not None and close is not None and ma5 < close:
        support.append(round(ma5, 2))
    if low is not None:
        support.append(round(low, 2))

    resistance: list[float] = []
    if high is not None:
        resistance.append(round(high, 2))
    if ma20 is not None and close is not None and ma20 > close:
        resistance.append(round(ma20, 2))

    return {
        "close": round(close, 2) if close is not None else None,
        "ma5": round(ma5, 2) if ma5 is not None else None,
        "ma10": round(ma10, 2) if ma10 is not None else None,
        "ma20": round(ma20, 2) if ma20 is not None else None,
        "support": sorted(set(support)),
        "resistance": sorted(set(resistance)),
    }


# ============================ 主入口 ============================

def build_outlook(
    index_klines: list[dict],
    sentiment: dict | None,
    sector_flows: list[dict] | None,
) -> dict[str, Any]:
    """明日市场预期(纯函数)

    Args:
        index_klines: 上证指数升序日K,{date,open,high,low,close,volume}
        sentiment: {up_total, down_total, ...} 或 None
        sector_flows: [{name, netamount_yi}, ...] 或 None
    """
    klines = index_klines if isinstance(index_klines, list) else []
    closes: list[float] = []
    for k in klines:
        c = _f(k.get("close")) if isinstance(k, dict) else None
        if c is not None:
            closes.append(c)

    dims = [
        _volume_dim(klines),
        _sentiment_dim(sentiment),
        _ma_dim(closes),
        _flow_dim(sector_flows),
    ]
    score = sum(d["score"] for d in dims)
    effective = sum(1 for d in dims if d["state"] != "missing")

    if effective == 0:
        stance = "unknown"
    elif score >= 1 and effective >= BULLISH_MIN_EFFECTIVE_DIMS:
        stance = "bullish"
    elif score <= -1:
        stance = "bearish"
    else:
        stance = "neutral"

    stance_label = {
        "bullish": "偏多", "bearish": "偏空", "neutral": "震荡", "unknown": "数据不足",
    }[stance]
    degraded = effective < len(dims)
    degraded_reason = [
        f"{d['label']}数据缺失" for d in dims if d["state"] == "missing"
    ]

    return {
        "stance": stance,
        "stance_label": stance_label,
        "score": score,
        "dims_total": len(dims),
        "dims_effective": effective,
        "dims": dims,
        "key_levels": _key_levels(klines, closes),
        "disclaimer": (
            f"基于 {effective}/{len(dims)} 维度规则推断，非预测；仅作明日操作参考。"
        ),
        "degraded": degraded,
        "degraded_reason": degraded_reason,
    }


__all__ = ["build_outlook"]
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_outlook_service.py -q --no-header -p no:cacheprovider
```

Expected: 全部 PASS（本任务共 25 个用例，以你实际跑出来的为准）。

- [ ] **Step 5: 静态检查 + Commit**

```powershell
Set-Location 'D:\zga-study\rich\backend'
& '.\.venv\Scripts\python.exe' -m ruff check app/services/outlook_service.py tests/test_outlook_service.py
```
Expected: `All checks passed!`

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/services/outlook_service.py backend/tests/test_outlook_service.py
git commit -m "feat(outlook): 明日市场预期四维度规则推断(纯函数、零 LLM)

- 维度: 量能(上证日K volume)/ 涨跌家数 / 均线位置(MA5/MA10) / 板块资金
- 合成: 偏多需 >=2 有效维度(单证据不足定向);偏空允许单维度(不对称,风险侧保守)
- 关键位: MA5/今日低点作支撑,今日高点/MA20 作压力,全部取自真实日K
- 文案只写倾向 + 必带'非预测'标注;缺数据维度记 0 且不计入有效维度数"
```

---

## Task 3: 决策 → 明日预案转换（plan_item_builder）

**Files:**
- Create: `backend/app/services/plan_item_builder.py`
- Test: `backend/tests/test_plan_item_builder.py`
- Modify: `backend/app/services/decision_service.py`（blocked 动作补 `missing` 键 = 真正没满足的条件）
- Test: `backend/tests/test_decision_service.py`（补 1 条：blocked 动作必须带 `missing`）

**Interfaces:**
- Consumes: `build_decision` 的输出 dict（结构见「跨任务锁定的接口契约」）
- Produces: `build_items(decision, position) -> list[dict]`、`build_todos(decision) -> list[dict]`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_plan_item_builder.py`：

```python
"""决策 → 明日预案转换(纯函数、零 IO)设计文档 §4.4"""
from __future__ import annotations

import pytest

from app.services.plan_item_builder import build_items, build_todos


def _action(kind="entry", status="armed", price=10.0, label="支撑企稳建仓",
            condition="回踩 10.00 元不破时首仓建仓", basis=None):
    return {
        "kind": kind, "label": label, "condition": condition,
        "price": price, "basis": basis if basis is not None else [f"依据 {price}"],
        "status": status,
    }


class _Pos:
    """持仓视图(属性形状,与 services/position_status.resolve_position_status 同契约)"""

    def __init__(self, shares=0, avg_cost=0.0):
        self.shares = shares
        self.avg_cost = avg_cost


def _decision(actions=None, **kw):
    d = {
        "stock_code": "001896.SZ", "stock_name": "豫能控股",
        "verdict": "hold", "headline": "现价 9.92,等触发",
        "confidence": "medium", "role": "解套参考", "position_status": "loss",
        "actions": actions if actions is not None else [],
        "stop_loss": None, "position_pct": "解套优先",
        "do_not": [], "t_plan": {"suitable": False, "t_high": None, "t_low": None,
                                "amplitude_pct": None, "sell_trigger": "", "buyback_trigger": "",
                                "base_position_pct": "", "unsuitable_signals": "不合适",
                                "needs_position": False},
        "trend_state": {}, "market_env": {}, "data_quality": {"degraded": False},
    }
    d.update(kw)
    return d


# ---------------- 三路分流 ----------------

def test_armed_action_becomes_plan_item():
    d = _decision([_action(status="armed", price=9.62)])
    items = build_items(d, _Pos(600, 15.578))
    assert len(items) == 1
    it = items[0]
    assert it["item_kind"] == "entry"
    assert it["direction"] == "buy"
    assert it["trigger_price"] == 9.62
    assert it["status_now"] == "armed"
    assert it["basis"]


def test_now_action_does_not_enter_plan_items():
    d = _decision([_action(status="now", price=9.62)])
    assert build_items(d, None) == []


def test_now_action_goes_to_todos():
    d = _decision([_action(status="now", price=9.62, label="分批止盈")])
    todos = build_todos(d)
    assert len(todos) == 1
    assert todos[0]["label"] == "分批止盈"
    assert todos[0]["price"] == 9.62
    assert todos[0]["condition"]


def test_todos_and_items_never_overlap():
    """用**动作身份**(label + condition)判不重叠,不用价格。

    为什么不用价格:同一个价位可能同时出现在「今日待办」与「明日预案」
    (如止损动作 status=now 与 stop_loss 字段同价) —— 价格集合会误判成重叠,
    这条测试就永远抓不到真正的动作级回归。

    ⚠️ 比较前必须把 item 侧的「明日」前缀去掉:预案项的 label 带「明日」(那是明日预案),
    待办的不带(那是今日待办)。不剥前缀的话,同一动作在两个出口的 label 必然不等 →
    集合交恒为空 → 这条测试对「同一动作同时出现在两个出口」完全免疫,失去判别力。
    """
    d = _decision([_action(status="now", price=1.0, label="分批止盈"),
                   _action(status="armed", price=2.0, label="支撑企稳建仓")])
    item_keys = {(i["label"].removeprefix("明日"), i["trigger_condition"])
                 for i in build_items(d, None)}
    todo_keys = {(t["label"], t["condition"]) for t in build_todos(d)}
    assert not (item_keys & todo_keys)


def test_todos_and_items_never_overlap_even_with_same_price():
    """同价位、不同动作 → 仍必须不重叠(价格集合法在这里会误判)"""
    d = _decision([_action(status="now", price=9.62, label="分批止盈"),
                   _action(status="armed", price=9.62, label="支撑企稳建仓")])
    item_keys = {(i["label"].removeprefix("明日"), i["trigger_condition"])
                 for i in build_items(d, None)}
    todo_keys = {(t["label"], t["condition"]) for t in build_todos(d)}
    assert not (item_keys & todo_keys)
    assert len(item_keys) == 1 and len(todo_keys) == 1


def test_same_action_in_both_exports_is_detected():
    """判别力自检:同一个动作若同时出现在两个出口,身份键集合**必须**相交

    (这条测试保证上面两条不会因为「前缀/字段不一致」而恒真)
    """
    same = _action(status="now", price=9.62, label="分批止盈")
    d = _decision([same, dict(same, status="armed")])
    item_keys = {(i["label"].removeprefix("明日"), i["trigger_condition"])
                 for i in build_items(d, None)}
    todo_keys = {(t["label"], t["condition"]) for t in build_todos(d)}
    assert item_keys & todo_keys, "同一动作同时出现在两个出口时,身份键必须相交"


def test_blocked_action_becomes_unlock_item():
    d = _decision([_action(status="blocked", price=12.5,
                            basis=["压力位 12.50 元", "量能仅 0.90 倍,未达 1.50 倍确认标准"])])
    items = build_items(d, None)
    assert len(items) == 1
    it = items[0]
    assert it["item_kind"] == "unlock"
    assert it["status_now"] == "blocked"
    assert "量能" in it["invalid_if"]


# ---------------- 方向映射 ----------------

def test_direction_mapping_buy_kinds():
    for kind in ("entry", "add", "t_buyback"):
        d = _decision([_action(kind=kind, status="armed")])
        items = build_items(d, _Pos(100, 10.0))
        assert items and items[0]["direction"] == "buy", kind


def test_direction_mapping_sell_kinds():
    for kind in ("exit", "stop", "t_sell"):
        d = _decision([_action(kind=kind, status="armed")])
        items = build_items(d, _Pos(100, 10.0))
        assert items and items[0]["direction"] == "sell", kind


def test_watch_action_direction_none():
    d = _decision([_action(kind="watch", status="armed", price=None)])
    items = build_items(d, None)
    assert items[0]["direction"] == "none"


# ---------------- 止损 / 做T / 别动 ----------------

def test_stop_loss_item_only_when_has_position():
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    assert build_items(d, None) == []
    items = build_items(d, _Pos(600, 15.578))
    kinds = [i["item_kind"] for i in items]
    assert "stop" in kinds


def test_stop_loss_item_invalid_if():
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    items = build_items(d, _Pos(600, 15.578))
    stop = next(i for i in items if i["item_kind"] == "stop")
    assert stop["direction"] == "sell"
    assert stop["trigger_price"] == 9.62
    assert "9.62" in stop["invalid_if"]


def test_t_plan_splits_into_two_items():
    d = _decision(t_plan={
        "suitable": True, "t_high": 10.5, "t_low": 9.2, "amplitude_pct": 12.0,
        "sell_trigger": "冲高至 10.50 元附近卖出 T 仓", "buyback_trigger": "回落至 9.20 元附近买回",
        "base_position_pct": "≥50%", "unsuitable_signals": "", "needs_position": False,
    })
    items = build_items(d, _Pos(600, 15.578))
    tp = [i for i in items if i["item_kind"] in ("t_sell", "t_buyback")]
    assert len(tp) == 2
    sell = next(i for i in tp if i["item_kind"] == "t_sell")
    buy = next(i for i in tp if i["item_kind"] == "t_buyback")
    assert sell["direction"] == "sell" and sell["trigger_price"] == 10.5
    assert buy["direction"] == "buy" and buy["trigger_price"] == 9.2


def test_t_plan_skipped_when_not_suitable():
    d = _decision()   # suitable=False
    items = build_items(d, _Pos(600, 15.578))
    assert [i for i in items if i["item_kind"].startswith("t_")] == []


def test_t_plan_skipped_when_no_position():
    d = _decision(t_plan={
        "suitable": True, "t_high": 10.5, "t_low": 9.2, "amplitude_pct": 12.0,
        "sell_trigger": "s", "buyback_trigger": "b", "base_position_pct": "≥50%",
        "unsuitable_signals": "", "needs_position": False,
    })
    items = build_items(d, None)
    assert [i for i in items if i["item_kind"].startswith("t_")] == []


def test_dict_position_raises_instead_of_silently_skipping_position_items():
    """传 dict 必须**响亮失败**:静默当空仓会让持仓票的止损/做T子项整条消失"""
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    with pytest.raises(TypeError):
        build_items(d, {"shares": 600, "avg_cost": 15.578})


def test_none_position_is_not_an_error():
    """position=None 是合法输入(该票没持仓) —— 不能抛异常"""
    d = _decision([_action(status="armed", price=9.62)])
    assert build_items(d, None) != []


def test_do_not_items():
    d = _decision(do_not=["下跌通道中不要抄底", "距上次卖出仅 1 天,勿频繁操作"])
    items = build_items(d, _Pos(600, 15.578))
    dn = [i for i in items if i["item_kind"] == "do_not"]
    assert len(dn) == 2
    assert all(i["direction"] == "none" for i in dn)
    assert all(i["trigger_price"] is None for i in dn)


# ---------------- 失效条件计算 ----------------

def test_entry_invalid_if_uses_097():
    d = _decision([_action(kind="entry", status="armed", price=10.0)])
    items = build_items(d, None)
    assert "9.70" in items[0]["invalid_if"]


def test_exit_invalid_if_uses_103():
    d = _decision([_action(kind="exit", status="armed", price=12.03)])
    items = build_items(d, _Pos(100, 10.0))
    assert "12.39" in items[0]["invalid_if"]


def test_invalid_if_present_on_every_item():
    d = _decision(
        [_action(kind="entry", status="armed", price=10.0)],
        stop_loss={"price": 9.62, "basis": "b"},
        do_not=["别动"],
    )
    items = build_items(d, _Pos(100, 10.0))
    for it in items:
        assert it["invalid_if"], it


# ---------------- 边界 ----------------

def test_empty_actions_returns_empty_list():
    assert build_items(_decision([]), _Pos(100, 10.0)) == []


def test_action_with_none_price_yields_none_trigger():
    d = _decision([_action(kind="watch", status="armed", price=None)])
    items = build_items(d, None)
    assert items[0]["trigger_price"] is None


def test_basis_preserved_verbatim():
    basis = ["企稳价 9.62 元(现价 9.920 +3.1%)", "stabilize.state=true"]
    d = _decision([_action(status="armed", price=9.62, basis=basis)])
    items = build_items(d, None)
    assert items[0]["basis"] == basis


def test_unlock_uses_explicit_missing_when_provided():
    """决策层给了 missing → 解锁依据必须是**真正没满足的条件**,不是 basis 里的事实"""
    a = _action(status="blocked", price=9.92, label="补仓摊薄",
                basis=["持仓 600 股 @ 成本 15.58 元", "补 100 股后均价 9.87 元"])
    a["missing"] = ["下跌通道(趋势未破条件不成立)", "尚无企稳信号"]
    d = _decision([a])
    it = build_items(d, None)[0]
    assert it["item_kind"] == "unlock"
    assert "下跌通道" in it["invalid_if"]
    assert "尚无企稳信号" in it["invalid_if"]
    assert "均价" not in it["invalid_if"]      # ← 事实不是条件


def test_unlock_invalid_if_has_no_duplicate_suffix():
    """缺失依据里已含「未达」就别再叠一句「未满足则不解锁」"""
    a = _action(status="blocked", price=12.5,
                basis=["压力位 12.50 元", "量能仅 0.90 倍,未达 1.50 倍确认标准"])
    a["missing"] = ["量能仅 0.90 倍,未达 1.50 倍确认标准"]
    it = build_items(_decision([a]), None)[0]
    assert it["invalid_if"].count("未满足") == 0
    assert it["invalid_if"].endswith("则不解锁")


def test_stop_item_wording_reflects_already_triggered_stop():
    """止损位今天已被击穿 → 明日预案不能写「跌破 X 元无条件减仓」(那是过期建议)"""
    now_stop = _action(kind="stop", status="now", price=9.62, label="无条件止损")
    d = _decision([now_stop], stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    items = build_items(d, _Pos(600, 15.578))
    stop = next(i for i in items if i["item_kind"] == "stop")
    assert "已跌破 9.62" in stop["trigger_condition"]
    assert "跌破 9.62 元无条件减仓" not in stop["trigger_condition"]


def test_stop_item_wording_normal_when_stop_not_yet_triggered():
    """止损位未击穿 → 正常写「跌破 X 元无条件减仓」"""
    d = _decision(stop_loss={"price": 9.62, "basis": "参考支撑 9.92 元 × 0.97"})
    items = build_items(d, _Pos(600, 15.578))
    stop = next(i for i in items if i["item_kind"] == "stop")
    assert stop["trigger_condition"] == "跌破 9.62 元无条件减仓"


def test_every_item_carries_source():
    """溯源字段(spec §4.4.4):每条预案都要能说清来自决策引擎的哪一块"""
    blocked = _action(status="blocked", price=12.5, label="放量突破追进",
                      basis=["压力位 12.50 元", "量能仅 0.90 倍,未达 1.50 倍确认标准"])
    d = _decision([_action(status="armed", price=9.62), blocked],
                  stop_loss={"price": 9.62, "basis": "b"},
                  t_plan={"suitable": True, "t_high": 10.5, "t_low": 9.2,
                          "amplitude_pct": 12.0, "sell_trigger": "s", "buyback_trigger": "b",
                          "base_position_pct": "≥50%", "unsuitable_signals": "",
                          "needs_position": False},
                  do_not=["下跌通道中不要抄底"])
    items = build_items(d, _Pos(600, 15.578))
    assert items, "至少要有一条"
    assert all(i.get("source") for i in items)
    by_kind = {i["item_kind"]: i["source"] for i in items}
    assert by_kind["entry"] == "decision.actions"
    assert by_kind["stop"] == "decision.stop_loss"
    assert by_kind["t_sell"] == "decision.t_plan"
    assert by_kind["do_not"] == "decision.do_not"
    assert by_kind["unlock"] == "decision.actions"


def test_item_labels_use_mingri_wording():
    """spec §4.4.5:预案项措辞统一用「明日」,避免与生成时点混淆"""
    d = _decision([_action(status="armed", price=9.62)],
                  stop_loss={"price": 9.62, "basis": "b"},
                  t_plan={"suitable": True, "t_high": 10.5, "t_low": 9.2,
                          "amplitude_pct": 12.0, "sell_trigger": "s", "buyback_trigger": "b",
                          "base_position_pct": "≥50%", "unsuitable_signals": "",
                          "needs_position": False},
                  do_not=["下跌通道中不要抄底"])
    items = build_items(d, _Pos(600, 15.578))
    assert all(i["label"].startswith("明日") for i in items)


def test_malformed_shares_raises_instead_of_silently_no_position():
    """形状对但值畸形(如 'abc')→ 响亮失败,不能静默当成空仓(否则止损/做T整条消失)"""
    d = _decision(stop_loss={"price": 9.62, "basis": "b"})
    with pytest.raises(TypeError):
        build_items(d, _Pos("abc", 15.578))


def test_nan_shares_raises_instead_of_silently_no_position():
    """NaN 与任何数比较都是 False → 会被静默当成「无持仓」,必须响亮失败"""
    d = _decision(stop_loss={"price": 9.62, "basis": "b"})
    with pytest.raises(TypeError):
        build_items(d, _Pos(float("nan"), 15.578))
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_plan_item_builder.py -q --no-header -p no:cacheprovider
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.plan_item_builder'`

- [ ] **Step 3: 实现**

创建 `backend/app/services/plan_item_builder.py`：

```python
"""决策输出 → 明日操作预案(纯函数、零 IO、零 LLM)

设计文档 §4.4。

**核心分流规则**:
| 决策输出 | 去向 |
|---|---|
| actions status="now"    | **不进明日预案** → 今日复盘「未执行待办」(条件已过期) |
| actions status="armed"  | 明日预案主力 |
| actions status="blocked"| 明日预案「解锁条件」 |
| stop_loss               | 明日预案(仅持仓票) |
| t_plan                  | 明日预案(仅持仓票,拆上沿/下沿两条) |
| do_not[]                | 明日预案「别动」 |

**为什么 now 不进明日预案**:它的语义是「此刻条件已满足,此刻就该做」。
写进明日预案就是一条**已经过期的建议**——这正是股民复盘里最常见的自欺
("我有个计划"但其实条件早就到了没做)。必须显式推到复盘待办,逼用户面对。
"""
from __future__ import annotations

from typing import Any, Optional

# 决策引擎 kind → 预案方向
# ⚠️ 只列**会被查询**的 kind。unlock / do_not 不在此表:
# unlock 项的 direction 继承被它派生的原动作 kind;do_not 项恒为 none(直接写死)。
KIND_DIRECTION: dict[str, str] = {
    "entry": "buy",
    "add": "buy",
    "t_buyback": "buy",
    "exit": "sell",
    "stop": "sell",
    "t_sell": "sell",
    "watch": "none",
}

# 失效条件系数(显式四则运算,不是拍脑袋的魔法数)
ENTRY_INVALID_FACTOR = 0.97   # 跌破 触发价×0.97 → 建仓预案作废
EXIT_INVALID_FACTOR = 1.03    # 回落至 触发价×1.03 以上未达成 → 不追高


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _has_position(position) -> bool:
    """持仓判定:`position` 须为含 `.shares` **属性**的对象。

    ⚠️ 契约统一(2026-10-21 跨任务裁决):本模块与
    `services/position_status.resolve_position_status` **统一用属性形状**,
    不用 dict —— 后者的契约已写进 docstring 并通过 Task 1 复审,
    改它要动既有代码(且 `api/diagnose.py` 在用);而本模块是新代码,改它零成本。
    接线层(Task 6)造一个 PositionView 同时传给两者。

    **传 dict 抛 TypeError(不静默降级)**:dict 没有 `.shares` 属性,
    会被读成 0 股 → 持仓票的「止损」与两条「做T」子项被**静默漏掉** →
    用户拿到的计划里根本没有止损,复盘时却显示「按计划执行」。
    这种漏项比报错更难发现,所以这里选择**响亮地失败**
    (与 `position_status.resolve_position_status` 的契约处理一致)。
    """
    if position is None:
        return False
    if not hasattr(position, "shares"):
        raise TypeError(
            "position 须为含 .shares 属性的对象(如 PositionView / Position),"
            f"收到 {type(position).__name__} —— 传 dict 会静默漏掉止损与做T子项"
        )
    shares = getattr(position, "shares", 0)
    if not isinstance(shares, (int, float)):
        # 形状对了但**值畸形**(如 'abc' / None):同样必须响亮失败。
        # 静默当成「无持仓」会让止损与做T子项整条消失 —— 与 position_status 的契约一致
        # (那里 `position.shares <= 0` 特意放在 try 之外,字符串会抛 TypeError)。
        raise TypeError(
            f"position.shares 须为数值(与 position_status 同契约),"
            f"收到 {type(shares).__name__}: {shares!r}"
        )
    if shares != shares:  # NaN:与任何数比较都是 False → 会被静默当成「无持仓」
        raise TypeError(f"position.shares 不得为 NaN: {shares!r}")
    return float(shares) > 0


def _invalid_if(item_kind: str, direction: str, price: float | None,
                label: str) -> str:
    """算失效条件(不得为空,除非是恒成立的别动项)"""
    if item_kind == "do_not":
        return "该别动项恒成立,明日仍然有效"
    if price is None:
        return f"触发价未知,{label}不执行"
    if direction == "buy":
        cut = round(price * ENTRY_INVALID_FACTOR, 2)
        return f"跌破 {cut:.2f} 则本条作废(不接下跌中的刀)"
    if direction == "sell":
        back = round(price * EXIT_INVALID_FACTOR, 2)
        return f"回落至 {back:.2f} 以上未达成,明日不追高"
    return f"{label}条件不满足则不执行"


def _item(
    stock_code: str,
    stock_name: str | None,
    item_kind: str,
    direction: str,
    label: str,
    trigger_price: float | None,
    trigger_condition: str,
    basis: list[str],
    invalid_if: str,
    status_now: str,
    source: str = "decision.actions",
) -> dict[str, Any]:
    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "item_kind": item_kind,
        "direction": direction,
        "label": label,
        "trigger_price": trigger_price,
        "trigger_condition": trigger_condition,
        "basis": basis,
        "invalid_if": invalid_if,
        "status_now": status_now,
        "source": source,          # 溯源用(spec §4.4.4)
        "fulfillment": "pending",
        "fulfillment_note": "",
    }


def _split_actions(decision: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """把 actions 按 status 拆成 (now, armed, blocked)三组"""
    now: list[dict] = []
    armed: list[dict] = []
    blocked: list[dict] = []
    for a in decision.get("actions") or []:
        if not isinstance(a, dict):
            continue
        st = a.get("status")
        if st == "now":
            now.append(a)
        elif st == "armed":
            armed.append(a)
        elif st == "blocked":
            blocked.append(a)
    return now, armed, blocked


def build_todos(decision: dict) -> list[dict]:
    """今日复盘的「未执行待办」:条件已满足(now)但用户还没做的动作"""
    now, _, _ = _split_actions(decision)
    code = decision.get("stock_code") or ""
    name = decision.get("stock_name")
    out: list[dict] = []
    for a in now:
        out.append({
            "stock_code": code,
            "stock_name": name,
            "label": a.get("label") or "",
            "condition": a.get("condition") or "",
            "price": _f(a.get("price")),
            "basis": list(a.get("basis") or []),
        })
    return out


def build_items(decision: dict, position) -> list[dict]:
    """明日操作预案项(纯函数)

    `position` 须为含 `.shares` **属性**的对象(或 None)——与
    `services/position_status.resolve_position_status` 同契约(属性形状,不是 dict)。
    """
    code = decision.get("stock_code") or ""
    name = decision.get("stock_name")
    _, armed, blocked = _split_actions(decision)
    items: list[dict] = []

    # 1) armed → 明日预案主力
    for a in armed:
        kind = str(a.get("kind") or "watch")
        direction = KIND_DIRECTION.get(kind, "none")
        price = _f(a.get("price"))
        basis = list(a.get("basis") or [])
        raw_label = a.get("label") or ""
        items.append(_item(
            code, name, kind, direction,
            f"明日{raw_label}", price,
            a.get("condition") or "", basis,
            _invalid_if(kind, direction, price, raw_label),
            "armed",
            "decision.actions",
        ))

    # 2) blocked → 解锁条件(方向继承原动作)
    for a in blocked:
        kind = str(a.get("kind") or "watch")
        direction = KIND_DIRECTION.get(kind, "none")
        price = _f(a.get("price"))
        basis = list(a.get("basis") or [])
        raw_label = a.get("label") or ""
        # 缺的依据:优先用决策层显式给出的 `missing`(那是**真正没满足的条件**);
        # 没有才退回「除首条(价位)外的其余依据」。
        # 为什么必须有 missing:真实 blocked 动作(如 L4 补仓摊薄)的 basis 是两条**事实**
        # (「持仓 600 股 @ 成本 15.58 元」「补 100 股后均价 9.87 元」),
        # 把 basis[1:] 当缺失条件会写出「补 100 股后均价 9.87 元未满足则不解锁」——
        # 那不是条件,是事实,用户读到的是假前提。
        explicit = [str(x) for x in (a.get("missing") or []) if str(x)]
        if explicit:
            missing = explicit
        else:
            missing = basis[1:] if len(basis) > 1 else basis
        unlock_txt = "、".join(missing) if missing else f"{raw_label}的前置条件"
        # 文案去重复:缺失依据里已经写了「未达/未满足/未站回/尚未」就别再叠一句
        if any(k in unlock_txt for k in ("未达", "未满足", "未站回", "尚未")):
            invalid_txt = f"{unlock_txt}则不解锁"
        else:
            invalid_txt = f"{unlock_txt}未满足则不解锁"
        items.append(_item(
            code, name, "unlock", direction,
            f"明日解锁后:{raw_label}",
            price,
            a.get("condition") or "", basis,
            invalid_txt,
            "blocked",
            "decision.actions",
        ))

    # 3) 止损(仅持仓票)
    stop = decision.get("stop_loss")
    if isinstance(stop, dict) and _has_position(position):
        price = _f(stop.get("price"))
        # 止损位**已被击穿**时(决策层同时给了 status=="now" 的止损动作),
        # 明日预案不能再写「跌破 X 元无条件减仓」—— 那个条件今天就已经成立,
        # 写进明日预案就是一条过期建议。改成「仍在 X 下方则继续减仓」。
        already = any(
            str(a.get("kind") or "") == "stop"
            and a.get("status") == "now"
            and price is not None
            and _f(a.get("price")) == price
            for a in (decision.get("actions") or [])
            if isinstance(a, dict)
        )
        if price is not None:
            cond = (
                f"已跌破 {price:.2f} 元,明日仍在该位置下方则继续无条件减仓"
                if already else f"跌破 {price:.2f} 元无条件减仓"
            )
        else:
            cond = "跌破止损位无条件减仓"
        items.append(_item(
            code, name, "stop", "sell", "明日止损",
            price,
            cond,
            [stop.get("basis") or ""],
            (f"收盘站回 {price:.2f} 元上方则明日不看止损" if price is not None
             else "止损位未知,明日不执行"),
            "armed",
            "decision.stop_loss",
        ))

    # 4) 做T(仅持仓票;拆上沿/下沿两条)
    t_plan = decision.get("t_plan")
    if isinstance(t_plan, dict) and t_plan.get("suitable") and _has_position(position):
        base = t_plan.get("base_position_pct") or ""
        th = _f(t_plan.get("t_high"))
        tl = _f(t_plan.get("t_low"))
        amp = t_plan.get("amplitude_pct")
        basis = [f"T 区间宽度 {amp}%"] if amp is not None else []
        if base:
            basis.append(f"底仓要求 {base}")
        if th is not None:
            items.append(_item(
                code, name, "t_sell", "sell", "明日做T减仓",
                th, t_plan.get("sell_trigger") or "", list(basis),
                (f"上沿 {th:.2f} 未触及则不做减仓;下沿 {tl:.2f} 未触及则不做回补"
                 if tl is not None else "上沿未触及则不做减仓"),
                "armed",
                "decision.t_plan",
            ))
        if tl is not None:
            items.append(_item(
                code, name, "t_buyback", "buy", "明日做T回补",
                tl, t_plan.get("buyback_trigger") or "", list(basis),
                (f"下沿 {tl:.2f} 未触及则不做回补;上沿 {th:.2f} 未触及则今日只减不接"
                 if th is not None else "下沿未触及则不做回补"),
                "armed",
                "decision.t_plan",
            ))

    # 5) 别动清单
    for txt in decision.get("do_not") or []:
        if not txt:
            continue
        items.append(_item(
            code, name, "do_not", "none", "明日别动", None,
            str(txt), [str(txt)],
            "该别动项恒成立,明日仍然有效",
            "armed",
            "decision.do_not",
        ))

    return items


__all__ = ["build_items", "build_todos"]
```

- [ ] **Step 3b: 决策层显式产出「真正没满足的条件」(改既有文件)**

`plan_item_builder` 的解锁依据优先读 `action["missing"]`（决策层给的缺失条件）。
决策层必须真的产出这个键,否则转换层只能猜 `basis[1:]` —— 而真实 blocked 动作
（L4 补仓摊薄）的 basis 是**两条事实**,不是缺失条件,猜出来的解锁依据是假前提。

改 `backend/app/services/decision_service.py` 两处 blocked 动作:

```python
    # C3 突破确认(judge_entry 内)
    else:
        status = "blocked"
        basis_extra = [f"量能仅 {vol_ratio:.2f} 倍,未达 {ENTRY_MIN_VOLUME_RATIO} 倍确认标准"]
    actions.append(_guard({
        "kind": "entry",
        ...
        "basis": [f"压力位 {pressure:.2f} 元"] + basis_extra,
        "missing": basis_extra,          # ← 新增:真正没满足的条件
        "status": status,
    }))
```

```python
    # L4 补仓摊薄(judge_loss_plan 内)
    actions.append({
        "kind": "add",
        "label": "补仓摊薄",
        ...
        "basis": [
            f"持仓 {shares} 股 @ 成本 {cost:.2f} 元",
            f"补 {add_shares} 股后均价 {new_cost:.2f} 元",
        ],
        "missing": reasons,               # ← 新增:真正没满足的条件(下跌通道/无企稳/大盘偏冷)
        "status": "now" if not reasons else "blocked",
    })
```

- `missing` 是**加键**,不改任何既有键的值 → 既有消费方(前端 DecisionCard、api/stock.py)不受影响。
- 只有 blocked 语义才需要它;`now` / `armed` 动作可以不带该键(转换层会忽略)。

在 `backend/tests/test_decision_service.py` 补 1 条测试(L4 补仓摊薄 blocked 时):
断言该动作带 `missing` 键,且 `missing` 内容是**条件**(如「下跌通道」「企稳」「大盘」)
而不是 basis 里那种事实(「持仓 600 股」「均价」)。

- [ ] **Step 4: 运行测试确认通过**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_plan_item_builder.py -q --no-header -p no:cacheprovider
```

Expected: 全部 PASS（32 passed）。

- [ ] **Step 5: 静态检查 + Commit**

```powershell
Set-Location 'D:\zga-study\rich\backend'
& '.\.venv\Scripts\python.exe' -m ruff check app/services/plan_item_builder.py tests/test_plan_item_builder.py
```
Expected: `All checks passed!`

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/services/plan_item_builder.py backend/tests/test_plan_item_builder.py
git commit -m "feat(plan): 决策→明日预案转换(纯函数、零 IO)

- 三路分流: now→复盘待办(已过期,不写进明日) / armed→预案主力 / blocked→解锁条件
- 止损与做T仅对持仓票生成;做T拆上沿(减)/下沿(接)两条独立子项
- 每条预案必带 invalid_if(买: 触发价×0.97 作废;卖: 触发价×1.03 不追高)
- build_items 与 build_todos 是同一份 decision 的两个出口,动作不重叠"
```

---

## Task 4: 兑现比对（fulfillment_checker）

**Files:**
- Create: `backend/app/services/fulfillment_checker.py`
- Test: `backend/tests/test_fulfillment_checker.py`

**Interfaces:**
- Consumes: 预案项 list、目标日 K 线 dict、流水 list
- Produces: `check_fulfillment(items, target_klines, transactions) -> list[dict]`、`summarize_fulfillment(items) -> dict`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_fulfillment_checker.py`：

```python
"""昨日预案 × 今日行情/流水 → 兑现状态(纯函数、零 IO)设计文档 §4.5"""
from __future__ import annotations

from app.services.fulfillment_checker import check_fulfillment, summarize_fulfillment


def _item(code="001896.SZ", kind="entry", direction="buy", price=9.62, label="建仓"):
    return {
        "stock_code": code, "stock_name": "豫能控股", "item_kind": kind,
        "direction": direction, "label": label, "trigger_price": price,
        "trigger_condition": "c", "basis": ["b"], "invalid_if": "i",
        "status_now": "armed", "fulfillment": "pending", "fulfillment_note": "",
    }


def _kline(high=10.0, low=9.0, close=9.5, open_=9.2):
    return {"date": "2026-10-22", "open": open_, "high": high, "low": low, "close": close}


def _txn(code="001896.SZ", action="buy", price=9.5, shares=100):
    return {"stock_code": code, "action": action, "shares": shares,
            "price": price, "trade_date": "2026-10-22"}


# ---------------- 触及判定 ----------------

def test_buy_touched_when_low_reaches_trigger():
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.5)]}, [])
    assert out[0]["fulfillment"] == "touched"


def test_buy_missed_when_low_above_trigger():
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.70)]}, [])
    assert out[0]["fulfillment"] == "missed"


def test_sell_touched_when_high_reaches_trigger():
    out = check_fulfillment([_item(kind="exit", direction="sell", price=12.03)],
                            {"001896.SZ": [_kline(high=12.5)]}, [])
    assert out[0]["fulfillment"] == "touched"


def test_sell_missed_when_high_below_trigger():
    out = check_fulfillment([_item(kind="exit", direction="sell", price=12.03)],
                            {"001896.SZ": [_kline(high=11.9)]}, [])
    assert out[0]["fulfillment"] == "missed"


def test_none_direction_is_na():
    out = check_fulfillment([_item(kind="do_not", direction="none", price=None)],
                            {"001896.SZ": [_kline()]}, [])
    assert out[0]["fulfillment"] == "n_a"


def test_no_kline_data_treated_as_missed_not_touched():
    out = check_fulfillment([_item(direction="buy", price=9.62)], {}, [])
    assert out[0]["fulfillment"] == "missed"


# ---------------- 执行判定(优先于触及) ----------------

def test_executed_when_buy_transaction_present():
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.7)]},
                            [_txn(action="buy")])
    assert out[0]["fulfillment"] == "executed"


def test_executed_when_sell_transaction_present():
    out = check_fulfillment([_item(kind="exit", direction="sell", price=12.03)],
                            {"001896.SZ": [_kline(high=11.0)]},
                            [_txn(action="sell")])
    assert out[0]["fulfillment"] == "executed"


def test_transaction_for_other_stock_ignored():
    # ⚠️ 脚手架数字必须是 low=9.5(<= 触发价 9.62 → 触及):写 9.7 会与
    # test_buy_missed_when_low_above_trigger(同 9.70 → missed)构成同输入两期望的互斥断言
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.5)]},
                            [_txn(code="000807.SZ", action="buy")])
    assert out[0]["fulfillment"] == "touched"


# ---------------- T 计划双子项 ----------------

def test_t_plan_sell_and_buyback_checked_independently():
    items = [
        _item(kind="t_sell", direction="sell", price=10.5, label="做T减仓"),
        _item(kind="t_buyback", direction="buy", price=9.2, label="做T回补"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.8, low=9.5)]}, [])
    by_kind = {i["item_kind"]: i for i in out}
    assert by_kind["t_sell"]["fulfillment"] == "touched"
    assert by_kind["t_buyback"]["fulfillment"] == "missed"


def test_t_plan_buyback_executed_by_buy_transaction():
    items = [
        _item(kind="t_sell", direction="sell", price=10.5, label="做T减仓"),
        _item(kind="t_buyback", direction="buy", price=9.2, label="做T回补"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.5)]},
                            [_txn(action="buy", price=9.1)])
    by_kind = {i["item_kind"]: i for i in out}
    assert by_kind["t_buyback"]["fulfillment"] == "executed"
    assert by_kind["t_sell"]["fulfillment"] == "missed"


# ---------------- 纪律问题 ----------------

def test_discipline_violation_flagged_when_do_not_but_traded():
    items = [_item(kind="do_not", direction="none", price=None, label="别动")]
    out = check_fulfillment(items, {"001896.SZ": [_kline()]}, [_txn(action="buy")])
    assert out[0]["fulfillment"] == "executed"
    assert "纪律问题" in out[0]["fulfillment_note"]


def test_discipline_violation_flagged_when_unlock_blocked_but_traded():
    items = [_item(kind="unlock", direction="buy", price=12.5, label="解锁后建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline()]}, [_txn(action="buy")])
    assert out[0]["fulfillment"] == "executed"
    assert "纪律问题" in out[0]["fulfillment_note"]


def test_do_not_with_sell_operation_also_flagged():
    """别动项:买卖任一方向的操作都算违规(spec §4.5 第四步:「有该票的买卖操作」)"""
    items = [_item(kind="do_not", direction="none", price=None, label="别动")]
    out = check_fulfillment(items, {"001896.SZ": [_kline()]}, [_txn(action="sell")])
    assert out[0]["fulfillment"] == "executed"
    assert "纪律问题" in out[0]["fulfillment_note"]


def test_unlock_without_operation_is_not_counted_as_gap():
    """解锁类(未解锁)本来就不该执行 —— 没操作记 n_a,不计入统计(spec §4.5.4)"""
    items = [_item(kind="unlock", direction="buy", price=12.5, label="解锁后建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(low=9.0)]}, [])
    assert out[0]["fulfillment"] == "n_a"


def test_t_buyback_not_executed_when_bought_above_target_price():
    """T 回补按**价格区间**匹配(spec §4.5):买价高于下沿×1.02 → 不算按计划回补"""
    items = [_item(kind="t_buyback", direction="buy", price=9.2, label="做T回补")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.4)]},
                            [_txn(action="buy", price=9.5)])
    assert out[0]["fulfillment"] == "missed"


# ---------------- 其它 ----------------

def test_input_items_not_mutated():
    items = [_item(direction="buy", price=9.62)]
    snapshot = [dict(i) for i in items]
    check_fulfillment(items, {"001896.SZ": [_kline(low=9.5)]}, [])
    assert items == snapshot


def test_empty_items_returns_empty():
    assert check_fulfillment([], {}, []) == []


def test_transaction_without_price_still_counts_as_executed():
    out = check_fulfillment([_item(direction="buy", price=9.62)],
                            {"001896.SZ": [_kline(low=9.7)]},
                            [{"stock_code": "001896.SZ", "action": "buy", "shares": 100,
                              "price": None, "trade_date": "2026-10-22"}])
    assert out[0]["fulfillment"] == "executed"


def test_t_item_without_trigger_price_does_not_raise():
    """T 子项没有触发价时不能炸:price×容差 会 TypeError,必须先判 price is None"""
    items = [_item(kind="t_sell", direction="sell", price=None, label="做T减仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline()]}, [])
    assert out[0]["fulfillment"] == "n_a"


# ---------------- 流水归属规则(spec §4.5.2.1:一条流水只归一条预案) ----------------

def test_single_transaction_consumed_by_only_one_plan():
    """同票两条同向预案 + 一笔流水 → 只能有一条 executed,另一条不许白嫖"""
    items = [
        _item(kind="entry", direction="buy", price=9.62, label="建仓"),
        _item(kind="add", direction="buy", price=9.90, label="加仓"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.95)]},
                            [_txn(action="buy", price=9.62)])
    assert out[0]["fulfillment"] == "executed"
    assert out[1]["fulfillment"] == "missed"


def test_t_item_price_match_takes_priority_over_plain_plan():
    """T 子项按价格区间硬匹配 → 优先于同向的普通预案拿走流水"""
    items = [
        _item(kind="entry", direction="buy", price=9.60, label="建仓"),
        _item(kind="t_buyback", direction="buy", price=9.20, label="做T回补"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.7)]},
                            [_txn(action="buy", price=9.10)])
    by_kind = {i["item_kind"]: i for i in out}
    assert by_kind["t_buyback"]["fulfillment"] == "executed"
    assert by_kind["entry"]["fulfillment"] == "missed"


def test_multiple_candidates_pick_closest_price():
    """同票同向多笔流水 → 取成交价与触发价最接近的那笔"""
    items = [_item(kind="entry", direction="buy", price=8.60, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=9.2, low=8.0)]},
                            [_txn(action="buy", price=8.30),
                             _txn(action="buy", price=8.00)])
    assert out[0]["fulfillment"] == "executed"
    assert "8.30" in out[0]["fulfillment_note"]
    assert "8.00" not in out[0]["fulfillment_note"]


def test_transaction_without_price_fallback_disclosed():
    """成交价缺失 → 兜底消费并在 note 披露(不能装作知道是哪条预案)"""
    items = [_item(kind="entry", direction="buy", price=9.62, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.3)]},
                            [{"stock_code": "001896.SZ", "action": "buy",
                              "shares": 100, "price": None,
                              "trade_date": "2026-10-22"}])
    assert out[0]["fulfillment"] == "executed"
    assert "成交价缺失" in out[0]["fulfillment_note"]


def test_discipline_item_does_not_consume_transaction():
    """纪律类不参与流水归属 —— 同一笔操作可同时构成纪律违规与别的预案的执行"""
    items = [
        _item(kind="do_not", direction="none", price=None, label="别动"),
        _item(kind="entry", direction="buy", price=9.62, label="建仓"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.3)]},
                            [_txn(action="buy", price=9.62)])
    by_kind = {i["item_kind"]: i for i in out}
    assert by_kind["do_not"]["fulfillment"] == "executed"
    assert "纪律问题" in by_kind["do_not"]["fulfillment_note"]
    assert by_kind["entry"]["fulfillment"] == "executed"


def test_deviation_beyond_3pct_disclosed_in_note():
    """成交价与触发价偏离 >3% → note 里看得见(追高买/提前卖)"""
    items = [_item(kind="entry", direction="buy", price=10.00, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.5, low=9.9)]},
                            [_txn(action="buy", price=10.40)])
    assert out[0]["fulfillment"] == "executed"
    assert "不符" in out[0]["fulfillment_note"]


def test_deviation_within_3pct_not_disclosed():
    """偏离在 3% 以内 → 不披露(避免把按计划执行也标成不符)"""
    items = [_item(kind="entry", direction="buy", price=10.00, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.5, low=9.9)]},
                            [_txn(action="buy", price=10.20)])
    assert out[0]["fulfillment"] == "executed"
    assert "不符" not in out[0]["fulfillment_note"]


def test_deviation_exactly_3pct_not_disclosed():
    """恰好 3% 偏离 → 不披露(**浮点边界**,正是 `_EPS` 存在的原因)

    触发价 10.00 / 成交 10.30:数学上正好 3%,但浮点表示下
    `abs(10.30 - 10.00) = 0.30000000000000071` > `10.00 * 0.03 = 0.29999999999999999`。
    没有 `_EPS` 就会把它误判成「超过 3%」而披露 —— 恰好 3% 不该披露。
    """
    items = [_item(kind="entry", direction="buy", price=10.00, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.5, low=9.9)]},
                            [_txn(action="buy", price=10.30)])
    assert out[0]["fulfillment"] == "executed"
    assert "不符" not in out[0]["fulfillment_note"]


def test_t_buyback_boundary_price_within_epsilon_counts_as_executed():
    """浮点容差:买价 9.384 与下沿 9.2×1.02(=9.383999999999999) 差 1e-15 → 算按计划回补"""
    items = [_item(kind="t_buyback", direction="buy", price=9.20, label="做T回补")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.4)]},
                            [_txn(action="buy", price=9.384)])
    assert out[0]["fulfillment"] == "executed"


# ---------------- 统计口径 ----------------

def test_summarize_counts_every_state():
    """统计口径:四态各计各的(spec §4.5.4)"""
    items = [
        {**(_item(direction="buy", price=9.62)), "fulfillment": "executed"},
        {**(_item(direction="sell", price=12.0)), "fulfillment": "touched"},
        {**(_item(direction="buy", price=9.9)), "fulfillment": "missed"},
        {**(_item(kind="do_not", direction="none", price=None)), "fulfillment": "n_a"},
    ]
    s = summarize_fulfillment(items)
    assert s["total"] == 4
    assert s["executed"] == 1
    assert s["touched"] == 1
    assert s["missed"] == 1
    assert s["na"] == 1
    assert s["discipline"] == 0


def test_summarize_flags_discipline_as_most_severe():
    """纪律问题优先级最高(spec §4.5.4)"""
    items = [
        {**(_item(direction="buy", price=9.62)), "fulfillment": "executed",
         "fulfillment_note": "⚠️ 纪律问题:昨日标记别动/未解锁,今日仍有操作"},
        {**(_item(direction="sell", price=12.0)), "fulfillment": "touched"},
    ]
    s = summarize_fulfillment(items)
    assert s["discipline"] == 1
    assert s["verdict_label"] == "存在纪律问题"
    assert s["verdict_level"] == "danger"
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_fulfillment_checker.py -q --no-header -p no:cacheprovider
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.fulfillment_checker'`

- [ ] **Step 3: 实现**

创建 `backend/app/services/fulfillment_checker.py`：

```python
"""昨日预案 × 今日行情/流水 → 兑现状态(纯函数、零 IO、零 LLM)

设计文档 §4.5。

**记法**:R = 被检查的日报日(R 日报的 items 是为 R+1 定下的);
R+1 = 兑现判定日。

**诚实性**:"未触发"不评价对错。计划说"跌破 9.62 止损",当天最低 9.70
没跌破 —— 这不是"止损错了",而是"不该触发"。算成错误会污染决策档案。

**归属规则(spec §4.5.3 第一步细化,2026-10-21 T4 评审后补)**:
一条流水最多被一条预案消费。
  1. **T 子项硬匹配**(按价格区间):t_sell 卖出价 ≥ 上沿×0.98、t_buyback 买价 ≤ 下沿×1.02;
  2. **其余预案按方向**匹配**尚未被消费**的流水,多条候选时取「成交价与触发价最接近」的一条;
  3. 成交价缺失的流水**不能证明是哪条预案** → 只在没有带价候选时兜底,并在 note 里披露;
  4. 纪律类(do_not/unlock)**不参与流水归属** —— 它的「executed」表示「当日有操作(违规)」,
     同一笔操作也可能同时构成别的预案的执行,两个结论都成立,不该互相吞掉。

为什么:只看方向时,同票多笔同向预案会把「T 回补的那笔买入」也算成「建仓预案已执行」——
那种假阳性会直接污染复盘档案,而本模块存在的意义就是不污染。

**输入范围约束**:传入的 target_klines 与 transactions **必须只含目标日(R+1)的数据**。
本模块是纯函数、零 IO,不做日期过滤(那是编排层的职责);若上游喂进多日 K 线,
多日极值会被当成单日极值 —— 这正是「假触及」的来源。
"""
from __future__ import annotations

from typing import Any

# 纪律问题相关:计划说别动/未解锁,却仍然操作
DISCIPLINE_KINDS = {"do_not", "unlock"}

# T 操作的「减」与「接」方向相反,**不能只看 action**,必须按价格区间匹配(spec §4.5):
#   卖出价 ≥ 上沿 × 0.98 → 算「减仓」子项已执行
#   买价   ≤ 下沿 × 1.02 → 算「回补」子项已执行
T_SELL_TOLERANCE = 0.98
T_BUYBACK_TOLERANCE = 1.02

# 成交价与触发价偏离超过这个比例 → 在 note 里披露
# (「已执行」不等于「按计划价位执行」——追高买、提前卖都要看得见)
DEVIATION_TOLERANCE = 0.03

# 阈值比较的浮点容差:9.2 × 1.02 = 9.383999999999999 < 9.384,
# 不加容差会漏判「恰好按计划价位成交」的边界
_EPS = 1e-9


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _day_extremes(klines: list[dict] | None) -> tuple[float | None, float | None]:
    """目标日的 (high, low);缺数据返回 (None, None)"""
    if not klines:
        return None, None
    highs: list[float] = []
    lows: list[float] = []
    for k in klines:
        if not isinstance(k, dict):
            continue
        h = _f(k.get("high"))
        lo = _f(k.get("low"))
        if h is not None:
            highs.append(h)
        if lo is not None:
            lows.append(lo)
    return (max(highs) if highs else None, min(lows) if lows else None)


def _has_txn(transactions: list[dict] | None, code: str, action: str) -> bool:
    if not transactions:
        return False
    for t in transactions:
        if not isinstance(t, dict):
            continue
        if t.get("stock_code") != code:
            continue
        if str(t.get("action") or "").lower() == action:
            return True
    return False


def _assign(
    items: list[dict],
    transactions: list[dict],
) -> dict[int, tuple[dict[str, Any] | None, str]]:
    """把当日流水归属到预案项 → {item 序号: (归属到的流水, 归属说明)}

    规则见模块 docstring。**一条流水最多被一条预案消费。**
    纪律类不参与归属(它的 executed 表示违规,不是「执行了这条预案」)。
    """
    pool: list[dict[str, Any]] = []
    for t in transactions or []:
        if not isinstance(t, dict):
            continue
        code = str(t.get("stock_code") or "")
        action = str(t.get("action") or "").lower()
        if not code or not action:
            continue
        pool.append({
            "code": code, "action": action,
            "price": _f(t.get("price")), "used": False,
        })

    def _take(pred) -> dict[str, Any] | None:
        for t in pool:
            if t["used"] or not pred(t):
                continue
            t["used"] = True
            return t
        return None

    plan: list[tuple[int, int, str, str, str, float | None]] = []
    for idx, it in enumerate(items or []):
        if not isinstance(it, dict):
            continue
        kind = str(it.get("item_kind") or "")
        if kind in DISCIPLINE_KINDS:
            continue  # 纪律类不参与归属
        direction = str(it.get("direction") or "none")
        price = _f(it.get("trigger_price"))
        if price is None or direction not in ("buy", "sell"):
            continue  # 无触发价/无方向 → n_a,不占流水
        prio = 1 if kind in ("t_sell", "t_buyback") else 2
        plan.append((prio, idx, str(it.get("stock_code") or ""), kind, direction, price))
    plan.sort(key=lambda x: (x[0], x[1]))

    out: dict[int, tuple[dict[str, Any] | None, str]] = {}
    for _prio, idx, code, kind, direction, price in plan:
        if kind == "t_sell":
            thr = price * T_SELL_TOLERANCE
            t = _take(lambda x, code=code, thr=thr: x["code"] == code and x["action"] == "sell"
                      and x["price"] is not None and x["price"] >= thr - _EPS)
            if t is not None:
                out[idx] = (t, "减仓成交价在计划区间内")
            continue
        if kind == "t_buyback":
            thr = price * T_BUYBACK_TOLERANCE
            t = _take(lambda x, code=code, thr=thr: x["code"] == code and x["action"] == "buy"
                      and x["price"] is not None and x["price"] <= thr + _EPS)
            if t is not None:
                out[idx] = (t, "回补成交价在计划区间内")
            continue
        # 其余预案:按方向匹配尚未被消费的流水,多条候选时取价差最小的
        best: dict[str, Any] | None = None
        best_diff: float | None = None
        for x in pool:
            if x["used"] or x["code"] != code or x["action"] != direction:
                continue
            if x["price"] is None:
                continue
            diff = abs(x["price"] - price)
            if best_diff is None or diff < best_diff:
                best, best_diff = x, diff
        if best is not None:
            best["used"] = True
            out[idx] = (best, "")
            continue
        # 兜底:没有带价候选 → 方向匹配一条(成交价缺失,不能证明归属 → note 里披露)
        t = _take(lambda x, code=code, direction=direction: x["code"] == code and x["action"] == direction)
        if t is not None:
            out[idx] = (t, "成交价缺失,仅按方向匹配")
    return out


def check_fulfillment(
    items: list[dict],
    target_klines: dict[str, list[dict]],
    transactions: list[dict],
) -> list[dict]:
    """给每个预案项补 fulfillment / fulfillment_note(不修改入参)"""
    assign = _assign(items, transactions)
    out: list[dict] = []
    for idx, raw in enumerate(items or []):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        code = str(item.get("stock_code") or "")
        kind = str(item.get("item_kind") or "")
        direction = str(item.get("direction") or "none")
        price = _f(item.get("trigger_price"))
        high, low = _day_extremes((target_klines or {}).get(code))
        txn, hint = assign.get(idx, (None, ""))

        if kind in DISCIPLINE_KINDS:
            # 纪律问题优先于「不计入统计」—— 这是最该被看见的一条
            if _has_txn(transactions, code, "buy") or _has_txn(transactions, code, "sell"):
                fulfillment = "executed"
                note = "⚠️ 纪律问题:昨日标记别动/未解锁,今日仍有操作"
            else:
                fulfillment = "n_a"
                note = "别动/未解锁类,不计入兑现统计"
        elif direction == "none" or price is None:
            # 无触发价(如 watch):不参与统计
            fulfillment = "n_a"
            note = "无触发价,不计入兑现统计"
        elif txn is not None:
            fulfillment = "executed"
            note = f"已按计划执行({hint})" if hint else "已按计划执行"
            tp = txn.get("price")
            if tp is not None and abs(tp - price) > price * DEVIATION_TOLERANCE:
                note += f"(成交价 {tp:.2f} 与触发价 {price:.2f} 不符)"
        else:
            # 第二步:价格是否触及
            touched = False
            if direction == "sell" and high is not None and high >= price:
                touched = True
            if direction == "buy" and low is not None and low <= price:
                touched = True
            if touched:
                fulfillment = "touched"
                note = "价格已触及触发位,但当日无对应操作"
            else:
                fulfillment = "missed"
                note = "当日未触及触发位(不评价对错)"

        item["fulfillment"] = fulfillment
        item["fulfillment_note"] = note
        out.append(item)
    return out


def summarize_fulfillment(items: list[dict]) -> dict[str, Any]:
    """复盘段统计口径(spec §4.5.4)"""
    total = len(items or [])
    executed = touched = missed = na = 0
    discipline = 0
    for i in items or []:
        if not isinstance(i, dict):
            continue
        f = i.get("fulfillment")
        if f == "executed":
            executed += 1
            if "纪律问题" in str(i.get("fulfillment_note") or ""):
                discipline += 1
        elif f == "touched":
            touched += 1
        elif f == "missed":
            missed += 1
        elif f == "n_a":
            na += 1
    if discipline > 0:
        verdict_label, verdict_level = "存在纪律问题", "danger"
    elif touched > 0:
        verdict_label, verdict_level = "有执行缺口", "warn"
    elif executed > 0:
        verdict_label, verdict_level = "按计划执行", "ok"
    else:
        verdict_label, verdict_level = "无操作记录", "flat"
    return {
        "total": total, "executed": executed, "touched": touched,
        "missed": missed, "na": na, "discipline": discipline,
        "verdict_label": verdict_label, "verdict_level": verdict_level,
    }


__all__ = ["check_fulfillment", "summarize_fulfillment"]
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_fulfillment_checker.py -q --no-header -p no:cacheprovider
```

Expected: 全部 PASS（30 passed —— 原有 20 条 + 本轮新增 10 条：8 条流水归属/偏离披露 + 2 条统计口径）。

> 本轮新增用例的目的（fix round 2，2026-10-21 T4 独立评审后）：
> 旧实现只按方向找流水，同票多条同向预案会互相白嫖同一笔流水（假阳性）。
> 新增用例锁死「一条流水最多被一条预案消费」+「纪律类不参与归属」+「偏离 3% 披露」三条口径。
> 用例数固定为 30 —— 若你改了用例条数，必须同步改这里的数字（简报与实现必须逐行一致）。

- [ ] **Step 5: 静态检查 + Commit**

```powershell
Set-Location 'D:\zga-study\rich\backend'
& '.\.venv\Scripts\python.exe' -m ruff check app/services/fulfillment_checker.py tests/test_fulfillment_checker.py
```
Expected: `All checks passed!`

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/services/fulfillment_checker.py backend/tests/test_fulfillment_checker.py
git commit -m "feat(plan): 兑现比对状态机(纯函数、零 IO)

- 优先级: 已执行 > 价格触及 > 未触及;别动/解锁类记 n_a 不计统计
- 纪律问题: 计划说别动/未解锁却仍有操作 → 显式标记
- 未触发不评价对错(本来就没到,不是判断错)
- summarize_fulfillment 统一复盘段统计口径"
```

---

## Task 5: 持久化层（两表 + 迁移 + 仓储）

**Files:**
- Create: `backend/app/models/orm.py`（追加两表）
- Create: `backend/migrations/versions/<new_rev>_add_battle_plan_tables.py`
- Create: `backend/app/repositories/battle_plan_repo.py`
- Test: `backend/tests/test_battle_plan_repo.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `app.models.orm.BattlePlan` / `BattlePlanItem`
  - `app.repositories.battle_plan_repo`：`upsert_plan`、`get_plan`、`replace_items`、`get_items`、`update_item_fulfillment`、`list_plan_dates`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_battle_plan_repo.py`：

```python
"""作战计划持久化层测试"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models.orm import BattlePlan, BattlePlanItem
from app.repositories.battle_plan_repo import battle_plan_repo


def _item(code="001896.SZ", kind="entry", price=9.62, direction="buy"):
    return {
        "stock_code": code, "stock_name": "豫能控股", "item_kind": kind,
        "direction": direction, "label": "建仓", "trigger_price": price,
        "trigger_condition": "回踩不破", "basis": ["依据 9.62"],
        "invalid_if": "跌破 9.33 作废", "status_now": "armed",
        "fulfillment": "pending", "fulfillment_note": "",
    }


@pytest.mark.asyncio
async def test_upsert_plan_creates_then_updates():
    pid1 = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-21", outlook_json='{"a":1}', review_json=None, meta_json=None)
    pid2 = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-21", outlook_json='{"a":2}', review_json=None, meta_json=None)
    assert pid1 == pid2
    async with async_session() as s:
        rows = (await s.execute(
            select(BattlePlan).where(BattlePlan.plan_date == "2026-10-21")
        )).scalars().all()
    assert len(rows) == 1
    assert rows[0].outlook_json == '{"a":2}'


@pytest.mark.asyncio
async def test_replace_items_is_idempotent():
    pid = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-22", outlook_json=None, review_json=None, meta_json=None)
    await battle_plan_repo.replace_items(pid, "2026-10-22", [_item(), _item(code="000807.SZ")])
    await battle_plan_repo.replace_items(pid, "2026-10-22", [_item()])
    items = await battle_plan_repo.get_items(pid)
    assert len(items) == 1


@pytest.mark.asyncio
async def test_get_items_returns_fulfillment_fields():
    pid = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-23", outlook_json=None, review_json=None, meta_json=None)
    await battle_plan_repo.replace_items(pid, "2026-10-23", [_item()])
    items = await battle_plan_repo.get_items(pid)
    assert items[0]["fulfillment"] == "pending"
    assert items[0]["trigger_price"] == 9.62
    assert items[0]["basis"] == ["依据 9.62"]


@pytest.mark.asyncio
async def test_update_item_fulfillment():
    pid = await battle_plan_repo.upsert_plan(
        plan_date="2026-10-24", outlook_json=None, review_json=None, meta_json=None)
    await battle_plan_repo.replace_items(pid, "2026-10-24", [_item()])
    items = await battle_plan_repo.get_items(pid)
    await battle_plan_repo.update_item_fulfillment(
        items[0]["id"], "touched", "价格已触及")
    again = await battle_plan_repo.get_items(pid)
    assert again[0]["fulfillment"] == "touched"
    assert again[0]["fulfillment_note"] == "价格已触及"


@pytest.mark.asyncio
async def test_get_plan_returns_none_for_missing_date():
    assert await battle_plan_repo.get_plan("1999-01-01") is None
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_battle_plan_repo.py -q --no-header -p no:cacheprovider
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.repositories.battle_plan_repo'`

- [ ] **Step 3: ORM 两表**

在 `backend/app/models/orm.py` 末尾追加：

```python
class BattlePlan(Base):
    """每日作战日报(阶段9)

    一行 = 一个生成日 D 的日报。三段内容:
    - outlook_json: 明日市场预期(对 D+1 的规则推断)
    - review_json : 今日复盘(D 当天实际 + 昨日预案兑现比对)
    - items       : 明日操作预案(目标日 = D+1,落在 battle_plan_items)
    """
    __tablename__ = "battle_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_date: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    outlook_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class BattlePlanItem(Base):
    """日报内的一条逐票预案(目标日 = plan_date 的次日)"""
    __tablename__ = "battle_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("battle_plans.id"), nullable=False, index=True
    )
    plan_date: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String, nullable=True)
    item_kind: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)   # buy/sell/none
    label: Mapped[str] = mapped_column(String, nullable=False)
    trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_condition: Mapped[str] = mapped_column(Text, nullable=False)
    basis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalid_if: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_now: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)  # 溯源用(spec §4.4.4)
    fulfillment: Mapped[str] = mapped_column(
        String, default="pending", nullable=False
    )  # pending/touched/executed/missed/n_a
    fulfillment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Alembic 迁移**

用 alembic 生成 revision，再手写内容。命令行：

```powershell
Set-Location 'D:\zga-study\rich\backend'
& '.\.venv\Scripts\python.exe' -m alembic revision -m "add battle plan tables"
```

生成的文件名形如 `backend/migrations/versions/<hash>_add_battle_plan_tables.py`。把 `down_revision` 改为 `"f6a7b8c9d0e1"`，并把 `upgrade()` 改成下面这样（**必须先 `has_table` 检查**——`kline_cache` 曾因"迁移已应用但表被删"导致 `upgrade head` 直接失败）：

```python
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("battle_plans"):
        op.create_table(
            "battle_plans",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("plan_date", sa.String, nullable=False),
            sa.Column("outlook_json", sa.Text, nullable=True),
            sa.Column("review_json", sa.Text, nullable=True),
            sa.Column("meta_json", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=True),
            sa.Column("updated_at", sa.DateTime, nullable=True),
        )
        # 与 ORM 的 `unique=True, index=True` 对齐:同名**唯一索引**
        # (不是「唯一约束 + 同名普通索引」——同名不同义会让 alembic autogenerate 误报差异)
        op.create_index("ix_battle_plans_plan_date", "battle_plans", ["plan_date"], unique=True)

    if not inspector.has_table("battle_plan_items"):
        op.create_table(
            "battle_plan_items",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("plan_id", sa.Integer, sa.ForeignKey("battle_plans.id"), nullable=False),
            sa.Column("plan_date", sa.String, nullable=False),
            sa.Column("stock_code", sa.String, nullable=False),
            sa.Column("stock_name", sa.String, nullable=True),
            sa.Column("item_kind", sa.String, nullable=False),
            sa.Column("direction", sa.String, nullable=False),
            sa.Column("label", sa.String, nullable=False),
            sa.Column("trigger_price", sa.Float, nullable=True),
            sa.Column("trigger_condition", sa.Text, nullable=False),
            sa.Column("basis_json", sa.Text, nullable=True),
            sa.Column("invalid_if", sa.Text, nullable=True),
            sa.Column("status_now", sa.String, nullable=False),
            sa.Column("source", sa.String, nullable=True),
            sa.Column("fulfillment", sa.String, nullable=False, server_default="pending"),
            sa.Column("fulfillment_note", sa.Text, nullable=True),
        )
        op.create_index("ix_battle_plan_items_plan_id", "battle_plan_items", ["plan_id"])
        op.create_index("ix_battle_plan_items_plan_date", "battle_plan_items", ["plan_date"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("battle_plan_items"):
        op.drop_table("battle_plan_items")
    if inspector.has_table("battle_plans"):
        op.drop_table("battle_plans")
```

- [ ] **Step 5: 仓储层**

创建 `backend/app/repositories/battle_plan_repo.py`：

```python
"""作战计划持久化(日报 + 逐票预案)"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select, update

from app.db import async_session
from app.models.orm import BattlePlan, BattlePlanItem


def _dumps(v: Any) -> str | None:
    if v is None:
        return None
    return json.dumps(v, ensure_ascii=False)


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _row_to_item(r: BattlePlanItem) -> dict[str, Any]:
    return {
        "id": r.id,
        "plan_id": r.plan_id,
        "plan_date": r.plan_date,
        "stock_code": r.stock_code,
        "stock_name": r.stock_name,
        "item_kind": r.item_kind,
        "direction": r.direction,
        "label": r.label,
        "trigger_price": r.trigger_price,
        "trigger_condition": r.trigger_condition,
        "basis": _loads(r.basis_json) or [],
        "invalid_if": r.invalid_if or "",
        "status_now": r.status_now,
        "source": r.source or "",
        "fulfillment": r.fulfillment or "pending",
        "fulfillment_note": r.fulfillment_note or "",
    }


class BattlePlanRepo:
    """日报仓储。所有方法都是幂等的。"""

    async def upsert_plan(
        self, plan_date: str, outlook_json: str | None,
        review_json: str | None, meta_json: str | None,
    ) -> int:
        async with async_session() as session:
            row = (await session.execute(
                select(BattlePlan).where(BattlePlan.plan_date == plan_date)
            )).scalar_one_or_none()
            if row is None:
                row = BattlePlan(plan_date=plan_date)
                session.add(row)
            row.outlook_json = outlook_json
            row.review_json = review_json
            row.meta_json = meta_json
            await session.commit()
            return row.id

    async def get_plan(self, plan_date: str) -> dict[str, Any] | None:
        async with async_session() as session:
            row = (await session.execute(
                select(BattlePlan).where(BattlePlan.plan_date == plan_date)
            )).scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "plan_date": row.plan_date,
                "outlook": _loads(row.outlook_json),
                "review": _loads(row.review_json),
                "meta": _loads(row.meta_json),
            }

    async def replace_items(
        self, plan_id: int, plan_date: str, items: list[dict[str, Any]]
    ) -> list[int]:
        """整体替换某日报的预案项(先删后插)"""
        async with async_session() as session:
            await session.execute(
                delete(BattlePlanItem).where(BattlePlanItem.plan_id == plan_id)
            )
            ids: list[int] = []
            for it in items or []:
                row = BattlePlanItem(
                    plan_id=plan_id,
                    plan_date=plan_date,
                    stock_code=str(it.get("stock_code") or ""),
                    stock_name=it.get("stock_name"),
                    item_kind=str(it.get("item_kind") or "watch"),
                    direction=str(it.get("direction") or "none"),
                    label=str(it.get("label") or ""),
                    trigger_price=it.get("trigger_price"),
                    trigger_condition=str(it.get("trigger_condition") or ""),
                    basis_json=_dumps(it.get("basis") or []),
                    invalid_if=it.get("invalid_if") or "",
                    status_now=str(it.get("status_now") or "armed"),
                    source=it.get("source") or None,
                    fulfillment=str(it.get("fulfillment") or "pending"),
                    fulfillment_note=it.get("fulfillment_note") or "",
                )
                session.add(row)
                await session.flush()
                ids.append(row.id)
            await session.commit()
            return ids

    async def get_items(self, plan_id: int) -> list[dict[str, Any]]:
        async with async_session() as session:
            rows = (await session.execute(
                select(BattlePlanItem)
                .where(BattlePlanItem.plan_id == plan_id)
                .order_by(BattlePlanItem.id)
            )).scalars().all()
            return [_row_to_item(r) for r in rows]

    async def update_item_fulfillment(
        self, item_id: int, fulfillment: str, note: str = ""
    ) -> None:
        async with async_session() as session:
            await session.execute(
                update(BattlePlanItem)
                .where(BattlePlanItem.id == item_id)
                .values(fulfillment=fulfillment, fulfillment_note=note)
            )
            await session.commit()

    async def list_plan_dates(self, limit: int = 30) -> list[str]:
        async with async_session() as session:
            rows = (await session.execute(
                select(BattlePlan.plan_date)
                .order_by(BattlePlan.plan_date.desc())
                .limit(limit)
            )).scalars().all()
            return list(rows)


battle_plan_repo = BattlePlanRepo()

__all__ = ["battle_plan_repo", "BattlePlanRepo"]
```

- [ ] **Step 6: 运行测试确认通过**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_battle_plan_repo.py -q --no-header -p no:cacheprovider
```

Expected: 全部 PASS（5 passed）。

- [ ] **Step 7: 迁移在开发库上验证**

```powershell
Set-Location 'D:\zga-study\rich\backend'
& '.\.venv\Scripts\python.exe' -m alembic upgrade head
& '.\.venv\Scripts\python.exe' -m alembic current
```

Expected: `current` 显示新 revision；`data.db` 中 `battle_plans` / `battle_plan_items` 两表存在。

- [ ] **Step 8: 静态检查 + Commit**

```powershell
Set-Location 'D:\zga-study\rich\backend'
& '.\.venv\Scripts\python.exe' -m ruff check app/repositories/battle_plan_repo.py app/models/orm.py tests/test_battle_plan_repo.py
```
Expected: `All checks passed!`

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/models/orm.py backend/app/repositories/battle_plan_repo.py backend/migrations/versions backend/tests/test_battle_plan_repo.py
git commit -m "feat(plan): 作战计划持久化(两表 + Alembic 迁移 + 仓储)

- battle_plans: 生成日唯一的日报(outlook/review/meta 三段 JSON)
- battle_plan_items: 逐票预案(触发价/条件/依据/失效条件/兑现状态)
- 迁移按项目惯例先 has_table 再建表(防御'迁移已应用但表被删')
- 仓储 upsert/replace/get/update_fulfillment 全部幂等"
```

---

## Task 6: 编排服务（battle_plan_service）

**Files:**
- Create: `backend/app/services/battle_plan_service.py`
- Test: `backend/tests/test_battle_plan_service.py`

**Interfaces:**
- Consumes: Task 1 的 `position_status`、Task 2 的 `build_outlook`、Task 3 的 `build_items`/`build_todos`、Task 4 的 `check_fulfillment`/`summarize_fulfillment`、Task 5 的 `battle_plan_repo`
- Produces: `resolve_target_stocks()`、`build_plan(plan_date)`、`get_plan(plan_date)`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_battle_plan_service.py`：

```python
"""作战计划编排层测试(外部 IO 全部 mock)"""
from __future__ import annotations

from datetime import date

import pytest

from app.services import battle_plan_service as svc


def _stock(code="001896.SZ", name="豫能控股", price=9.92, shares=600, avg_cost=15.578):
    return {
        "stock_code": code, "stock_name": name, "in_position": True,
        "is_favorite": False, "shares": shares, "avg_cost": avg_cost,
        "current_price": price,
    }


@pytest.mark.asyncio
async def test_resolve_scope_merges_positions_and_favorites(monkeypatch):
    async def _pos():
        return [_stock("001896.SZ"), _stock("000807.SZ", "云铝股份", 24.93, 100, 8.977)]
    async def _fav():
        return [{"stock_code": "001896.SZ", "stock_name": "豫能控股"},
                {"stock_code": "300394.SZ", "stock_name": "天孚通信"}]
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    scope = await svc.resolve_target_stocks()
    codes = {s["stock_code"] for s in scope}
    assert codes == {"001896.SZ", "000807.SZ", "300394.SZ"}
    by_code = {s["stock_code"]: s for s in scope}
    assert by_code["001896.SZ"]["in_position"] is True
    assert by_code["001896.SZ"]["is_favorite"] is True
    assert by_code["300394.SZ"]["in_position"] is False


@pytest.mark.asyncio
async def test_resolve_scope_merges_without_truncating(monkeypatch):
    """resolve_target_stocks 只做**合并去重**,不做上限截断。

    为什么:截断与「是否真的截断」这个标志必须由同一处产出。
    若这里先切一刀,build_plan 里再切一次就永远切不动(len 恰好 == MAX_SCOPE),
    meta["truncated"] 恒为 False —— 等于向用户谎称「一只票都没砍掉」。
    """
    async def _pos():
        return [_stock(f"00000{i}.SZ", f"票{i}", 10.0, 100, 9.0) for i in range(25)]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)
    scope = await svc.resolve_target_stocks()
    assert len(scope) == 25
    # 截断标志必须精确:只有真的砍掉了票才为 True
    cut, truncated = svc._truncate_scope(scope)
    assert len(cut) == svc.MAX_SCOPE
    assert truncated is True
    _exact, not_truncated = svc._truncate_scope(
        [_stock(f"00000{i}.SZ") for i in range(svc.MAX_SCOPE)]
    )
    assert not_truncated is False


@pytest.mark.asyncio
async def test_build_plan_degrades_when_one_stock_fails(monkeypatch):
    async def _pos():
        return [_stock("001896.SZ"), _stock("000807.SZ", "云铝股份", 24.93, 100, 8.977)]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    async def _one(code, *a, **kw):
        if code == "000807.SZ":
            raise RuntimeError("K 线不可用")
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _one)

    def _ind(klines):
        """⚠️ `compute_indicators` 是**同步**函数(ta_service.py: `def compute_indicators`),
        这里必须用同步 mock —— 写成 async 会让 indicators 变成协程对象,
        build_decision 访问 ctx.indicators.xxx 时炸 AttributeError。"""
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 8.26,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)

    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 50, "down_total": 50}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)

    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    codes = {i["stock_code"] for i in plan["items"]}
    assert "000807.SZ" not in codes
    assert plan["meta"]["degraded"] is True
    assert any("000807.SZ" in r for r in plan["meta"]["degraded_reason"])


@pytest.mark.asyncio
async def test_build_plan_returns_three_sections(monkeypatch):
    async def _pos():
        return [_stock()]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)
    async def _k(code, *a, **kw):
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _k)
    def _ind(klines):
        """⚠️ `compute_indicators` 是**同步**函数(ta_service.py: `def compute_indicators`),
        这里必须用同步 mock —— 写成 async 会让 indicators 变成协程对象,
        build_decision 访问 ctx.indicators.xxx 时炸 AttributeError。"""
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 8.26,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)
    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 60, "down_total": 40}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    assert set(["plan_date", "outlook", "review", "items", "meta"]) <= set(plan)
    assert plan["outlook"]["stance"] in ("bullish", "bearish", "neutral", "unknown")
    assert len(plan["outlook"]["dims"]) == 4
    assert plan["meta"]["scope_count"] >= 1


@pytest.mark.asyncio
async def test_build_plan_puts_now_actions_into_review_pending_todos(monkeypatch):
    """status=="now" 的动作必须进 review.pending_todos(今日未执行待办)

    这是 spec §4.4.2 三路分流的核心:now 不进明日预案,只进复盘待办。
    mock 让止损位(9.95)高于现价(9.9)→ 决策引擎产出 status=="now" 的 stop 动作。
    """
    async def _pos():
        return [_stock()]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    async def _k(code, *a, **kw):
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _k)

    def _ind(klines):
        """⚠️ `compute_indicators` 是**同步**函数(ta_service.py: `def compute_indicators`),
        这里必须用同步 mock —— 写成 async 会让 indicators 变成协程对象,
        build_decision 访问 ctx.indicators.xxx 时炸 AttributeError。"""
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 9.95,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)

    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 50, "down_total": 50}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    todos = plan["review"]["pending_todos"]
    assert len(todos) >= 1
    assert todos[0]["stock_code"] == "001896.SZ"
    assert todos[0]["label"]
    # now 动作不得出现在明日预案里
    assert all(i["status_now"] != "now" for i in plan["items"])


@pytest.mark.asyncio
async def test_build_plan_meta_truncated_flag_is_true_when_scope_exceeds_max(monkeypatch):
    """端到端:股票池超上限时 meta["truncated"] 必须为 True —— 不许谎称没砍票"""
    async def _pos():
        return [_stock(f"00000{i}.SZ", f"票{i}", 10.0, 100, 9.0) for i in range(25)]
    async def _fav():
        return []
    monkeypatch.setattr(svc, "_load_positions", _pos)
    monkeypatch.setattr(svc, "_load_favorites", _fav)

    async def _k(code, *a, **kw):
        return [{"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.8,
                 "close": 9.9, "volume": 100}]
    monkeypatch.setattr(svc, "fetch_klines", _k)

    def _ind(klines):
        return {"latest_close": 9.9, "ma": {"ma5": 9.8, "ma10": 9.5},
                "position": {"p20": 8.5, "p80": 11.0, "stop_loss_price": 8.26,
                             "support_price": 8.5, "risk_band": "mid"},
                "volume": {"ratio": 1.0}, "kdj": {"zone": "neutral", "cross": None},
                "channel": {"state": "flat"}, "support_pressure": {"pressure": [11.0]},
                "stabilize": {"state": False, "price": None}, "signal": {"score": 50}}
    monkeypatch.setattr(svc, "compute_indicators", _ind)

    async def _quote(codes):
        return []
    monkeypatch.setattr(svc, "_load_quotes", _quote)
    async def _ctx(code, *a, **kw):
        from app.services.decision_service import MarketContext
        return MarketContext(degraded=[])
    monkeypatch.setattr(svc, "get_market_context", _ctx)
    async def _sent():
        return {"up_total": 50, "down_total": 50}
    monkeypatch.setattr(svc, "fetch_market_sentiment", _sent)
    async def _flows(*a, **kw):
        return [{"name": "电子", "netamount_yi": 1.0}]
    monkeypatch.setattr(svc, "get_sector_fund_flow", _flows)
    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)
    async def _save(*a, **kw):
        return 1
    monkeypatch.setattr(svc, "_persist", _save)

    plan = await svc.build_plan(date(2026, 10, 21))
    assert plan["meta"]["truncated"] is True
    assert plan["meta"]["scope_count"] == svc.MAX_SCOPE


@pytest.mark.asyncio
async def test_fulfillment_uses_only_target_day_kline(monkeypatch):
    """兑现比对只能用**目标日那一根** K 线。

    check_fulfillment 会把传入 K 线的 high/low 合成为当日极值 ——
    一次给 5 根等于把「5 天极值」当成「单日极值」→ 昨天没到位的价位
    会被说成目标日触及了。这里造一根「前一天击穿、目标日没击穿」的 K 线锁死该行为。
    """
    prev_plan = {
        "id": 1, "plan_date": "2026-10-21",
        "outlook": None, "review": None,
        "meta": {"target_date": "2026-10-22"},
    }
    prev_items = [{
        "id": 1, "stock_code": "001896.SZ", "item_kind": "entry", "direction": "buy",
        "trigger_price": 9.62, "status_now": "armed", "label": "建仓",
    }]

    class _Repo:
        async def get_plan(self, plan_date):
            return prev_plan if plan_date == "2026-10-21" else None

        async def get_items(self, plan_id):
            return prev_items

        async def update_item_fulfillment(self, item_id, fulfillment, note=""):
            return None

    monkeypatch.setattr(svc, "battle_plan_repo", _Repo())

    async def _k(code, *a, **kw):
        return [
            {"date": "2026-10-21", "open": 9.0, "high": 10.0, "low": 8.80,
             "close": 9.9, "volume": 100},
            {"date": "2026-10-22", "open": 9.0, "high": 9.90, "low": 9.70,
             "close": 9.8, "volume": 100},
        ]
    monkeypatch.setattr(svc, "fetch_klines", _k)

    async def _txns(*a, **kw):
        return []
    monkeypatch.setattr(svc, "_load_transactions", _txns)

    review = await svc._build_review("2026-10-21", "2026-10-22", [])
    assert review["fulfillment"]["items"][0]["fulfillment"] == "missed"
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_battle_plan_service.py -q --no-header -p no:cacheprovider
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.battle_plan_service'`

- [ ] **Step 3: 实现**

创建 `backend/app/services/battle_plan_service.py`：

```python
"""每日作战计划编排(取数 → 三模块 → 落库 → 回填兑现)

设计文档 §4.6。本模块是**唯一**做 IO 的地方;三个纯函数模块
(outlook_service / plan_item_builder / fulfillment_checker)只管算。

**降级原则**:单票失败不影响其余票;缺数据如实标注,绝不编造。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.repositories.battle_plan_repo import battle_plan_repo
from app.services.fulfillment_checker import check_fulfillment, summarize_fulfillment
from app.services.kline_service import fetch_klines
from app.services.market_context_service import get_market_context
from app.services.market_overview_service import fetch_market_sentiment
from app.services.outlook_service import build_outlook
from app.services.plan_item_builder import build_items, build_todos
from app.services.position_status import (
    kline_fallback_price,
    resolve_position_status,
    sanitize_current_price,
)
from app.services.quote_service import QuoteService
from app.services.sector_fund_flow_service import get_sector_fund_flow
from app.services.ta_service import compute_indicators

logger = logging.getLogger(__name__)

MAX_SCOPE = 20              # 目标股票池上限
KLINE_COUNT = 190           # 决策引擎需要足够 K 线
INDEX_CODE = "000001.SH"    # 上证指数
INDEX_KLINE_COUNT = 30      # 算 MA20 + 5 日均量足够


# ============================ 取数 ============================

async def _load_positions() -> list[dict[str, Any]]:
    """持仓(已是聚合结果)"""
    from app.modules.portfolio.service import get_all_positions

    positions = await get_all_positions()
    out: list[dict[str, Any]] = []
    for p in positions or []:
        shares = int(getattr(p, "shares", 0) or 0)
        if shares <= 0:
            continue
        out.append({
            "stock_code": getattr(p, "stock_code", ""),
            "stock_name": getattr(p, "stock_name", None),
            "shares": shares,
            "avg_cost": float(getattr(p, "avg_cost", 0) or 0),
        })
    return out


async def _load_favorites() -> list[dict[str, Any]]:
    """★关注票"""
    from app.repositories import watchlist_repo

    rows = await watchlist_repo.list_all()
    return [
        {"stock_code": getattr(r, "stock_code", ""), "stock_name": getattr(r, "stock_name", None)}
        for r in rows or []
        if getattr(r, "is_favorite", False)
    ]


async def _load_quotes(codes: list[str]):
    """实时行情(失败返回空列表,不阻断)"""
    try:
        return await QuoteService().get_quotes(codes)
    except Exception as e:  # noqa: BLE001
        logger.warning("作战计划拉取行情失败: %s", e)
        return []


async def _load_transactions(plan_date: str) -> list[dict[str, Any]]:
    """目标日交易流水"""
    from app.modules.portfolio.repository import transaction_repo

    try:
        rows, _total = await transaction_repo.list_all(limit=500)
    except Exception as e:  # noqa: BLE001
        logger.warning("作战计划读取流水失败: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for r in rows or []:
        trade_date = getattr(r, "trade_date", None)
        if trade_date is None:
            continue
        iso = trade_date.isoformat() if hasattr(trade_date, "isoformat") else str(trade_date)[:10]
        if iso != plan_date:
            continue
        # Transaction.price 是 String 列,可能是非数字字符串 —— 必须 try/except,
        # 否则一个脏价格会让整份日报生成失败(而不是只丢这一条流水的价格)
        price: float | None = None
        raw_price = getattr(r, "price", None)
        if raw_price is not None:
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                price = None
        out.append({
            "stock_code": getattr(r, "stock_code", ""),
            "action": getattr(r, "action", ""),
            "shares": int(getattr(r, "shares", 0) or 0),
            "price": price,
            "trade_date": iso,
        })
    return out


# ============================ 股票池 ============================

async def resolve_target_stocks() -> list[dict[str, Any]]:
    """持仓 ∪ ★关注,按 code 去重。持仓优先。"""
    positions = await _load_positions()
    favorites = await _load_favorites()

    merged: dict[str, dict[str, Any]] = {}
    for p in positions:
        code = p["stock_code"]
        if not code:
            continue
        merged[code] = {
            "stock_code": code, "stock_name": p.get("stock_name"),
            "in_position": True, "is_favorite": False,
            "shares": p.get("shares", 0), "avg_cost": p.get("avg_cost", 0.0),
        }
    for f in favorites:
        code = f["stock_code"]
        if not code:
            continue
        if code in merged:
            merged[code]["is_favorite"] = True
        else:
            merged[code] = {
                "stock_code": code, "stock_name": f.get("stock_name"),
                "in_position": False, "is_favorite": True,
                "shares": 0, "avg_cost": 0.0,
            }
    scope = list(merged.values())
    scope.sort(key=lambda s: (not s["in_position"], s["stock_code"]))
    # ⚠️ 这里**不做上限截断** —— 截断与「是否真的截断」这个标志必须由同一处产出。
    # 若这里先切一刀,build_plan 再切一次就永远切不动(len 恰好 == MAX_SCOPE),
    # meta["truncated"] 会恒为 False —— 等于向用户谎称「一只票都没砍掉」。
    # 上限截断只在 build_plan 里做一次(见 `_truncate_scope`)。
    return scope


def _truncate_scope(scope: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """超过 MAX_SCOPE 时截断,并**精确**返回是否真的发生了截断。

    为什么不写成 `len(scope) >= MAX_SCOPE`:恰好等于上限时并没有真的截断,
    那种写法会误报 truncated=True —— 等于向用户谎称"砍掉了一些票"。
    """
    if len(scope) > MAX_SCOPE:
        return scope[:MAX_SCOPE], True
    return scope, False


# ============================ 单票决策 ============================

async def _build_one_decision(
    stock: dict[str, Any], quotes_by_code: dict[str, Any]
) -> tuple[Optional[dict], Optional[list[dict]], list[str]]:
    """返回 (decision, todos, errors);失败返回 (None, None, [原因])"""
    code = stock["stock_code"]
    errors: list[str] = []
    try:
        klines = await fetch_klines(code, period="daily", count=KLINE_COUNT)
    except Exception as e:  # noqa: BLE001
        return None, None, [f"{code} K线不可用: {e}"]
    if not klines:
        return None, None, [f"{code} K线为空"]

    try:
        indicators = compute_indicators(klines)
    except Exception as e:  # noqa: BLE001
        return None, None, [f"{code} 指标计算失败: {e}"]

    quote = quotes_by_code.get(code)
    current_price, _date = sanitize_current_price(quote, klines)
    fallback = kline_fallback_price(klines)
    price_for_status = current_price if current_price is not None else fallback
    shares = int(stock.get("shares") or 0)
    avg_cost = float(stock.get("avg_cost") or 0.0)
    position_status, _pct = resolve_position_status(
        PositionView(shares=shares, avg_cost=avg_cost) if shares > 0 else None,
        price_for_status, fallback
    )

    prev_close = None
    if len(klines) >= 2:
        try:
            prev_close = float(klines[-2]["close"])
        except (TypeError, ValueError, KeyError):
            prev_close = None

    try:
        env = await get_market_context(code, stock_change_pct=None)
    except Exception as e:  # noqa: BLE001
        logger.warning("作战计划取市场环境失败 %s: %s", code, e)
        from app.services.decision_service import MarketContext
        env = MarketContext(degraded=["市场环境不可用"])

    from app.services.decision_service import DecisionContext, build_decision

    ctx = DecisionContext(
        stock_code=code,
        stock_name=stock.get("stock_name"),
        indicators=indicators,
        klines=klines,
        current_price=float(current_price) if current_price is not None else None,
        prev_close=prev_close,
        cost_basis=avg_cost if shares > 0 else None,
        shares=shares,
        position_status=position_status,
        env=env,
    )
    decision = build_decision(ctx)
    todos = build_todos(decision)
    return decision, todos, errors


@dataclass(frozen=True)
class PositionView:
    """持仓视图 —— 同时满足两个下游契约(**属性形状,不是 dict**):

    - `services/position_status.resolve_position_status`:须含 `.shares` / `.avg_cost` 属性
    - `services/plan_item_builder.build_items`:须含 `.shares` 属性

    两边统一成属性形状(2026-10-21 跨任务裁决),避免接线层出现 dict/对象两套契约。
    """

    shares: int
    avg_cost: float


# ============================ 目标交易日 ============================

def _next_trading_day(index_klines: list[dict], plan_date: date) -> tuple[str, bool]:
    """下一个交易日;返回 (日期字符串, 是否为推算值)"""
    last_date = None
    for k in reversed(index_klines or []):
        d = (k or {}).get("date")
        if d:
            last_date = str(d)[:10]
            break
    base = date.fromisoformat(last_date) if last_date else plan_date
    nxt = base + timedelta(days=1)
    while nxt.weekday() >= 5:  # 跳过周末
        nxt += timedelta(days=1)
    return nxt.isoformat(), True   # 未能从真实日历确认,标记为推算


# ============================ 主入口 ============================

async def _persist(plan: dict[str, Any]) -> int:
    """落库(可被测试替换)

    **幂等覆盖的例外**(spec §4.6.3):D 日报的 items 若已有非 pending 的 fulfillment,
    说明那批兑现状态已被判定过(生成 D+1 日报时回填的)。重新生成 D 日报时
    **保留原 items 不动**,只更新 outlook / review / meta —— 否则会把已判定的
    兑现状态冲回 pending,把复盘历史抹掉。
    """
    plan_date = plan["plan_date"]
    meta = plan.setdefault("meta", {})

    judged = False
    row = await battle_plan_repo.get_plan(plan_date)
    if row:
        existing = await battle_plan_repo.get_items(row["id"])
        judged = any((i.get("fulfillment") or "pending") != "pending" for i in existing)
    meta["items_preserved"] = judged

    plan_id = await battle_plan_repo.upsert_plan(
        plan_date=plan_date,
        outlook_json=json.dumps(plan.get("outlook"), ensure_ascii=False),
        review_json=json.dumps(plan.get("review"), ensure_ascii=False),
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    if not judged:
        await battle_plan_repo.replace_items(plan_id, plan_date, plan.get("items") or [])
    return plan_id


async def build_plan(plan_date: date) -> dict[str, Any]:
    """生成一份作战日报(幂等;同日重复生成覆盖)"""
    ds = plan_date.isoformat()
    degraded: list[str] = []

    scope, truncated = _truncate_scope(await resolve_target_stocks())
    if not scope:
        raise ValueError("目标股票池为空:既无持仓也无★关注票,无法生成作战计划")

    quotes = await _load_quotes([s["stock_code"] for s in scope])
    quotes_by_code = {getattr(q, "code", None): q for q in (quotes or [])}

    # ---- 市场数据(明日预期原料) ----
    index_klines: list[dict] = []
    try:
        index_klines = await fetch_klines(INDEX_CODE, period="daily", count=INDEX_KLINE_COUNT)
    except Exception as e:  # noqa: BLE001
        degraded.append(f"上证指数K线不可用: {e}")

    sentiment = None
    try:
        sentiment = await fetch_market_sentiment()
    except Exception as e:  # noqa: BLE001
        degraded.append(f"涨跌家数不可用: {e}")

    sector_flows = None
    try:
        sector_flows = await get_sector_fund_flow(fenlei=1, num=40, sort="netamount")
    except Exception as e:  # noqa: BLE001
        degraded.append(f"板块资金流不可用: {e}")

    outlook = build_outlook(index_klines, sentiment, sector_flows)

    # ---- 逐票预案 ----
    items: list[dict[str, Any]] = []
    todos: list[dict[str, Any]] = []
    for stock in scope:
        decision, stock_todos, errors = await _build_one_decision(stock, quotes_by_code)
        degraded.extend(errors)
        if decision is None:
            continue
        todos.extend(stock_todos or [])
        pos = PositionView(
            shares=int(stock.get("shares") or 0),
            avg_cost=float(stock.get("avg_cost") or 0.0),
        )
        items.extend(build_items(decision, pos if stock.get("in_position") else None))

    # ---- 昨日兑现(闭环) ----
    prev_date = (plan_date - timedelta(days=1)).isoformat()
    review = await _build_review(prev_date, plan_date, degraded, todos)

    target_date, estimated = _next_trading_day(index_klines, plan_date)
    meta = {
        "scope_count": len(scope),
        "scope": scope,
        "truncated": truncated,
        "degraded": bool(degraded),
        "degraded_reason": degraded,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target_date": target_date,
        "target_date_estimated": estimated,
    }

    plan = {
        "plan_date": ds,
        "target_date": target_date,
        "outlook": outlook,
        "review": review,
        "items": items,
        # ⚠️ 无顶层 `todos` —— 待办统一在 review.pending_todos(spec §4.7 契约)。
        # 首版实现里这里多了一个 `todos`,已由「Task 6 · fix round 1 / F11」删掉。
        "meta": meta,
    }
    await _persist(plan)
    return plan


async def _build_review(
    prev_date: str,
    plan_date: str,
    degraded: list[str],
    pending_todos: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """今日复盘 = 昨日预案兑现比对 + 今日待办

    `pending_todos` = 本次各票决策里 status=="now" 的动作(条件已满足但用户还没做)。
    它们**必须进复盘段**:写进明日预案是「已经过期的建议」,只有推到今日待办
    才能逼用户面对(见 spec §4.4.2 三路分流)。
    """
    todos = list(pending_todos or [])
    prev = await battle_plan_repo.get_plan(prev_date)
    if not prev:
        return {
            "market": None,
            "fulfillment": None,
            "pending_todos": todos,
            "note": "没有找到昨日作战计划,今日暂无兑现比对",
        }
    prev_items = await battle_plan_repo.get_items(prev["id"])

    # 目标日 = 昨日预案所面向的那一天 = 昨日日报的 meta.target_date(缺失时退回 plan_date)
    prev_meta = prev.get("meta") or {}
    target_day = str(prev_meta.get("target_date") or plan_date)
    codes = {i["stock_code"] for i in prev_items}
    target_klines: dict[str, list[dict]] = {}
    for code in codes:
        try:
            ks = await fetch_klines(code, period="daily", count=5)
            # ⚠️ **只取目标日那一根**:`check_fulfillment` 会把传入 K 线的 high/low 合成为当日极值,
            # 一次给 5 根等于把「5 天极值」当成「单日极值」→ 「当日触及」被夸大,
            # 昨天没到位的价位会被说成昨天触及了。宁可少数据,不可假触及。
            day_ks = [
                k for k in (ks or [])
                if str((k or {}).get("date") or "")[:10] == target_day
            ]
            target_klines[code] = day_ks
        except Exception as e:  # noqa: BLE001
            degraded.append(f"{code} 兑现比对取K线失败: {e}")
            target_klines[code] = []

    transactions = await _load_transactions(target_day)
    checked = check_fulfillment(prev_items, target_klines, transactions)
    summary = summarize_fulfillment(checked)

    # 回填昨日日报的兑现状态
    for it in checked:
        try:
            await battle_plan_repo.update_item_fulfillment(
                it["id"], it["fulfillment"], it.get("fulfillment_note") or ""
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("回填兑现状态失败 item=%s: %s", it.get("id"), e)

    return {
        "market": None,
        "fulfillment": {**summary, "items": [
            {
                "stock_code": i["stock_code"], "stock_name": i.get("stock_name"),
                "label": i.get("label"), "item_kind": i.get("item_kind"),
                "fulfillment": i["fulfillment"], "note": i.get("fulfillment_note"),
            }
            for i in checked
        ]},
        "pending_todos": todos,
        "note": None,
    }


async def get_plan(plan_date: date) -> Optional[dict[str, Any]]:
    """读取指定日期的日报(不存在返回 None)"""
    row = await battle_plan_repo.get_plan(plan_date.isoformat())
    if not row:
        return None
    items = await battle_plan_repo.get_items(row["id"])
    return {
        "plan_date": row["plan_date"],
        "target_date": (row.get("meta") or {}).get("target_date"),
        "outlook": row.get("outlook"),
        "review": row.get("review"),
        "items": items,
        "meta": row.get("meta"),
    }


__all__ = ["build_plan", "get_plan", "resolve_target_stocks", "MAX_SCOPE"]
```

- [ ] **Step 4: 运行测试确认通过**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_battle_plan_service.py -q --no-header -p no:cacheprovider
```

Expected: 全部 PASS（7 passed）。

- [ ] **Step 5: 静态检查 + Commit**

```powershell
Set-Location 'D:\zga-study\rich\backend'
& '.\.venv\Scripts\python.exe' -m ruff check app/services/battle_plan_service.py tests/test_battle_plan_service.py
```
Expected: `All checks passed!`

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/services/battle_plan_service.py backend/tests/test_battle_plan_service.py
git commit -m "feat(plan): 作战计划编排层(唯一做 IO 的地方)

- 股票池 = 持仓 ∪ ★关注 去重(上限 20,持仓优先)
- 单票取数失败不影响其余票,如实写 degraded
- 昨日兑现比对在生成日报时自动进行并回填昨日日报的 items
- 目标交易日按工作日推算并标记 target_date_estimated"
```

---

## Task 6 · fix round 1（编排层缺陷修复）

> **背景**：Task 6 的实现已落（commit `8cce90f`），独立评审 **VERDICT = FAIL**：
> 1 条 Critical + 7 条 Important。本轮把 **Critical + 7 条 Important** 全部修掉，
> 另顺带处理 3 条 Minor。
>
> **本轮与 Task 4 的 fix round 3 合并执行**：两者都要改 `fulfillment_checker.py`
> （T4 要补 `unlock` 场景用例 + 偏离比较的 `_EPS`；T6 的 F1 要加 `no_data` 状态）。
> 合并成一轮，避免两个 worker 同时改同一文件。

**改动文件清单（只许动这 6 个）**：

| 文件 | 改动 |
|---|---|
| `backend/app/services/fulfillment_checker.py` | F1（`no_data` 状态）+ T4-2（偏离比较 `_EPS`） |
| `backend/app/services/outlook_service.py` | F8（新增纯函数 `build_market_snapshot`） |
| `backend/app/services/battle_plan_service.py` | F1/F2/F3/F4/F5/F7/F8/F9/F11/F12/F13 |
| `backend/tests/test_fulfillment_checker.py` | T4-1/T4-3 补用例 + F1 的 `no_data` 用例 |
| `backend/tests/test_outlook_service.py` | `build_market_snapshot` 用例 |
| `backend/tests/test_battle_plan_service.py` | F1/F2/F4/F5/F6/F7/F13 用例 |

---

### F1 · Critical：「无数据」被永久判定为「未兑现」且不可自愈

**问题**：`fetch_klines` 只在 15:00 后强刷新鲜度 → **盘前/盘中缓存里没有当天的日 K**。
早上 09:00 生成日报 → 昨日日报的 `meta.target_date` 是今天 → 取不到今天的 K 线 →
`day_ks = []` → 判定层拿到极值 `(None, None)` → 判 `missed` → **「当日未触及触发位」被永久写进昨日日报**。
更糟的是 `_persist` 的 `items_preserved` 冻结机制会让这个错误结论**永远改不掉**。

**修法（三处联动，缺一不可）**：

**(1) 判定层新增 `no_data` 状态** — `backend/app/services/fulfillment_checker.py`

把 `check_fulfillment` 里的 `else:` 分支替换为：

```python
        else:
            # 第二步:价格是否触及
            if high is None and low is None:
                # ⚠️ 目标日**没有该票的行情数据**(停牌 / 数据源未出 / 节假日)——
                # 我们根本无从判定触没触发。判 missed 等于「用无知冒充事实」:
                # 会把「没拿到数据」永久写进复盘档案(spec §4.5.3 第三步之二)。
                fulfillment = "no_data"
                note = "目标日无行情数据,未判定"
            else:
                touched = False
                if direction == "sell" and high is not None and high >= price:
                    touched = True
                if direction == "buy" and low is not None and low <= price:
                    touched = True
                if touched:
                    fulfillment = "touched"
                    note = "价格已触及触发位,但当日无对应操作"
                else:
                    fulfillment = "missed"
                    note = "当日未触及触发位(不评价对错)"
```

> 注意：纪律类分支与「无触发价 → n_a」分支**在更前面**，不受影响。
> 「当日**有流水**」的分支也在前面 → 有流水时按 `executed` 判，不受日K缺失影响。

`summarize_fulfillment` 同步改：加 `no_data` 计数，并调整 verdict 优先级。

```python
def summarize_fulfillment(items: list[dict]) -> dict[str, Any]:
    """复盘段统计口径(spec §4.5.4)

    `no_data` = 目标日无行情数据,**不计入统计**(与 n_a 同性质),
    且 verdict 不允许因为它而说成「按计划执行」——「没判定」不是「做对了」。
    """
    total = len(items or [])
    executed = touched = missed = na = no_data = 0
    discipline = 0
    for i in items or []:
        if not isinstance(i, dict):
            continue
        f = i.get("fulfillment")
        if f == "executed":
            executed += 1
            if "纪律问题" in str(i.get("fulfillment_note") or ""):
                discipline += 1
        elif f == "touched":
            touched += 1
        elif f == "missed":
            missed += 1
        elif f == "n_a":
            na += 1
        elif f == "no_data":
            no_data += 1
    if discipline > 0:
        verdict_label, verdict_level = "存在纪律问题", "danger"
    elif touched > 0:
        verdict_label, verdict_level = "有执行缺口", "warn"
    elif no_data > 0:
        verdict_label, verdict_level = "数据不足", "warn"
    elif executed > 0:
        verdict_label, verdict_level = "按计划执行", "ok"
    else:
        verdict_label, verdict_level = "无操作记录", "flat"
    return {
        "total": total, "executed": executed, "touched": touched,
        "missed": missed, "na": na, "no_data": no_data, "discipline": discipline,
        "verdict_label": verdict_label, "verdict_level": verdict_level,
    }
```

**(2) 编排层不回填 `no_data`** — `backend/app/services/battle_plan_service.py` 的 `_build_review`

回填循环里跳过 `no_data`（保持 `pending`，等数据补齐后可重判）：

```python
    # 回填昨日日报的兑现状态
    # ⚠️ `no_data` **不回填** —— 那是「没判定」,不是判定结果。
    # 写回去会让「数据不足」变成「未兑现」,还会被 items_preserved 冻结成永久结论。
    for it in checked:
        if it.get("fulfillment") == "no_data":
            continue
        try:
            await battle_plan_repo.update_item_fulfillment(
                it["id"], it["fulfillment"], it.get("fulfillment_note") or ""
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("回填兑现状态失败 item=%s: %s", it.get("id"), e)
```

**(3) 收紧 `_persist` 的冻结条件** — 只认**可信判定**

```python
# 只有基于完整数据得出的判定才可信,才允许冻结 items。
# `pending`(还没判)与 `no_data`(没数据,判不了)都**不可信** ——
# 冻结它们等于把「还没判定」永久定成「没兑现」(spec §4.6.3)。
TRUSTED_FULFILLMENTS = {"executed", "touched", "missed"}
```

`_persist` 里把

```python
        judged = any((i.get("fulfillment") or "pending") != "pending" for i in existing)
```

改成

```python
        judged = any(
            (i.get("fulfillment") or "pending") in TRUSTED_FULFILLMENTS for i in existing
        )
```

> 这样：全部 `no_data` → `judged=False` → items 重建（都是 pending）→ 数据补齐后可重判 ✓；
> 有 `executed` → `judged=True` → items 保留 ✓。

---

### F2 · Important：R 的取法从「自然日减一」改成「数据驱动」

**问题**：`prev_date = (plan_date - timedelta(days=1)).isoformat()` →
周一的减一是**周日** → 必然找不到昨日日报 → 复盘段恒为「没有找到昨日作战计划」。
更糟的是**周五面向下个交易日的预案永远停在 `pending`**，闭环每周一断裂。

**修法**：用「最近一份**早于** plan_date 的日报」当 R。

在 `backend/app/services/battle_plan_service.py` 新增：

```python
async def _find_prev_plan_date(plan_date: date) -> str | None:
    """找最近一份**早于** plan_date 的日报日期(数据驱动)。

    为什么不能用「plan_date 减一天」:周一的减一是周日 → 必然找不到;
    每个长假后的第一个交易日同理。而「上一份日报」天然就是「上一个交易日的那份」——
    不需要交易日历,也不需要节假日表。
    """
    try:
        dates = await battle_plan_repo.list_plan_dates(limit=60)
    except Exception as e:  # noqa: BLE001
        logger.warning("作战计划查找上一份日报失败: %s", e)
        return None
    for d in dates or []:
        if str(d) < plan_date.isoformat():
            return str(d)
    return None
```

`build_plan` 里把

```python
    prev_date = (plan_date - timedelta(days=1)).isoformat()
    review = await _build_review(prev_date, plan_date, degraded, todos)
```

改成

```python
    prev_date = await _find_prev_plan_date(plan_date)
    review = await _build_review(prev_date, plan_date, degraded, todos)
```

`_build_review` 的 `prev_date` 形参类型改成 `str | None`，开头加一段：

```python
    todos = list(pending_todos or [])
    if not prev_date:
        return {
            "market": None,
            "fulfillment": None,
            "pending_todos": todos,
            "note": "没有找到上一份作战计划,今日暂无兑现比对",
        }
    prev = await battle_plan_repo.get_plan(prev_date)
```

> 同步修订 spec §4.6.2 第 4 步（已在本轮 spec 提交中改）。

---

### F3 · Important：`target_date` 的基准从「指数最后一根 K 线」改成 `plan_date`

**问题**：盘中生成时指数 K 线还没到今天 → `_next_trading_day` 返回**今天** →
卡面写「明日 = 今天」，D/D+1 契约塌陷。

**修法**：

```python
def _next_trading_day(plan_date: date) -> tuple[str, bool]:
    """下一个交易日 = plan_date(D) 之后的第一个工作日。

    ⚠️ 基准必须是 **plan_date**,不能是「指数最后一根 K 线的日期」——
    盘中生成时最后一根 K 线还是昨天,用它当基准会算出「明天 = 今天」,
    把 D/D+1 契约(明日)塌成今日,整份日报的语义就错了。
    工作日推算无法覆盖法定节假日 → 恒为推算值,标注 target_date_estimated。
    """
    nxt = plan_date + timedelta(days=1)
    while nxt.weekday() >= 5:  # 跳过周末
        nxt += timedelta(days=1)
    return nxt.isoformat(), True
```

`build_plan` 里把

```python
    target_date, estimated = _next_trading_day(index_klines, plan_date)
```

改成

```python
    target_date, estimated = _next_trading_day(plan_date)
```

---

### F4 · Important：流水读取失败必须降级披露，不能静默吞掉

**问题**：`_load_transactions` 读失败时 `return []` → 调用方分不清「今天没流水」与「没读到」；
spec §六 要求这种情况必须标「流水不可用，未核对执行」。

**修法**：`battle_plan_service.py`

`_load_transactions` 改成返回 `(rows, ok)`：

```python
async def _load_transactions(plan_date: str) -> tuple[list[dict[str, Any]], bool]:
    """目标日交易流水 → (流水列表, 是否读取成功)

    第二个返回值是 `ok`:读失败时为 False,调用方**必须**据此降级披露
    (spec §六:「流水读取失败 → 只判触及不判执行,note 标注『流水不可用，未核对执行』」)。
    静默返回空列表等于把「没读到数据」说成「今天没操作」——用户无从分辨。
    """
    from app.modules.portfolio.repository import transaction_repo

    try:
        rows, _total = await transaction_repo.list_all(limit=500)
    except Exception as e:  # noqa: BLE001
        logger.warning("作战计划读取流水失败: %s", e)
        return [], False
    out: list[dict[str, Any]] = []
    for r in rows or []:
        ...   # 原有转换逻辑不变
    return out, True
```

`_build_review` 里改成：

```python
    transactions, tx_ok = await _load_transactions(target_day)
    if not tx_ok:
        degraded.append("流水不可用,今日只判触及不判执行")
    checked = check_fulfillment(prev_items, target_klines, transactions)
    if not tx_ok:
        # 没读到流水 → 不能说「当日无对应操作」(那是我们没看到,不是没有)
        for it in checked:
            if it.get("fulfillment") == "missed":
                it["fulfillment_note"] = "流水不可用,未核对执行"
            elif it.get("fulfillment") == "touched":
                # ⚠️ 文案里**不能**出现「当日无对应操作」——
                # 没读到流水 ≠ 当天没操作。触及是真的(有K线),
                # 但「没做」这句是我们**没核对**出来的,不是事实。
                it["fulfillment_note"] = "价格已触及触发位,但流水不可用,未核对执行"
```

---

### F5 · Important：取数并发化

**问题**：逐票串行 `await`，20 只票 × 2 次上游往返，60s 超时预算会被打爆。

**修法**：`battle_plan_service.py` 的 `build_plan` 里，把逐票 for 循环换成并发：

```python
    # ---- 逐票预案(并发,限流) ----
    # ⚠️ 必须并发:逐票串行 20 轮 × (K线 + 市场环境) 上游往返,
    # 会打爆前端 60s 的超时预算(spec §4.7)。单票异常已在 _build_one_decision 内隔离。
    sem = asyncio.Semaphore(6)

    async def _one(stock: dict[str, Any]):
        async with sem:
            return await _build_one_decision(stock, quotes_by_code)

    results = await asyncio.gather(
        *[_one(stock) for stock in scope], return_exceptions=True
    )

    items: list[dict[str, Any]] = []
    todos: list[dict[str, Any]] = []
    for stock, res in zip(scope, results):
        if isinstance(res, BaseException):
            degraded.append(f"{stock.get('stock_code')} 决策失败: {res}")
            continue
        decision, stock_todos, errors = res
        degraded.extend(errors)
        if decision is None:
            continue
        todos.extend(stock_todos or [])
        pos = PositionView(
            shares=int(stock.get("shares") or 0),
            avg_cost=float(stock.get("avg_cost") or 0.0),
        )
        items.extend(build_items(decision, pos if stock.get("in_position") else None))
```

文件头补 `import asyncio`（**当前文件没有 import asyncio**）。

---

### F6 · Important：`_persist` 幂等两条集成测试缺失

**问题**：spec §七 明确要求两条集成测试（同日重复生成幂等 / 已有非 pending 时 items 不被冲掉），
当前测试把 `_persist` mock 掉了 → 零覆盖。

**修法**：在 `backend/tests/test_battle_plan_service.py` 里加 2 条**不打桩 `_persist`** 的用例
（用真 DB 或 fake repo 都行，但必须真的走 `_persist`）：

- `test_persist_is_idempotent_for_same_day`：同一天连续 `upsert_plan` 两次 → `battle_plans` 里该 plan_date 只有 1 行。
- `test_persist_keeps_judged_items`：库里已有 items 且其中一条 fulfillment 是 `executed` → 再走一次 `_persist` → items 内容不变（`replace_items` 未被调用 / items 仍是原值）。
- `test_persist_replaces_items_when_all_pending`：库里 items 全是 `pending` → 再走一次 `_persist` → items 被替换成新值。
- `test_persist_replaces_items_when_only_no_data`：库里 items 全是 `no_data` → 再走一次 `_persist` → items 被替换（`no_data` 不可信，不冻结）。

---

### F7 · Important：股票池排序要保留「关注按加入时间倒序」

**问题**：`scope.sort(key=lambda s: (not s["in_position"], s["stock_code"]))` 把关注票按 code 重排，
丢掉了 `watchlist_repo.list_all()` 已经排好的 `added_at desc` → 截断时会先砍掉**最近加入**的关注票。

**修法**：`resolve_target_stocks` 里**删掉那行 sort**（`merged` 是 dict，Python 3.7+ 保序，
插入顺序 = 持仓顺序 → 关注顺序，后者已是 added_at desc）。改成注释：

```python
    scope = list(merged.values())
    # ⚠️ **不要按 stock_code 重排** —— 关注票的顺序来自 watchlist_repo.list_all()
    # (按 added_at 倒序),重排会把「最近加入的关注票」排到最后,
    # 截断上限时先砍掉最该保留的票。持仓在前、关注在后,组内保持源顺序。
```

---

### F8 · Important：`review.market` 不能恒为 `None`

**问题**：spec §4.7 的响应契约里 `review.market` 有内容，实现恒为 `None` → 「今日复盘」缺了「今天大盘怎么走」。

**修法**：在**决策层**（`backend/app/services/outlook_service.py`）加一个纯函数：

```python
def build_market_snapshot(klines: list[dict] | None, target_date: str) -> dict[str, Any] | None:
    """目标日的指数实况快照(纯函数、零 IO)→ {index_close, change_pct, volume_note}

    只做**事实转述**,不做任何指标推断:
    - index_close = 目标日收盘价
    - change_pct  = (收盘 - 前收) / 前收 × 100
    - volume_note = 目标日成交额(亿元)的文字描述

    **为什么必须放在决策层**:编排层只该做 IO 与编排;
    涨跌幅与成交额换算属于「把行情数字翻译成人话」,和 build_outlook 同域。

    目标日没有数据(盘前 / 停牌 / 节假日)→ 返回 None(调用方如实留空,不编造)。
    """
    bars = [k for k in (klines or []) if isinstance(k, dict)]
    idx = None
    for i, k in enumerate(bars):
        if str((k or {}).get("date") or "")[:10] == target_date:
            idx = i
    if idx is None:
        return None
    close = _f((bars[idx] or {}).get("close"))
    if close is None:
        return None
    prev_close = None
    if idx > 0:
        prev_close = _f((bars[idx - 1] or {}).get("close"))
    change_pct = None
    if prev_close is not None and prev_close > 0:
        change_pct = (close - prev_close) / prev_close * 100.0
    volume_note = None
    amount = _f((bars[idx] or {}).get("amount"))
    if amount is not None and amount > 0:
        volume_note = f"成交额 {amount / 1e8:.0f} 亿"
    return {
        "index_close": round(close, 2),
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "volume_note": volume_note,
    }
```

并把 `__all__` 改成 `["build_outlook", "build_market_snapshot"]`。

> ⚠️ `amount` 字段：K 线的 `amount` 是**字符串**（见数据契约），`_f` 会转 float；
> 若该日 K 线没有 amount 字段 → `volume_note` 为 None（如实留空）。

编排层接线（`battle_plan_service.py`）：

```python
from app.services.outlook_service import build_market_snapshot, build_outlook
```

`_build_review` 的两个 return 分支里，`"market": None` 改成传入快照：

```python
async def _build_review(
    prev_date: str | None,
    plan_date: str,
    degraded: list[str],
    pending_todos: list[dict[str, Any]] | None = None,
    market: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

两个 return 里的 `"market": None` 改成 `"market": market`。

`build_plan` 里：

```python
    market_snapshot = build_market_snapshot(index_klines, plan_date)
    ...
    review = await _build_review(prev_date, plan_date, degraded, todos, market_snapshot)
```

> `review.market` 是「D 当天的实况」→ 用 `plan_date`（D）而不是 target_date（D+1）✓。

---

### F9 / F11 · Minor：顶层 `todos` 键去掉；`meta.scope` 形状同步

**F11**：spec §4.7 的响应契约里**没有**顶层 `todos`（待办在 `review.pending_todos`），
而实现 `build_plan` 返回了顶层 `todos`、`get_plan` 又不返回 → 契约不对称，前端切 GET 时待办会凭空消失。

**修法**：`build_plan` 的返回 dict 里删掉 `"todos": todos,` 这一行。
`get_plan` 不用改（它本来就没有）。

**F9 / F10**：`meta.scope` 里含 `shares` / `avg_cost`（真实持仓成本）→ 不必要的数据扩散。
**修法**：`build_plan` 的 meta 里改成只留 4 个字段：

```python
        "scope": [
            {
                "stock_code": s.get("stock_code"),
                "stock_name": s.get("stock_name"),
                "in_position": bool(s.get("in_position")),
                "is_favorite": bool(s.get("is_favorite")),
            }
            for s in scope
        ],
```

（`scope` 变量本身仍带 shares/avg_cost，供决策层用；只是**落库/出参**的 meta 里裁掉。）

---

### F12 · Minor：`generated_at` 带时区

`battle_plan_service.py`：

```python
from datetime import date, datetime, timedelta, timezone
```

```python
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
```

> 本机时区为 +08:00，输出形如 `2026-10-21T15:12:33+08:00`，与 spec §4.7 示例一致。

---

### F13 · Minor：单票「决策/转换」阶段的异常未隔离

**问题**：`build_decision` / `build_todos` / `build_items` 在 try 之外 → 一只票抛异常会让**整份日报 500**。

**修法**：`battle_plan_service.py` 的 `_build_one_decision` 里，把决策与转换包进 try：

```python
    try:
        decision = build_decision(ctx)
        todos = build_todos(decision)
    except Exception as e:  # noqa: BLE001
        # 单票失败不影响其余票(spec §4.6.2 降级原则)
        return None, None, [f"{code} 决策计算失败: {e}"]
    return decision, todos, errors
```

`build_plan` 里的 `items.extend(build_items(...))` 同样要包：

```python
        try:
            items.extend(build_items(decision, pos if stock.get("in_position") else None))
        except Exception as e:  # noqa: BLE001
            degraded.append(f"{stock.get('stock_code')} 预案转换失败: {e}")
```

---

### T4-1 · Important（来自 T4 复审）：纪律守卫用例是**假锁**

**问题**：`test_discipline_item_does_not_consume_transaction` 用的是 `do_not`（`direction="none"`），
它本来就会被方向过滤排除 → 删掉实现里的纪律守卫（`_assign` 里跳过 `DISCIPLINE_KINDS`）后**30 条用例全绿**。
真正能观察该守卫的是 `unlock` 项（`plan_item_builder` 让 unlock 继承原动作的 direction 并带触发价）。

**修法**：把那条用例**换成 unlock 场景**（或新增一条 unlock 版）：

```python
def test_discipline_item_does_not_consume_transaction():
    """纪律类不参与流水归属 —— 同一笔操作可同时构成纪律违规与别的预案的执行。

    ⚠️ 必须用 **unlock**(direction=buy + 有触发价)而不是 do_not(direction=none):
    do_not 本来就会被方向过滤排除,删掉纪律守卫它照样绿 —— 那是假锁。
    """
    items = [
        _item(kind="unlock", direction="buy", price=12.50, label="解锁后建仓"),
        _item(kind="entry", direction="buy", price=9.62, label="建仓"),
    ]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.3)]},
                            [_txn(action="buy", price=9.62)])
    by_kind = {i["item_kind"]: i for i in out}
    assert by_kind["unlock"]["fulfillment"] == "executed"
    assert "纪律问题" in by_kind["unlock"]["fulfillment_note"]
    assert by_kind["entry"]["fulfillment"] == "executed"
```

> 删掉实现里的纪律守卫后，这条用例必须**转红**（`entry` 会变成 `touched`）。

---

### T4-2 / T4-3 · Minor（来自 T4 复审）

**T4-2 偏离比例比较加 `_EPS`**（spec §4.5.2.1 写明「阈值比较（价格区间、偏离比例）统一加 1e-9 容差」）：

`fulfillment_checker.py`：

```python
            if tp is not None and abs(tp - price) > price * DEVIATION_TOLERANCE + _EPS:
```

**T4-3 `t_buyback` 的同票过滤补一条用例**：

```python
def test_t_buyback_ignores_other_stock_transaction():
    """T 回补的同票过滤:别的票的买入不能算本票的回补"""
    items = [_item(kind="t_buyback", direction="buy", price=9.20, label="做T回补")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.2, low=9.4)]},
                            [_txn(code="000807.SZ", action="buy", price=9.10)])
    assert out[0]["fulfillment"] == "missed"
```

---

### 本轮必须新增的测试清单

`backend/tests/test_fulfillment_checker.py`（首轮后 33 条 → **34 条**）：

| 用例 | 锁住的规则 |
|---|---|
| `test_no_data_when_target_day_has_no_kline` | 目标日无 K 线 → `no_data`，**不是** `missed` |
| `test_no_data_not_counted_in_statistics` | `no_data` 不计入统计；verdict = 「数据不足」 |
| `test_transaction_proves_execution_even_without_kline` | 当日有流水 → `executed`（不受日K缺失影响） |
| `test_discipline_item_does_not_consume_transaction`（改写为 unlock 版） | T4-1 |
| `test_t_buyback_ignores_other_stock_transaction` | T4-3 |
| `test_deviation_exactly_3pct_not_disclosed` | T4-2 的 `_EPS`（浮点边界锁定） |

`backend/tests/test_outlook_service.py`（新增 **4 条**）：

| 用例 | 锁住的规则 |
|---|---|
| `test_market_snapshot_returns_target_day_close` | 取目标日收盘与前收算涨跌幅 |
| `test_market_snapshot_returns_none_when_target_day_missing` | 目标日无 K 线 → `None`（不编造） |
| `test_market_snapshot_volume_note_none_when_amount_missing` | 无成交额 → `volume_note` 为 None |
| `test_market_snapshot_handles_string_amount` | `amount` 是字符串 → 正确转 float |

`backend/tests/test_battle_plan_service.py`（现 7 条 → **至少 17 条**）：

| 用例 | 锁住的规则 |
|---|---|
| `test_prev_plan_date_skips_weekend` | F2：周一 → 找到的是周五那份 |
| `test_prev_plan_date_none_when_no_earlier_plan` | F2：库里没有更早的日报 → `None` |
| `test_next_trading_day_from_plan_date_not_last_bar` | F3：基准是 plan_date |
| `test_transactions_load_failure_marks_degraded` | F4：读失败 → degraded 有记录 |
| `test_transactions_failure_does_not_claim_no_operation` | F4：note 不说「当日无对应操作」 |
| `test_no_data_items_are_not_written_back` | F1：`no_data` 不回填 |
| `test_persist_is_idempotent_for_same_day` | F6 |
| `test_persist_keeps_judged_items` | F6 |
| `test_persist_replaces_items_when_all_pending` | F6 |
| `test_persist_replaces_items_when_only_no_data` | F1/F6 |
| `test_scope_keeps_favorite_order_by_added_at_desc` | F7：关注顺序不被 code 重排 |
| `test_scope_meta_excludes_cost_fields` | F9：meta.scope 只有 4 字段 |
| `test_review_market_snapshot_present` | F8 |
| `test_top_level_todos_removed` | F11：顶层无 `todos` |
| `test_generated_at_has_timezone` | F12 |
| `test_one_stock_failure_does_not_break_others` | F13 |

---

### 本轮验收

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_fulfillment_checker.py tests/test_outlook_service.py tests/test_battle_plan_service.py -q --no-header -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m pytest -q --no-header -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m ruff check app/services/fulfillment_checker.py app/services/outlook_service.py app/services/battle_plan_service.py tests/test_fulfillment_checker.py tests/test_outlook_service.py tests/test_battle_plan_service.py
```

- 三个测试文件**全绿**（用例数按上表：33 / +4 / ≥17）。
- **全量回归 0 failed**。
- 六个文件 ruff `All checks passed!`。
  （全仓 `ruff check app tests` 有 **224 条历史存量**，不在本轮范围 —— 见 T9 Step 2。）

---

## Task 6 · fix round 2（两条裁决落地）

> **背景**：fix round 1 已落（commit `814adde`，6 文件 / +768 / −67；三文件 90 passed；全量 1255 passed；
> 19 项判别力破坏实验全部转红 + 复原）。实现者上报两条**待裁决项**，父会话裁决如下。

### R1 · F4 的 `touched` note 文案自相矛盾 → 改文案

**问题**：简报给的文案是「价格已触及触发位，但**当日无对应操作**(流水不可用，未核对执行)」，
但 F4 的整改目的恰恰是「**不得**说『当日无对应操作』——那是我们没看到，不是没有」。
前半句说「当日无对应操作」，等于把「没核对」写成了事实，与 F4 的整改目标直接冲突。
（实现者按简报原文落地，并如实上报了矛盾 —— 判断正确。）

**裁决**：**改文案**，触及分支不再声称「当日无对应操作」。

`backend/app/services/battle_plan_service.py` 的 `_build_review` 里，把

```python
            elif it.get("fulfillment") == "touched":
                it["fulfillment_note"] = "价格已触及触发位,但当日无对应操作(流水不可用,未核对执行)"
```

改成

```python
            elif it.get("fulfillment") == "touched":
                # ⚠️ 文案里**不能**出现「当日无对应操作」——
                # 没读到流水 ≠ 当天没操作。触及是真的(有K线),
                # 但「没做」这句是我们**没核对**出来的,不是事实。
                it["fulfillment_note"] = "价格已触及触发位,但流水不可用,未核对执行"
```

同步更新 `backend/tests/test_battle_plan_service.py` 里断言该文案的用例
（若它断言的是旧文案字符串 → 改成新字符串；若它断言「不含『当日无对应操作』」→ 不动）。

### R2 · 偏离比较的 `_EPS` 没有用例锁定 → 补 1 条

**问题**：T4-2 改了 `abs(tp - price) > price * DEVIATION_TOLERANCE + _EPS`，
但既有的两条偏离用例（10.00/10.20 与 10.00/10.40）**破坏 `_EPS` 后依然全绿** → 这次改动等于无锁改动。

**修法**：在 `backend/tests/test_fulfillment_checker.py` 补一条**恰好卡在 3% 边界**的用例
（代码见 fix round 1 章节的测试清单，完整代码块已写进 Task 4 段的测试代码块）：

```python
def test_deviation_exactly_3pct_not_disclosed():
    """恰好 3% 偏离 → 不披露(**浮点边界**,正是 `_EPS` 存在的原因)

    触发价 10.00 / 成交 10.30:数学上正好 3%,但浮点表示下
    `abs(10.30 - 10.00) = 0.30000000000000071` > `10.00 * 0.03 = 0.29999999999999999`。
    没有 `_EPS` 就会把它误判成「超过 3%」而披露 —— 恰好 3% 不该披露。
    """
    items = [_item(kind="entry", direction="buy", price=10.00, label="建仓")]
    out = check_fulfillment(items, {"001896.SZ": [_kline(high=10.5, low=9.9)]},
                            [_txn(action="buy", price=10.30)])
    assert out[0]["fulfillment"] == "executed"
    assert "不符" not in out[0]["fulfillment_note"]
```

**必须验证判别力**：把实现里的 `+ _EPS` 去掉，这条用例**必须转红**；复原后转绿。

### 本轮验收

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_fulfillment_checker.py tests/test_outlook_service.py tests/test_battle_plan_service.py -q --no-header -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m pytest -q --no-header -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m ruff check app/services/fulfillment_checker.py app/services/outlook_service.py app/services/battle_plan_service.py tests/test_fulfillment_checker.py tests/test_outlook_service.py tests/test_battle_plan_service.py
```

- 三文件 **91 passed**（34 / 32 / 25）。
- 全量 **1256 passed, 0 failed**。
- 6 个文件 ruff `All checks passed!`。

> ⚠️ **行尾陷阱（实现者已踩过一次）**：在 Windows 上用 `Path.write_text()` 复原文件会把 LF 写成 CRLF，
> 造成整文件级 diff（1700 行）。改文件再复原的脚本**必须用 `newline=""` 或直接读写 bytes**。

---

## Task 7: HTTP 端点 + 前端 API 与类型

**Files:**
- Create: `backend/app/api/battle_plan.py`
- Modify: `backend/app/main.py`（注册路由）
- Test: `backend/tests/test_battle_plan_api.py`
- Create: `frontend/src/lib/planTypes.ts`（作战计划类型 —— **独立文件，不进 types.ts**）
- Modify: `frontend/src/lib/api/advanced.ts`（+API 客户端）

**Interfaces:**
- Consumes: Task 6 的 `build_plan` / `get_plan` / `resolve_target_stocks`
- Produces: `GET /api/battle-plan`、`POST /api/battle-plan/generate`、`GET /api/battle-plan/scope`；前端 `fetchBattlePlan` / `generateBattlePlan` / `fetchBattlePlanScope`

- [ ] **Step 1: 写失败的测试**

创建 `backend/tests/test_battle_plan_api.py`：

```python
"""作战计划 API 测试"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.battle_plan import router
from app.main import app

client = TestClient(app)


def test_get_plan_404_when_not_generated():
    r = client.get("/api/battle-plan", params={"date": "1999-01-01"})
    assert r.status_code == 404
    assert "尚未生成" in r.json()["detail"]


def test_scope_endpoint_returns_list(monkeypatch):
    from app.api import battle_plan as bp

    async def _scope():
        return [{"stock_code": "001896.SZ", "stock_name": "豫能控股",
                 "in_position": True, "is_favorite": False}]
    monkeypatch.setattr(bp, "resolve_target_stocks", _scope)
    r = client.get("/api/battle-plan/scope")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["stock_code"] == "001896.SZ"


def test_generate_endpoint_returns_plan(monkeypatch):
    from app.api import battle_plan as bp

    async def _gen(plan_date: date):
        return {
            "plan_date": plan_date.isoformat(),
            "target_date": "2026-10-22",
            "outlook": {"stance": "neutral", "stance_label": "震荡", "score": 0,
                        "dims_total": 4, "dims_effective": 4, "dims": [],
                        "key_levels": {"close": 3713.03, "ma5": None, "ma10": None,
                                       "ma20": None, "support": [], "resistance": []},
                        "disclaimer": "基于 4/4 维度规则推断，非预测；仅作明日操作参考。",
                        "degraded": False, "degraded_reason": []},
            "review": None,
            "items": [],
            "meta": {"scope_count": 1, "scope": [], "truncated": False,
                     "degraded": False, "degraded_reason": [],
                     "generated_at": "2026-10-21T15:00:00+08:00",
                     "target_date": "2026-10-22", "target_date_estimated": True},
        }
    monkeypatch.setattr(bp, "build_plan", _gen)
    r = client.post("/api/battle-plan/generate", json={})
    assert r.status_code == 200
    assert r.json()["outlook"]["stance_label"] == "震荡"


def test_get_plan_fills_degraded_outlook_when_missing(monkeypatch):
    """落库日报缺 outlook 时,端点补一个**降级**空 outlook。

    前端契约里 `outlook` 是必填非 null(组件直接读 `outlook.stance`),
    所以兜底放在端点层 —— 前端不必到处判 null。
    """
    from app.api import battle_plan as bp

    async def _get(plan_date: date):
        return {
            "plan_date": plan_date.isoformat(), "target_date": None,
            "outlook": None, "review": None, "items": [], "meta": {},
        }

    monkeypatch.setattr(bp, "get_plan", _get)
    r = client.get("/api/battle-plan", params={"date": "2026-10-21"})
    assert r.status_code == 200
    o = r.json()["outlook"]
    assert o["stance"] == "unknown"
    assert o["degraded"] is True
    assert o["dims"] == []
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_battle_plan_api.py -q --no-header -p no:cacheprovider
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.api.battle_plan'`

- [ ] **Step 3: 实现端点**

创建 `backend/app/api/battle_plan.py`：

```python
"""每日作战计划 API(阶段9)

- GET  /api/battle-plan?date=YYYY-MM-DD  取指定日期的日报(默认今天)
- POST /api/battle-plan/generate        生成今天的日报(幂等)
- GET  /api/battle-plan/scope           目标股票池(持仓 ∪ ★关注)
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.battle_plan_service import (
    build_plan,
    get_plan,
    resolve_target_stocks,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/battle-plan", tags=["battle-plan"])


class GenerateRequest(BaseModel):
    date: str | None = None


def _with_outlook(plan: dict) -> dict:
    """保证响应里 `outlook` 非 null。

    落库的日报可能没有 outlook_json(早期数据 / 写入时被裁剪),而前端契约里
    `outlook` 是**必填非 null**(组件直接读 `outlook.stance`)。
    这里填一个**降级**的空 outlook —— 如实说「数据不足」,而不是让前端到处判 null。
    """
    if plan.get("outlook"):
        return plan
    out = dict(plan)
    out["outlook"] = {
        "stance": "unknown",
        "stance_label": "数据不足",
        "score": 0,
        "dims_total": 0,
        "dims_effective": 0,
        "dims": [],
        "key_levels": {
            "close": None, "ma5": None, "ma10": None, "ma20": None,
            "support": [], "resistance": [],
        },
        "disclaimer": "数据不足，无法给出明日倾向；请重新生成作战计划。",
        "degraded": True,
        "degraded_reason": ["该日期的日报没有市场预期数据"],
    }
    return out


@router.get("")
async def read_plan(plan_date: str | None = Query(default=None, alias="date")) -> dict:
    """取指定日期的作战日报;该日未生成 → 404(不返回空壳)

    ⚠️ 形参**不能叫 `date`** —— 它会遮蔽 `from datetime import date` 这个类,
    函数体内的 `date.fromisoformat(...)` 会变成在 str 上找方法 → AttributeError → 500,
    422 的「日期格式」分支永远走不到。这里用 `plan_date` + `Query(alias="date")`:
    对外查询参数仍是 `?date=YYYY-MM-DD`。
    """
    if plan_date:
        try:
            target = date.fromisoformat(plan_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from None
    else:
        target = date.today()
    try:
        plan = await get_plan(target)
    except Exception as e:  # noqa: BLE001
        # 迁移未执行时会是 `no such table: battle_plans` —— 必须转成可读的 500,
        # 不能把裸栈/原始驱动错误抛给前端
        logger.exception("读取作战计划失败")
        raise HTTPException(status_code=500, detail=f"读取作战计划失败: {e}") from e
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail=f"{target.isoformat()} 的作战计划尚未生成",
        )
    return _with_outlook(plan)


@router.post("/generate")
async def generate(req: GenerateRequest | None = None) -> dict:
    """生成指定日期(默认今天)的作战日报"""
    target = date.today()
    if req and req.date:
        try:
            target = date.fromisoformat(req.date)
        except ValueError:
            raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD") from None
    try:
        return _with_outlook(await build_plan(target))
    except ValueError as e:
        # build_plan 在股票池为空时抛 ValueError —— 转成可读的 422,不要 500
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        logger.exception("生成作战计划失败")
        raise HTTPException(status_code=500, detail=f"生成作战计划失败: {e}") from e


@router.get("/scope")
async def scope() -> list[dict]:
    """目标股票池(持仓 ∪ ★关注 去重)"""
    return await resolve_target_stocks()


__all__ = ["router"]
```

- [ ] **Step 4: 注册路由**

在 `backend/app/main.py` 的 import 区加入：

```python
from app.api.battle_plan import router as battle_plan_router
```

并在 `include_router` 区加入：

```python
app.include_router(battle_plan_router, prefix="/api")
```

> ⚠️ 路由顺序：`/battle-plan/scope` 必须**先于** `/battle-plan` 注册吗？—— 不需要。FastAPI 按路径精确匹配，`/battle-plan` 与 `/battle-plan/scope` 是不同路径，`scope` 不会被 `""` 路由吞掉（`""` 只匹配 `/api/battle-plan`）。

- [ ] **Step 5: 运行测试确认通过**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest tests/test_battle_plan_api.py -q --no-header -p no:cacheprovider
```

Expected: 全部 PASS（4 passed）。

- [ ] **Step 6: 前端类型与 API**

创建 `frontend/src/lib/planTypes.ts`：

> ⚠️ **为什么不写进 `src/lib/types.ts`**：那个文件是「手写 stub + OpenAPI 生成物」拼起来的，
> 而 `package.json` 里有 `"gen-types": "openapi-typescript ... -o src/lib/types.ts"` ——
> **跑一次 `npm run gen-types` 整个文件就被覆盖，手写部分全丢**。
> 作战计划类型是手写的（后端返回体没有 OpenAPI schema 化），必须放独立文件才不会被冲掉。

```typescript
/* ============================================================
 * 每日作战计划(阶段9)类型
 *
 * ⚠️ 独立文件,不进 src/lib/types.ts ——
 *    那个文件会被 `npm run gen-types`(openapi-typescript -o src/lib/types.ts)整体覆盖。
 *    本文件的类型是手写的,后端没有 schema 化到 OpenAPI。
 * ============================================================ */

export type BattlePlanStance = 'bullish' | 'bearish' | 'neutral' | 'unknown';

export interface BattlePlanDim {
  key: string;
  label: string;
  score: number;
  state: 'bull' | 'bear' | 'flat' | 'missing';
  detail: string;
}

export interface BattlePlanKeyLevels {
  close: number | null;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  support: number[];
  resistance: number[];
}

export interface BattlePlanOutlook {
  stance: BattlePlanStance;
  stanceLabel: string;
  score: number;
  dimsTotal: number;
  dimsEffective: number;
  dims: BattlePlanDim[];
  keyLevels: BattlePlanKeyLevels;
  disclaimer: string;
  degraded: boolean;
  degradedReason: string[];
}

export interface BattlePlanItem {
  id?: number;
  stockCode: string;
  stockName: string | null;
  itemKind: string;
  direction: 'buy' | 'sell' | 'none';
  label: string;
  triggerPrice: number | null;
  triggerCondition: string;
  basis: string[];
  invalidIf: string;
  statusNow: 'now' | 'armed' | 'blocked';
  /** 溯源:decision.actions / decision.stop_loss / decision.t_plan / decision.do_not */
  source: string;
  /** `no_data` = 目标日无该票行情数据 → 未判定(不计入统计) */
  fulfillment: 'pending' | 'touched' | 'executed' | 'missed' | 'n_a' | 'no_data';
  fulfillmentNote: string;
}

export interface BattlePlanTodo {
  stockCode: string;
  stockName: string | null;
  label: string;
  condition: string;
  price: number | null;
  basis: string[];
}

export interface BattlePlanFulfillment {
  total: number;
  executed: number;
  touched: number;
  missed: number;
  na: number;
  /** 目标日无行情数据 → 未判定(不计入统计) */
  noData: number;
  discipline: number;
  verdictLabel: string;
  verdictLevel: 'ok' | 'warn' | 'danger' | 'flat';
  items?: Array<{
    stockCode: string;
    stockName: string | null;
    label: string;
    itemKind: string;
    fulfillment: string;
    note: string;
  }>;
}

/** 今日大盘实况(D 当天)—— 事实转述,不含任何指标推断 */
export interface BattlePlanMarket {
  indexClose: number | null;
  changePct: number | null;
  volumeNote: string | null;
}

export interface BattlePlanReview {
  market: BattlePlanMarket | null;
  fulfillment: BattlePlanFulfillment | null;
  /** 今日待办(now 动作)—— 早于该字段落库的日报可能没有它,故可选 */
  pendingTodos?: BattlePlanTodo[];
  note: string | null;
}

export interface BattlePlanMeta {
  scopeCount: number;
  scope: Array<{
    stockCode: string;
    stockName: string | null;
    inPosition: boolean;
    isFavorite: boolean;
  }>;
  truncated: boolean;
  degraded: boolean;
  degradedReason: string[];
  generatedAt: string;
  targetDate: string | null;
  targetDateEstimated: boolean;
  /** 重新生成时保留了原有 items(已有兑现判定)—— 见 spec §4.6.3 */
  itemsPreserved?: boolean;
}

export interface BattlePlan {
  planDate: string;
  targetDate: string | null;
  /** 非 null —— 端点层保证:落库日报缺 outlook 时会填一个降级的空 outlook(spec §4.6.4) */
  outlook: BattlePlanOutlook;
  review: BattlePlanReview | null;
  items: BattlePlanItem[];
  /**
   * ⚠️ **没有顶层 `todos`** —— 待办统一在 `review.pending_todos`。
   * 契约对称性:POST 与 GET 返回的字段集必须一致,否则前端切到 GET 时待办会凭空消失。
   */
  meta: BattlePlanMeta;
}

/** 目标股票池(持仓 ∪ ★关注) */
export interface BattlePlanScopeRow {
  stockCode: string;
  stockName: string | null;
  inPosition: boolean;
  isFavorite: boolean;
}
```

在 `frontend/src/lib/api/advanced.ts` **顶部**（第 8 行 `import { apiDelete, apiGet, ... } from '@/lib/api';` 之后）加一行 type import：

```typescript
import type { BattlePlan, BattlePlanScopeRow } from '@/lib/planTypes';
```

然后在 `frontend/src/lib/api/advanced.ts` **末尾**追加：

```typescript
/* ============================================================
 * 阶段9 每日作战计划
 * ============================================================ */

/** 作战计划生成要拉 11 只票的行情,默认 10s 超时不够 */
const PLAN_TIMEOUT = { timeout: 60000 };

export async function fetchBattlePlan(date?: string): Promise<BattlePlan> {
  const q = date ? `?date=${encodeURIComponent(date)}` : '';
  return apiGet<BattlePlan>(`/battle-plan${q}`);
}

export async function generateBattlePlan(date?: string): Promise<BattlePlan> {
  return apiPost<BattlePlan>('/battle-plan/generate', { date: date ?? null }, PLAN_TIMEOUT);
}

export async function fetchBattlePlanScope(): Promise<BattlePlanScopeRow[]> {
  // ⚠️ 响应经 axios 拦截器做过 snake→camel(见 lib/api.ts),
  // 所以运行时拿到的是 stockCode / stockName / inPosition / isFavorite —— 类型必须按驼峰写,
  // 写成 snake_case 的话 TS 不报错(泛型是断言),但页面读出来全是 undefined。
  // ⚠️ 必须写显式泛型,否则返回 any,ScopeRow 的字段拼错也没人拦。
  return apiGet<BattlePlanScopeRow[]>('/battle-plan/scope');
}
```

- [ ] **Step 7: 前端类型检查**

```powershell
Set-Location 'D:\zga-study\rich\frontend'
npm run typecheck
```

Expected: 零错误。

- [ ] **Step 8: Commit**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/api/battle_plan.py backend/app/main.py backend/tests/test_battle_plan_api.py frontend/src/lib/planTypes.ts frontend/src/lib/api/advanced.ts
git commit -m "feat(plan): 作战计划 API + 前端类型与客户端

- GET /api/battle-plan?date= (未生成返回 404,不返回空壳)
- POST /api/battle-plan/generate (幂等,60s 超时)
- GET /api/battle-plan/scope (目标股票池)
- 前端类型严格对齐后端契约(已按 snakeToCamel 后的驼峰命名)"
```

---

## Task 8: 前端「作战计划」页面

**Files:**
- Create: `frontend/src/app/(app)/plan/page.tsx`
- Create: `frontend/src/components/plan/PlanPanel.tsx`
- Create: `frontend/src/components/plan/OutlookCard.tsx`
- Create: `frontend/src/components/plan/PlanItemList.tsx`
- Create: `frontend/src/components/plan/ReviewCard.tsx`
- Modify: `frontend/src/components/shell/NavRail.tsx`（+导航项）

**Interfaces:**
- Consumes: Task 7 的 `fetchBattlePlan` / `generateBattlePlan`
- Produces: 路由 `/plan`

**配色速查（本任务所有 class 必须来自此表，见 Global Constraints 13）**：
- 买入/看多/涨 → `text-up`；卖出/看空/跌 → `text-down`；预警/失效条件/降级 → `text-warn`
- 正文 `text-text-pri`、次要 `text-text-sec`、弱化 `text-text-ter`
- 边框 `border-border-def`；预警边框 `border-warn/40`；降级底色 `bg-warn-bg`
- 参照实现：`frontend/src/components/desk/DecisionCard.tsx`（已用 `text-up` / `border-up/40` / `bg-up-bg` 这套）

- [ ] **Step 1: 创建页面壳**

创建 `frontend/src/app/(app)/plan/page.tsx`：

```tsx
import { PageShell } from '@/components/shell/PageShell';
import { PlanPanel } from '@/components/plan/PlanPanel';

/** /plan · 每日作战计划(今日复盘 + 明日市场预期 + 明日逐票操作预案) */
export default function PlanPage() {
  return (
    <PageShell
      title="作战计划"
      subtitle="今日复盘 + 明日市场预期 + 明日逐票操作预案:明天什么价位做什么,写在这里"
      icon="🗓"
    >
      <PlanPanel />
    </PageShell>
  );
}
```

> ⚠️ `PageShell` 的 `title: string` 是**必填**（`components/shell/PageShell.tsx` 的 props 类型里没有 `?`）——只传 children 会直接 TS 报错。
> 参照实现：`frontend/src/app/(app)/brief/page.tsx`（它传了 title / subtitle / icon）。
> ⚠️ `PageShell` 内部已带 `max-w-6xl mx-auto` 宽度上限（约 1152px），**不要再自己加 max-width**；
> 两栏布局（`xl:grid-cols-[minmax(0,1fr)_360px]`）在这个内容宽度内成立。

- [ ] **Step 2: 创建明日市场预期卡**

创建 `frontend/src/components/plan/OutlookCard.tsx`：

```tsx
'use client';

import { Card } from '@/components/ui/Card';
import type { BattlePlanOutlook } from '@/lib/planTypes';

const STANCE_STYLE: Record<string, string> = {
  bullish: 'text-up',
  bearish: 'text-down',
  neutral: 'text-text-pri',
  unknown: 'text-text-ter',
};

const DIM_STYLE: Record<string, string> = {
  bull: 'text-up',
  bear: 'text-down',
  flat: 'text-text-sec',
  missing: 'text-text-ter',
};

export function OutlookCard({ outlook }: { outlook: BattlePlanOutlook }) {
  return (
    <Card>
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">明日市场预期</h3>
        <span className={`text-lg font-bold ${STANCE_STYLE[outlook.stance] ?? ''}`}>
          倾向：{outlook.stanceLabel}
        </span>
      </div>

      <p className="mt-1 text-[11px] text-text-ter">{outlook.disclaimer}</p>

      <ul className="mt-3 space-y-2">
        {outlook.dims.map((d) => (
          <li key={d.key} className="flex items-start gap-2 text-xs">
            <span className="w-16 shrink-0 text-text-sec">{d.label}</span>
            <span className={`w-10 shrink-0 font-mono ${DIM_STYLE[d.state] ?? ''}`}>
              {d.state === 'missing' ? '缺失' : d.score > 0 ? '偏多' : d.score < 0 ? '偏空' : '中性'}
            </span>
            <span className="flex-1 text-text-pri">{d.detail}</span>
          </li>
        ))}
      </ul>

      <div className="mt-4 border-t border-border-def pt-3 text-xs">
        <div className="text-text-sec">关键位</div>
        <div className="mt-1.5 grid grid-cols-2 gap-2">
          <div>
            <div className="text-[11px] text-text-ter">支撑</div>
            <div className="font-mono text-up">
              {outlook.keyLevels.support.length
                ? outlook.keyLevels.support.join(' / ')
                : '—'}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-text-ter">压力</div>
            <div className="font-mono text-down">
              {outlook.keyLevels.resistance.length
                ? outlook.keyLevels.resistance.join(' / ')
                : '—'}
            </div>
          </div>
        </div>
        {outlook.keyLevels.close !== null && (
          <div className="mt-2 text-[11px] text-text-ter">
            上证收盘 {outlook.keyLevels.close} · MA5 {outlook.keyLevels.ma5 ?? '—'} · MA10{' '}
            {outlook.keyLevels.ma10 ?? '—'} · MA20 {outlook.keyLevels.ma20 ?? '—'}
          </div>
        )}
      </div>
    </Card>
  );
}
```

- [ ] **Step 3: 创建预案清单**

创建 `frontend/src/components/plan/PlanItemList.tsx`：

```tsx
'use client';

import { Card } from '@/components/ui/Card';
import type { BattlePlanItem } from '@/lib/planTypes';

const KIND_LABEL: Record<string, string> = {
  entry: '建仓',
  add: '加仓',
  exit: '止盈',
  stop: '止损',
  t_sell: '做T减',
  t_buyback: '做T接',
  watch: '观察',
  unlock: '解锁后',
  do_not: '别动',
};

const FULFILL_LABEL: Record<string, string> = {
  pending: '待验证',
  touched: '已触及',
  executed: '已执行',
  missed: '未触发',
  n_a: '不适用',
  no_data: '数据不足',
};

function dirClass(direction: string): string {
  if (direction === 'buy') return 'text-up';
  if (direction === 'sell') return 'text-down';
  return 'text-text-sec';
}

export function PlanItemList({
  items,
  targetDate,
}: {
  items: BattlePlanItem[];
  targetDate: string | null;
}) {
  const byStock = new Map<string, BattlePlanItem[]>();
  for (const it of items) {
    const arr = byStock.get(it.stockCode) ?? [];
    arr.push(it);
    byStock.set(it.stockCode, arr);
  }

  if (items.length === 0) {
    return (
      <Card>
        <h3 className="text-sm font-semibold">明日操作预案</h3>
        <p className="mt-2 text-xs text-text-sec">
          当前覆盖的股票暂无操作预案 —— 明日仅观察,不主动开仓。
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">明日操作预案</h3>
        <span className="text-[11px] text-text-ter">
          目标日 {targetDate ?? '—'} · 共 {items.length} 条
        </span>
      </div>

      {[...byStock.entries()].map(([code, list]) => (
        <Card key={code}>
          <div className="flex items-baseline justify-between">
            <div className="text-sm font-semibold">
              {/* ⚠️ tsconfig 开了 `noUncheckedIndexedAccess` → `list[0]` 类型是
                  `BattlePlanItem | undefined`,直接写 list[0].stockName 编译不过。
                  必须用可选链。 */}
              {list[0]?.stockName ?? code}{' '}
              <span className="ml-1 font-mono text-[11px] text-text-ter">{code}</span>
            </div>
          </div>

          <div className="mt-2 space-y-2">
            {list.map((it, idx) => (
              <div key={`${code}-${idx}`} className="rounded border border-border-def p-2.5">
                <div className="flex items-center gap-2 text-xs">
                  <span className="rounded bg-bg-subtle px-1.5 py-0.5 text-[10px] text-text-sec">
                    {KIND_LABEL[it.itemKind] ?? it.itemKind}
                  </span>
                  <span className={`font-semibold ${dirClass(it.direction)}`}>{it.label}</span>
                  {it.triggerPrice !== null && (
                    <span className={`font-mono ${dirClass(it.direction)}`}>
                      {it.triggerPrice.toFixed(2)}
                    </span>
                  )}
                  {it.fulfillment !== 'pending' && (
                    <span className="ml-auto text-[10px] text-text-ter">
                      {FULFILL_LABEL[it.fulfillment] ?? it.fulfillment}
                    </span>
                  )}
                </div>

                <p className="mt-1.5 text-xs leading-relaxed text-text-pri">
                  {it.triggerCondition}
                </p>

                {it.basis.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5">
                    {it.basis.map((b, bi) => (
                      <li key={bi} className="text-[11px] text-text-sec">
                        依据：{b}
                      </li>
                    ))}
                  </ul>
                )}

                {it.invalidIf && (
                  <p className="mt-1.5 text-[11px] text-warn">失效：{it.invalidIf}</p>
                )}

                {it.fulfillmentNote && (
                  <p className="mt-1.5 text-[11px] text-text-ter">{it.fulfillmentNote}</p>
                )}
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: 创建复盘卡**

创建 `frontend/src/components/plan/ReviewCard.tsx`：

```tsx
'use client';

import { Card } from '@/components/ui/Card';
import type { BattlePlanReview } from '@/lib/planTypes';

const LEVEL_STYLE: Record<string, string> = {
  // 「按计划执行」不是行情方向 → 用中性正文色(红=买/涨、绿=卖/跌,都不能用来表示"做得好")
  ok: 'text-text-pri',
  warn: 'text-warn',      // 琥珀只给预警:执行缺口
  danger: 'text-danger',  // 语义错误色:纪律问题
  flat: 'text-text-sec',
};

export function ReviewCard({ review }: { review: BattlePlanReview | null }) {
  const todos = review?.pendingTodos ?? [];
  return (
    <Card>
      <h3 className="text-sm font-semibold">今日复盘</h3>

      {/* 今日大盘实况 —— 与兑现比对是两个独立来源:
          market 是「今天大盘怎么走」(事实),fulfillment 是「昨天预案兑现没」(判定)。
          两者可能一个有值另一个没有,所以 market 单独渲染,不受下面那个分支影响。 */}
      {review?.market && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
          <span className="text-text-sec">
            上证 {review.market.indexClose?.toFixed(2) ?? '—'}
          </span>
          {review.market.changePct !== null && (
            <span className={review.market.changePct >= 0 ? 'text-up' : 'text-down'}>
              {review.market.changePct >= 0 ? '+' : ''}
              {review.market.changePct.toFixed(2)}%
            </span>
          )}
          {review.market.volumeNote && (
            <span className="text-text-ter">{review.market.volumeNote}</span>
          )}
        </div>
      )}

      {!review || !review.fulfillment ? (
        <p className="mt-2 text-xs text-text-sec">
          {review?.note ?? '还没有可比的昨日预案 —— 生成一次作战计划后,明天这里会显示兑现情况。'}
        </p>
      ) : (
        <>
          <div className="mt-2 text-xs text-text-sec">
            昨日预案 {review.fulfillment.total} 条
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
            <span className="text-text-pri">执行 {review.fulfillment.executed}</span>
            <span className="text-warn">触及未做 {review.fulfillment.touched}</span>
            <span className="text-text-sec">未触发 {review.fulfillment.missed}</span>
            {review.fulfillment.na > 0 && (
              <span className="text-text-ter">不适用 {review.fulfillment.na}</span>
            )}
            {review.fulfillment.noData > 0 && (
              <span className="text-warn">数据不足 {review.fulfillment.noData}</span>
            )}
          </div>
          {/* ⚠️ 「昨日预案 N 条」与下面四个计数可能对不上 ——
              n_a(别动/解锁类)与 no_data(无行情数据)都**不计入统计**,
              但它们确实是「定过的预案」→ 必须显式列出,否则用户以为漏了几条。 */}
          <div
            className={`mt-1.5 text-xs font-semibold ${LEVEL_STYLE[review.fulfillment.verdictLevel] ?? ''}`}
          >
            {review.fulfillment.verdictLabel}
          </div>

          {todos.length > 0 && (
            <div className="mt-3 border-t border-border-def pt-2">
              <div className="text-[11px] text-text-ter">今日待办（条件已满足但未处理）</div>
              <ul className="mt-1 space-y-1">
                {todos.map((t, i) => (
                  <li key={i} className="text-xs text-text-pri">
                    <span className="font-semibold">{t.stockName ?? t.stockCode}</span>
                    {' · '}
                    {t.label}
                    {t.price !== null && <span className="font-mono"> {t.price.toFixed(2)}</span>}
                    <span className="block text-[11px] text-text-sec">{t.condition}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
```

- [ ] **Step 5: 创建主容器**

创建 `frontend/src/components/plan/PlanPanel.tsx`：

```tsx
'use client';

import { useCallback, useEffect, useState } from 'react';

import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { PlanItemList } from '@/components/plan/PlanItemList';
import { OutlookCard } from '@/components/plan/OutlookCard';
import { ReviewCard } from '@/components/plan/ReviewCard';
import {
  fetchBattlePlan,
  fetchBattlePlanScope,
  generateBattlePlan,
} from '@/lib/api/advanced';
import type { BattlePlan } from '@/lib/planTypes';

type State =
  | { kind: 'loading' }
  | { kind: 'empty'; message: string }
  | { kind: 'ready'; plan: BattlePlan }
  | { kind: 'error'; message: string }
  | { kind: 'generating' };

type ScopeRow = {
  stockCode: string;
  stockName: string | null;
  inPosition: boolean;
  isFavorite: boolean;
};

/** 后端 detail 才是人话;axios 的 e.message 只是 "Request failed with status code 404" */
function messageOf(e: unknown): string {
  const anyE = e as { response?: { data?: { detail?: unknown } } } | null;
  const d = anyE?.response?.data?.detail;
  if (typeof d === 'string' && d) return d;
  return e instanceof Error ? e.message : String(e);
}

/** 用 HTTP status 判定 404,不靠字符串匹配 */
function statusOf(e: unknown): number | undefined {
  return (e as { response?: { status?: number } } | null)?.response?.status;
}

export function PlanPanel() {
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [scope, setScope] = useState<ScopeRow[]>([]);

  const load = useCallback(async () => {
    setState({ kind: 'loading' });
    try {
      const plan = await fetchBattlePlan();
      setState({ kind: 'ready', plan });
    } catch (e) {
      if (statusOf(e) === 404) {
        setState({ kind: 'empty', message: '今天的作战计划还没生成' });
        // 空态也要有实质内容:顺手把目标股票池拉出来(顺便用上 /scope 端点)
        try {
          setScope(await fetchBattlePlanScope());
        } catch {
          setScope([]);
        }
      } else {
        setState({ kind: 'error', message: messageOf(e) });
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const generate = useCallback(async () => {
    setState({ kind: 'generating' });
    try {
      const plan = await generateBattlePlan();
      setState({ kind: 'ready', plan });
    } catch (e) {
      setState({ kind: 'error', message: messageOf(e) });
    }
  }, []);

  if (state.kind === 'loading') {
    return (
      <div className="space-y-3">
        <Card>
          <div className="h-4 w-40 animate-pulse rounded bg-bg-subtle" />
          <div className="mt-3 h-3 w-full animate-pulse rounded bg-bg-subtle" />
          <div className="mt-2 h-3 w-3/4 animate-pulse rounded bg-bg-subtle" />
        </Card>
      </div>
    );
  }

  if (state.kind === 'generating') {
    return (
      <Card>
        <h3 className="text-sm font-semibold">正在生成作战计划…</h3>
        <p className="mt-2 text-xs text-text-sec">
          正在采集持仓与关注票的行情、指标和市场环境,请稍候（约 15~25 秒）。
        </p>
      </Card>
    );
  }

  if (state.kind === 'error') {
    return (
      <Card>
        <h3 className="text-sm font-semibold">生成失败</h3>
        <p className="mt-2 text-xs text-text-sec">{state.message}</p>
        <Button variant="secondary" size="sm" className="mt-3" onClick={() => void generate()}>
          重试
        </Button>
      </Card>
    );
  }

  if (state.kind === 'empty') {
    return (
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <h3 className="text-sm font-semibold">作战计划</h3>
          <p className="mt-2 text-xs text-text-sec">
            {state.message}。生成后会得到三段内容：
            <br />① 今日复盘（昨日预案兑现了没有）② 明日市场预期（四维度规则推断）③ 明日逐票操作预案（什么价位做什么）。
          </p>
          <Button className="mt-3" size="sm" onClick={() => void generate()}>
            生成今日计划
          </Button>

          {/* 空态不留大片虚空:把「明天要看哪些票」摆出来 */}
          <div className="mt-4 border-t border-border-def pt-3">
            <div className="text-[11px] text-text-ter">
              目标股票池（持仓 ∪ ★关注）· 共 {scope.length} 只
            </div>
            {scope.length === 0 ? (
              <p className="mt-1.5 text-[11px] text-text-sec">
                还没有持仓也没有★关注票 —— 先在「盯盘台」加自选或建一笔持仓,作战计划才有对象。
              </p>
            ) : (
              <ul className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1 sm:grid-cols-3">
                {scope.map((s) => (
                  <li key={s.stockCode} className="truncate text-[11px] text-text-pri">
                    {s.stockName ?? s.stockCode}
                    <span className="ml-1 font-mono text-text-ter">{s.stockCode}</span>
                    {s.inPosition && <span className="ml-1 text-text-sec">持仓</span>}
                    {s.isFavorite && <span className="ml-1 text-text-sec">★</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <div className="space-y-3">
          <Card>
            <h3 className="text-sm font-semibold">明日市场预期</h3>
            <p className="mt-2 text-xs text-text-sec">
              生成时会按量能、涨跌家数、均线位置、板块资金四个维度做规则推断,并给出上证关键位 ——
              只写「倾向」,不预测涨跌。
            </p>
          </Card>
          <Card>
            <h3 className="text-sm font-semibold">明日逐票操作预案</h3>
            <p className="mt-2 text-xs text-text-sec">
              每条预案都会写死:什么价位、什么条件、做什么动作、依据是什么、什么情况下作废。
            </p>
          </Card>
        </div>
      </div>
    );
  }

  const { plan } = state;
  const scopeText = plan.meta?.scopeCount
    ? `覆盖 ${plan.meta.scopeCount} 只（持仓 + ★关注）`
    : '';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">作战计划</h2>
          <p className="mt-0.5 text-[11px] text-text-ter">
            {plan.planDate} · {scopeText}
            {plan.meta?.targetDateEstimated && plan.targetDate
              ? ` · 明日按工作日推算为 ${plan.targetDate}`
              : ''}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => void generate()}>
          重新生成
        </Button>
      </div>

      {plan.meta?.degraded && (plan.meta.degradedReason ?? []).length > 0 && (
        <div className="rounded border border-warn/40 bg-warn-bg px-3 py-2 text-[11px] text-warn">
          部分数据缺失（已如实标注，未用假数据填补）：
          {plan.meta.degradedReason.join('；')}
        </div>
      )}

      {/* 窄屏(单栏)顺序:预期 → 预案 → 复盘;宽屏:左栏预案,右栏预期 + 复盘 */}
      <div
        data-testid="plan-grid"
        className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]"
      >
        <div className="order-2 xl:order-1 xl:col-start-1 xl:row-start-1">
          <PlanItemList items={plan.items ?? []} targetDate={plan.targetDate ?? null} />
        </div>
        <div className="order-1 xl:order-2 xl:col-start-2 xl:row-start-1">
          <OutlookCard outlook={plan.outlook} />
        </div>
        <div className="order-3 xl:order-3 xl:col-start-2 xl:row-start-2">
          <ReviewCard review={plan.review ?? null} />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: 导航入口**

在 `frontend/src/components/shell/NavRail.tsx` 的 `GROUPS` 数组里，**紧跟 `{ href: '/', label: '盯盘', icon: '📈' }` 这一行之后**插入（即「盯盘」组的第一项之后、「大盘」之前）：

```tsx
{ href: '/plan', label: '作战计划', icon: '🗓' },
```

> 放在「行情」组（盯盘 / 作战计划 / 大盘 / 板块 / 快讯）里 —— 作战计划是盯盘的下一步动作，与「决策」组的「复盘」（单票回放）区分开。

- [ ] **Step 7: 类型检查 + 构建**

```powershell
Set-Location 'D:\zga-study\rich'
cmd /c "scripts\dev.cmd" -Action stop
Set-Location 'D:\zga-study\rich\frontend'
npm run typecheck
npm run build
```

Expected: typecheck 零错误；build 成功，且 build 输出里能看到 `/plan` 路由。
（**不要预设路由总数** —— 当前 `frontend/src/app` 下是 25 个 `page.tsx`，
Next 的 build 输出会按 route group / 重定向折算，与文件数对不上；只核对 `/plan` 存在即可。）

- [ ] **Step 8: Commit**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- 'frontend/src/app/(app)/plan/page.tsx' frontend/src/components/plan frontend/src/components/shell/NavRail.tsx
git commit -m "feat(plan): 作战计划页面 /plan(两栏:明日预案 + 预期/复盘)

- 空态/加载/错误三态均有实质内容,首屏不留大片虚空
- 配色: 红=买/看多/涨,绿=卖/看空/跌,琥珀=失效条件与降级提示
- 失效条件用琥珀色标注(它决定预案何时作废)
- 导航新增'作战计划'入口(盯盘组),与既有'复盘'(单票回放)区分"
```

---

## Task 9: 实测复验 + 文档登记

**Files:**
- Modify: `docs/roadmap.md`
- Modify: `docs/design/trading-desk-v3-decision-card.md`（口径一致性说明）
- Test: `backend/.pytest_tmp/tb_plan_resp.js`（tabbit 脚本，gitignored）

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 实测证据 + 文档登记

- [ ] **Step 1: 后端全量回归**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest -q --no-header -p no:cacheprovider
```

Expected: **0 failed**。基线是 **1230 passed**（2026-10-21 实测，含 T4 fix2 的 30 条兑现用例）；
本轮（T6 fix1 新增 ~27 条 + T7 端点 4 条）后总数会上升 —— **记录最终数字**，不要预设。

- [ ] **Step 2: ruff 定向检查**

```powershell
Set-Location 'D:\zga-study\rich\backend'
& '.\.venv\Scripts\python.exe' -m ruff check app/services/fulfillment_checker.py app/services/outlook_service.py app/services/battle_plan_service.py app/api/battle_plan.py tests/test_fulfillment_checker.py tests/test_outlook_service.py tests/test_battle_plan_service.py tests/test_battle_plan_api.py
```
Expected: `All checks passed!`

> ⚠️ **不要跑 `ruff check app tests` 当门禁** —— 全仓有 **224 条历史存量错误**
> （`api/calculator.py` / `api/fund_flow.py` / `api/quotes.py` / `core/cost_engine.py` /
> `services/ta_service.py` / `tests/conftest.py` 等，均不在本功能范围）。
> 本功能的门禁 = **本功能涉及的 8 个文件 ruff 全绿**。
> 存量 224 条单独立项（见台账），不在阶段 9 范围内 —— spec §十一 #7 的措辞相应为
> 「**本功能涉及文件** ruff 全过」。

- [ ] **Step 3: 真机跑一遍生成（开发库）**

```powershell
Set-Location 'D:\zga-study\rich'
cmd /c "scripts\dev.cmd"
```
（启动器"失败"退出属正常，watcher 接管；等 45 秒）

```powershell
Start-Sleep -Seconds 45
$r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/battle-plan/scope' -UseBasicParsing -TimeoutSec 30
$r.Content
```

Expected: 返回持仓 5 + 关注 6 去重后的股票池（≤11 只）。

```powershell
$body = @{ date = $null } | ConvertTo-Json
$r2 = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/battle-plan/generate' -Method POST -ContentType 'application/json' -Body $body -UseBasicParsing -TimeoutSec 180
$j = $r2.Content | ConvertFrom-Json
"plan_date=$($j.plan_date)  target_date=$($j.target_date)"
"outlook: $($j.outlook.stance_label)  score=$($j.outlook.score)  dims=$($j.outlook.dims_effective)/$($j.outlook.dims_total)"
"items=$($j.items.Count)  scope=$($j.meta.scope_count)  degraded=$($j.meta.degraded)"
$j.outlook.dims | ForEach-Object { "  [$($_.label)] score=$($_.score) state=$($_.state)  $($_.detail)" }
$j.items | Select-Object -First 8 | ForEach-Object { "  $($_.stock_code) $($_.item_kind) $($_.direction) price=$($_.trigger_price)  $($_.trigger_condition)" }
```

**逐条核对（人工判断，必须如实记录）**：
1. `outlook.dims` 恰好 4 项，`dims_effective` 与非 missing 项数一致
2. `outlook.disclaimer` 含「非预测」
3. 每条 item 的 `trigger_condition` / `basis` / `invalid_if` 非空
4. **没有任何数字是编的** —— 抽查 3 条 item 的 `trigger_price` 与盯盘台决策卡上同一只票的同一动作价位是否一致
5. 持仓 5 只全部出现在 items 里（除非降级）

- [ ] **Step 4: tabbit 实拍四档响应式**

创建 `backend/.pytest_tmp/tb_plan_resp.js`（**中文一律用 `\uXXXX` 转义**）：

```javascript
// 作战计划页面响应式实拍
const widths = [1510, 1280, 1024, 820];
const results = [];

for (const w of widths) {
  await page.setViewportSize({ width: w, height: 860 });
  await page.goto("http://localhost:5173/plan", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  const info = await page.evaluate(() => {
    // 用 data-testid 定位主网格 —— 页面上有多个 .grid,取第一个会量错对象
    const grid = document.querySelector('[data-testid="plan-grid"]');
    const cols = grid ? getComputedStyle(grid).gridTemplateColumns : '';
    const order = grid
      ? Array.from(grid.children).map((el) => {
          const r = el.getBoundingClientRect();
          return { top: Math.round(r.top), text: (el.textContent || '').slice(0, 12) };
        }).sort((a, b) => a.top - b.top).map((x) => x.text)
      : [];
    return {
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      gridCols: cols,
      order,
      bodyLen: (document.body.innerText || '').length,
    };
  });
  results.push({ w, ...info });
  await page.screenshot({
    path: `D:/zga-study/rich/backend/.pytest_tmp/shot_plan_${w}.png`,
    fullPage: false,
  });
}

return results;
```

运行：

```powershell
$cli = "$env:LOCALAPPDATA\Tabbit\LocalAgent\bin\tabbit-cli.exe"
$cmd = "`"$cli`" nodejs --task `"作战计划页面响应式`" --request-id tbplan01 --timeout-ms 180000 < `"D:\zga-study\rich\backend\.pytest_tmp\tb_plan_resp.js`""
cmd /c $cmd
```

**验收**：
- 四档 `scrollWidth == clientWidth`（无横向滚动）
- 1510/1280/1024：两栏（`gridCols` 含两个值）
- 820：单栏，且 `order` 的三项依次是「明日市场预期」→「明日操作预案」→「今日复盘」
- `bodyLen > 200`（页面有实质内容，不是一片空白）

- [ ] **Step 5: 目视核对截图**

逐张读 `shot_plan_1510.png` 与 `shot_plan_820.png`，核对：
- 红色 = 买入/看多/涨；绿色 = 卖出/看空/跌；琥珀 = 失效条件
- 浮盈用红、浮亏用绿
- 首屏没有大片虚空
- 明日预期段在右栏，预案清单在左栏（1510px）；820px 时顺序为「预期 → 预案 → 复盘」

- [ ] **Step 6: roadmap 登记**

在 `docs/roadmap.md` 的「二、阶段总览」表格末尾追加一行：

```markdown
| **9** | 每日作战计划 | 今日复盘 + 明日市场预期 + 明日逐票预案(零 LLM 规则推断) | ✅ 完成(见下) |
```

并在文件末尾追加小节：

```markdown
## 阶段 9 · 每日作战计划 ✅
| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 页面 | `/plan` | 两栏:左=明日逐票预案,右=明日市场预期 + 今日复盘 |
| 明日预期 | `backend/app/services/outlook_service.py` | 四维度规则推断(量能/涨跌家数/均线/板块资金)+ 关键位;纯函数、零 LLM |
| 预案转换 | `backend/app/services/plan_item_builder.py` | 决策 actions 的 now/armed/blocked 三路分流;now → 复盘待办 |
| 兑现比对 | `backend/app/services/fulfillment_checker.py` | 昨日预案 × 今日行情+流水 → 触及/已执行/未触发/纪律问题 |
| 编排 | `backend/app/services/battle_plan_service.py` | 股票池=持仓∪★关注(≤20);唯一做 IO 的模块 |
| 端点 | `GET/POST /api/battle-plan` | 读取 / 生成 / scope |

### 设计约束（阶段 9 · 明日预期）
- **明日预期是纪律锚点,不是预测器**;只写「倾向」,必带「非预测」标注
- 偏多需 ≥2 个有效维度;偏空允许单维度(风险侧保守,刻意不对称)
- 规则参数先定死(1.10/0.90/60%/40%);未来回测校准只能改参数,不得事后调门槛
- 兑现「未触发」不评价对错(本来就没到,不是判断错)
```

- [ ] **Step 7: 卡面文档口径一致性**

在 `docs/design/trading-desk-v3-decision-card.md` 末尾追加：

```markdown
## 九、与阶段 9「作战计划」的口径一致性

阶段 9 的明日预期与本卡的七问**共用同一套数字来源**(indicators / 报价 / 持仓),
因此两处结论必须一致。已核对:

| 场景 | 决策卡 | 作战计划 | 一致性要求 |
| --- | --- | --- | --- |
| 同一只票的建仓触发价 | `action.price` | `item.trigger_price` | 必须**逐位相同**(预案直接继承决策引擎算好的价) |
| 止损价 | `stop_loss.price` | `stop` 项的 `trigger_price` | 同上 |
| 大盘涨跌家数 | `market_env.market.up_total/down_total` | 明日预期的涨跌家数维度 | 同源同值 |
| 降级标注 | `data_quality.degraded` | `meta.degraded_reason` | 口径一致,**不得**一处标降级另一处不标 |

**原则**:作战计划**不重新计算**任何价格,只把决策引擎已算好的结论转成「明天什么价位做什么」。
若两处出现不一致,说明转换层引入了新的计算 —— 这违反「价格必须来自 indicators/报价/持仓或其显式四则运算」铁律,必须回改转换层。
```

- [ ] **Step 7b: 回填前序任务 deferred 的遗留项**

这些是前序评审判定为 Minor / 不阻塞、但**必须在收尾前回填**的项。逐条改,改完跑相关测试。

**(a) `backend/app/services/position_status.py:56` 契约文字** — 现在写「`shares` 须为 int」,
但实测 float / bool / Decimal 都能过,只有字符串才 TypeError → 改成「`shares` 须为**数值**」。

**(b) `backend/app/services/position_status.py:12` 的「15 处引用」未穷尽** — 计数口径是
「代码里的名字引用数」,但 `api/stock.py` 自身还有 3 行 import + 11 行调用没算进去 →
 在 docstring 里补一句范围说明(说明这个数字指**测试与 diagnose.py** 的引用)。

**(c) 决策层零 IO 守卫测试(缺失)** — 新建 `backend/tests/test_decision_layer_purity.py`:
用 AST 扫描**四个**决策层模块(`position_status` / `outlook_service` / `plan_item_builder` /
`fulfillment_checker`),断言它们的 import 集合里**没有任何 `app.*` 之外的内部模块**,
且不含 `sqlalchemy` / `httpx` / `openai` 等 IO 或 LLM 依赖。
(注:`fulfillment` 字段名含 "llm" 子串,别把它当 LLM 引用 —— 按 AST 的 import 节点判定,不用子串扫。)

**(d) `backend/app/services/outlook_service.py` 的 `_f` 未过滤 ±inf(pre-existing)**
— `_f` 只用 `f == f` 滤 NaN,±inf 会通过;`[inf, -inf]` 求和得 NaN → 落 else 档判 flat,
文案「多空抵消,无明确主攻方向」= 数据已损坏却宣称中性,属**误导性结论**。
改法:`_f` 同时滤掉 ±inf(如 `math.isfinite`),并补 1 条测试(净额含 inf → 该维度判 missing)。

**(e) 同一模块的「0.00 亿」展示带** — 净残差 <0.005 亿时 2 位小数会显示成「0.00 亿」
(真实 `netamount_yi` 是新浪原始元/1e8 的全精度 float,可达几十万元级残差)。
改法:金额格式化时 |v| < 0.01 亿改用「万元」表述(如「净流入合计 49 万元」),不再显示 0.00。
补 1 条测试。

**(f) 记录一条已知无害的实现细节**(不改代码,写进 `docs/design/trading-desk-v3-decision-card.md` §九):
决策层的 `missing` 键目前挂在 C3 的共用 `_guard({...})` 上,故 C3 的 armed/now 动作也带该键;
转换层**只对 blocked 读它**,当前零影响;将来若有别的消费方读 `missing`,必须按 `status == "blocked"` 过滤。

**(g) 可选**:`backend/app/api/diagnose.py` 仍绕一跳取 `position_status` 的私有名
(pre-existing 耦合,非本功能引入)—— 不改,仅在台账注明。

**(h) `battle_plan_service._load_transactions` 用 `list_all(limit=500)` 再按日期过滤**（T6 评审发现）
—— 当某日流水**超过 500 条**时会漏单（漏掉的流水 → 该笔操作被误判成「没执行」）。
当前规模(单用户自选 ≤ 20 只)远不到 500,属**低概率已知边界**。
本轮不改（改法要动仓储层的分页/按日查询接口,超出阶段 9 范围）,
仅在 `docs/design/trading-desk-v3-decision-card.md` §九 记录该边界。

**(i) 统计口径说明**（T6 fix1 引入 `no_data` 后产生的新口径）
—— `summarize_fulfillment` 的 `total` = **所有预案条数**(含 `n_a` 与 `no_data`),
而 `executed + touched + missed` 不含它们 → 两者**故意不相等**。
前端必须把「不适用 N」与「数据不足 N」显式列出,否则用户以为漏了几条。
本轮已在 T8 的 ReviewCard 里补上这两项显示;此条留作口径说明记录。

**(j) 纪律 note 的标点是半角**（T4 评审 Minor）
—— `"⚠️ 纪律问题:昨日标记别动/未解锁,今日仍有操作"` 用的是半角冒号 + 半角逗号,
与项目其余中文文案的「全角标点」风格不一致。属展示层,不改(改了会让
`summarize_fulfillment` 里 `"纪律问题" in note` 的判定依赖具体文案,徒增耦合)。

- [ ] **Step 8: 最终 Commit**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- docs/roadmap.md docs/design/trading-desk-v3-decision-card.md
git commit -m "docs(plan): 阶段9 登记 + 卡面口径一致性说明

- roadmap: 阶段9 每日作战计划(明日预期四维度规则 + 预案转换 + 兑现闭环)
- 卡面文档 §九: 决策卡与作战计划共用同一套数字来源,
  触发价必须逐位相同(预案只转换,不重算)"
```

- [ ] **Step 9: 恢复 dev 服务**

```powershell
Set-Location 'D:\zga-study\rich'
cmd /c "scripts\dev.cmd"
```
（构建已完成，现在可安全重启 dev）

---

## 验收标准（对照 spec §十一）

| # | 验收项 | 落在哪个 Task | 验证方式 |
|---|---|---|---|
| 1 | API 契约符合 §4.7 | Task 7 | `test_battle_plan_api.py` |
| 2 | 每条预案有触发价/条件/依据/失效条件 | Task 3 | `test_plan_item_builder.py::test_invalid_if_present_on_every_item` |
| 3 | `now` 不进明日预案、进复盘待办 | Task 3 | `test_now_action_does_not_enter_plan_items` / `test_now_action_goes_to_todos` |
| 4 | 明日预期恰好 4 维度且计数一致 | Task 2 | `test_dims_always_four_items` |
| 5 | 含「非预测」；unknown 不给方向 | Task 2 | `test_disclaimer_always_present_and_says_not_prediction` / `test_unknown_when_all_dims_missing` |
| 6 | 昨日预案兑现回填且统计一致 | Task 4 + Task 6 | `test_executed_when_buy_transaction_present` + Task 9 Step 3 实跑 |
| 7 | 后端全量 0 failed + ruff 全过 | Task 9 | Step 1 / Step 2 |
| 8 | 前端 typecheck 零错误 + build 通过 | Task 8 | Step 7 |
| 9 | tabbit 四档布局/颜色/无横向滚动/零 error | Task 9 | Step 4 / Step 5 |
| 10 | 未生成首屏无大片虚空 | Task 8 + Task 9 | `PlanPanel` empty 分支 + 实拍 |
| 11 | roadmap 登记阶段 9 | Task 9 | Step 6 |

---

## Self-Review

**1. Spec 覆盖**：spec 的 §4.2→T5、§4.3→T2、§4.4→T3、§4.5→T4、§4.6→T6、§4.7→T7、§4.8→（无需任务，设计为不引入 LLM）、§五→T8、§六→各任务的降级分支 + T9 实测、§七→各任务的测试步骤 + T9、§八→范围约束（已写入 Global Constraints 且无任务涉及被排除项）、§九→File Structure、§十→Global Constraints、§十一→验收标准表。**无缺口**。

**2. 占位符扫描**：全部代码块为可直接落地的完整实现；无 TBD / TODO / "类似 Task N"。

**3. 类型一致性**：
- `build_outlook` / `build_items` / `build_todos` / `check_fulfillment` / `summarize_fulfillment` / `build_plan` / `get_plan` / `resolve_target_stocks` 的签名在「跨任务锁定的接口契约」中一次定义，Task 2→Task 6→Task 7 全部按此调用。
- `item_kind` 取值统一为 `entry|add|exit|stop|t_sell|t_buyback|watch|unlock|do_not`（对齐决策引擎实际 kind + 新增 unlock/do_not）。
- `fulfillment` 取值统一为 `pending|touched|executed|missed|n_a`。
- 前端类型 `BattlePlan*` 全部按 `snakeToCamel` 后的驼峰命名（`plan_date`→`planDate`），与 `api.ts` 的响应拦截器一致。

**已修正的不一致**（写计划过程中发现并已改）：
- spec §4.4 写的 `item_kind` 含 `t_plan`，实际决策引擎是 `t_sell` / `t_buyback` 两条 → 本计划统一用引擎实际 kind。
- spec §4.4 未提 `build_todos` 的实现位置 → 本计划明确它是 `plan_item_builder` 的第二个导出函数。
- spec §4.2 写的是 `db_migrations.py` 迁移 → 实际项目走 Alembic（`backend/migrations/versions/`），已按实际机制改写。
