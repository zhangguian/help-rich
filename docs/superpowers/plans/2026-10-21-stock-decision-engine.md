# 盯盘决策引擎 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给盯盘台首页右栏加一张**确定性行动卡**——选股即出「现在该做什么 + 价位 + 触发条件 + 止损 + 什么情况别动」，覆盖买/卖/做T/亏损/盈利/市场环境/走势七问，全程零 LLM 调用。

**Architecture:** 后端新增两个服务。`decision_service.py` 是**纯函数判定器**（零 IO、零 LLM、可单测可回测），消费 `ta_service.compute_indicators()` 的输出 + 持仓 + 市场环境，产出结构化决策；`market_context_service.py` 负责聚合市场环境（只读现有服务，不新增抓取逻辑）。API 层新增 `GET /api/stock/{code}/decision`，复用 `stock.py` 既有的 `_check_code` / `_load_klines` / `_load_quote` / `_sanitize_current_price` / `_resolve_position_status`。前端新增 `DecisionCard.tsx`，在 `DecisionColumn` 顶部渲染，与 analysis 请求并发、互不阻塞。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy(async) / pytest / Next.js 14 (App Router) / React 18 / TypeScript strict / Tailwind CSS

**设计文档:** `docs/superpowers/specs/2026-10-21-stock-decision-engine-design.md`（已提交 `6e455fb`）

---

## Global Constraints

以下约束对**每个** Task 都生效，无需在 Task 里重复：

1. **零 LLM**：`decision_service.py` 不得 import 任何 `app.llm.*` / `app.services.stock_advice_service`；决策层永不调用 LLM。
2. **纯函数**：`decision_service.py` 不得 import FastAPI / SQLAlchemy / DB session；所有 IO 收敛在 `market_context_service.py` 与 API 层。
3. **数字可追溯**：所有输出价格必须来自 `indicators` / 实时报价 / 持仓，或由这些值的显式四则运算得到。**禁止编造**。Task 2 的不变量测试会强制这一点。
4. **统一计算价**：一切涉及价格与百分比的计算使用 `effective_price(ctx)`（实时价优先，缺失时用 `indicators.latest_close`）。判定器内部**不得**自行判断 `current_price` 是否为 None。
5. **失败即降级**：任一数据源失败 → 对应字段为 `None` + 写入 `degraded` 列表。**不得**用 0、空串或猜测值代替。
6. **错误码沿用项目既有约定**：代码格式非法 → **422** `INVALID_STOCK_CODE`（复用 `stock.py` 的 `_check_code`，不要自造 400）；数据源不可用 → **502** `DATA_SOURCE_UNAVAILABLE`（复用 `_load_klines`）。
7. **不引入新依赖**：后端只用已有 `httpx`/`fastapi`/`pydantic`；前端只用已有 `clsx` + Tailwind。
8. **中文文案里的数字**必须能追溯到输入，不得出现「等企稳」「看情况」这类无数字表述。
9. **测试隔离**：`DATABASE_URL` 必须指向 `.pytest_tmp`，`RICH_TEST_TMP` 必须指向工程内目录（否则 Windows 沙箱权限导致整套 collect 失败）。
10. **前端构建**：`npm run build` 前必须先 `scripts\dev.cmd -Action stop`（dev 与 build 共用 `.next`）。
11. **本仓库 PowerShell 策略为 RemoteSigned**：`scripts\dev.ps1` 不可直接执行，一律用 `cmd /c "scripts\dev.cmd"`。
12. **删除文件**用可恢复方式：单独一条顶层 `rm -- "<绝对路径>"`。

---

## File Structure

| 文件 | 责任 | 状态 |
| --- | --- | --- |
| `backend/app/services/decision_service.py` | 纯判定器 + 数据契约 + `build_decision` 组装 | 新建 |
| `backend/app/services/market_context_service.py` | 市场环境聚合(大盘/行业/资金/相对强弱)，唯一有 IO 的决策相关模块 | 新建 |
| `backend/app/services/decision_backtest.py` | 回测闸门：逐日跑决策器，输出胜率/收益/回撤报告 | 新建 |
| `backend/app/api/stock.py` | 新增 `GET /{code}/decision` 端点 | 修改 |
| `backend/tests/test_decision_service.py` | 判定器单测 + 数字可追溯不变量 | 新建 |
| `backend/tests/test_market_context_service.py` | 市场环境聚合单测(mock 数据源 + 降级) | 新建 |
| `backend/tests/test_decision_api.py` | 端点契约 + 错误码 | 新建 |
| `backend/tests/test_decision_backtest.py` | 回测脚本自身正确性 | 新建 |
| `frontend/src/lib/types.ts` | `StockDecision` 等前端类型 | 修改 |
| `frontend/src/components/desk/DecisionCard.tsx` | 决策卡组件(loading/ready/error 三态) | 新建 |
| `frontend/src/components/desk/DecisionColumn.tsx` | 顶部插入决策卡 | 修改 |
| `frontend/src/app/(app)/page.tsx` | 选中股票时并发拉 decision | 修改 |
| `docs/roadmap.md` | 登记新阶段 | 修改 |

---

## 任务 1：决策引擎骨架 + 走势判定 + 做T判定

**Files:**
- Create: `backend/app/services/decision_service.py`
- Create: `backend/tests/test_decision_service.py`

**Interfaces:**
- Consumes: `app.services.ta_service.compute_indicators(klines) -> dict`（已存在，字段路径见设计文档附录 A）
- Produces:
  ```python
  # decision_service.py
  @dataclass(frozen=True)
  class MarketContext:
      market: dict[str, Any] = field(default_factory=dict)
      sector: dict[str, Any] = field(default_factory=dict)
      stock_flow: dict[str, Any] = field(default_factory=dict)
      relative: dict[str, Any] = field(default_factory=dict)
      degraded: list[str] = field(default_factory=list)

  @dataclass(frozen=True)
  class DecisionContext:
      stock_code: str
      stock_name: str | None
      indicators: dict[str, Any]
      klines: list[dict[str, Any]]
      current_price: float | None
      prev_close: float | None
      cost_basis: float | None
      shares: int
      position_status: str          # 'empty' | 'profit' | 'loss'
      env: MarketContext = field(default_factory=MarketContext)

  def effective_price(ctx: DecisionContext) -> float | None
  def judge_trend(ctx: DecisionContext) -> dict[str, Any]
      # -> {"phase": str, "note": str}
  def judge_t_plan(ctx: DecisionContext) -> dict[str, Any]
      # -> {"suitable": bool, "t_high": float|None, "t_low": float|None,
      #     "amplitude_pct": float|None, "sell_trigger": str, "buyback_trigger": str,
      #     "base_position_pct": str, "unsuitable_signals": str, "needs_position": bool}
  ```

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_decision_service.py`：

```python
"""确定性决策引擎单测(decision_service 纯函数)"""
import pytest

from app.services.decision_service import (
    DecisionContext,
    MarketContext,
    effective_price,
    judge_trend,
    judge_t_plan,
)


def _kline(closes: list[float], volumes: list[int] | None = None,
           highs: list[float] | None = None, lows: list[float] | None = None) -> list[dict]:
    out = []
    for i, c in enumerate(closes):
        out.append({
            "date": f"2026-01-{i + 1:02d}",
            "open": c * 0.99,
            "high": highs[i] if highs else c * 1.02,
            "low": lows[i] if lows else c * 0.98,
            "close": c,
            "volume": volumes[i] if volumes else 10000,
        })
    return out


def _ctx(closes, **kw) -> DecisionContext:
    from app.services.ta_service import compute_indicators
    klines = _kline(closes)
    ind = compute_indicators(klines)
    return DecisionContext(
        stock_code="002185.SZ",
        stock_name="华天科技",
        indicators=ind,
        klines=klines,
        current_price=kw.get("current_price", closes[-1]),
        prev_close=kw.get("prev_close", closes[-2] if len(closes) > 1 else closes[-1]),
        cost_basis=kw.get("cost_basis"),
        shares=kw.get("shares", 0),
        position_status=kw.get("position_status", "empty"),
        env=kw.get("env", MarketContext()),
    )


def test_effective_price_prefers_realtime():
    ctx = _ctx([10.0] * 30, current_price=12.5)
    assert effective_price(ctx) == 12.5


def test_effective_price_falls_back_to_latest_close():
    ctx = _ctx([10.0, 11.0] + [11.0] * 28, current_price=None)
    assert effective_price(ctx) == 11.0


def test_judge_trend_up_channel_accelerate():
    # 持续上涨 → 通道向上 + 量价健康
    closes = [10.0 + i * 0.3 for i in range(60)]
    ctx = _ctx(closes)
    phase = judge_trend(ctx)["phase"]
    assert "上涨通道" in phase


def test_judge_trend_note_contains_numbers():
    closes = [10.0 + i * 0.3 for i in range(60)]
    note = judge_trend(_ctx(closes))["note"]
    assert "量比" in note


def test_t_plan_unsuitable_when_amplitude_too_small():
    # 几乎无波动 → 振幅不足
    closes = [10.0] * 60
    ctx = _ctx(closes)
    plan = judge_t_plan(ctx)
    assert plan["suitable"] is False
    assert "振幅" in plan["unsuitable_signals"]


def test_t_plan_needs_position_flag_when_empty():
    closes = [10.0 + (i % 5) * 0.4 for i in range(60)]
    ctx = _ctx(closes, shares=0)
    plan = judge_t_plan(ctx)
    assert plan["needs_position"] is True


def test_t_plan_all_prices_traceable():
    closes = [10.0 + (i % 7) * 0.5 for i in range(60)]
    ctx = _ctx(closes)
    plan = judge_t_plan(ctx)
    if plan["suitable"]:
        ks = ctx.klines[-5:]
        hi = max(float(k["high"]) for k in ks)
        lo = min(float(k["low"]) for k in ks)
        assert plan["t_high"] <= round(hi, 6) + 1e-6
        assert plan["t_low"] >= round(lo, 6) - 1e-6
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest -q --no-header -p no:cacheprovider tests/test_decision_service.py
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.decision_service'`

- [ ] **Step 3: 实现 decision_service.py(本任务部分)**

创建 `backend/app/services/decision_service.py`：

```python
"""确定性盯盘决策引擎(v0.9 Trading Desk)

回答七问:该买?该卖?何时做T?亏损怎么办?盈利怎么办?市场情况?现在走势?
—— 以**可执行的条件清单**给出,而不是散文。

设计文档:docs/superpowers/specs/2026-10-21-stock-decision-engine-design.md

三条铁律:
1. 纯函数、零 IO、零 LLM —— 可单测、可回测
2. 所有价格必须来自 indicators / 实时报价 / 持仓,或其显式四则运算(禁止编造)
3. 任一输入缺失 → 对应字段为 None,并写进 degraded(绝不编数字)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---- 阈值(全部来自设计文档 §6;改动必须同步改文档) ----
T_MIN_AMPLITUDE_PCT = 3.0        # G1:做 T 所需最小近 5 日平均振幅
T_WINDOW = 5                     # 做 T 观察窗口(根)
ENTRY_MIN_VOLUME_RATIO = 1.5     # C3:突破确认所需量比
POSITION_TIERS = ((45, 10), (65, 20), (10**9, 30))  # (signal.score 上界, 首仓 %)
POSITION_ADD_CAP = 60            # 加仓上限 %
MARKET_COLD_RATIO = 1.5          # 大盘普跌:跌家数 > 涨家数 × 该系数
NEAR_LIMIT_UP_PCT = 9.5          # 近涨停判定(当日涨幅 %)
ONE_WORD_LIMIT_PCT = 0.1         # 一字板:当日振幅 < 该值 %
ADD_SHARE_RATIO = 0.3            # L4:补仓股数 = 现有股数 × 该比例
MIN_KLINES_FOR_SIGNAL = 23       # 少于该根数 → 信号不可信


@dataclass(frozen=True)
class MarketContext:
    """市场环境(由 market_context_service 构造;decision_service 只读)"""
    market: dict[str, Any] = field(default_factory=dict)
    sector: dict[str, Any] = field(default_factory=dict)
    stock_flow: dict[str, Any] = field(default_factory=dict)
    relative: dict[str, Any] = field(default_factory=dict)
    degraded: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DecisionContext:
    """决策引擎的全部输入(纯数据,不含任何 IO 对象)"""
    stock_code: str
    stock_name: str | None
    indicators: dict[str, Any]
    klines: list[dict[str, Any]]
    current_price: float | None
    prev_close: float | None
    cost_basis: float | None
    shares: int
    position_status: str          # 'empty' | 'profit' | 'loss'
    env: MarketContext = field(default_factory=MarketContext)


def _f(v: Any) -> float | None:
    """安全转 float;None / 非法值 / NaN → None"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def effective_price(ctx: DecisionContext) -> float | None:
    """统一计算价:实时价优先,缺失时用最新收盘价。

    所有判定器一律用它,不得自行判断 current_price 是否为 None。
    """
    p = _f(ctx.current_price)
    if p is not None and p > 0:
        return p
    lc = _f(ctx.indicators.get("latest_close"))
    return lc if lc is not None and lc > 0 else None


def _clamped(value: float | None) -> float | None:
    return value if value is not None else None


def judge_trend(ctx: DecisionContext) -> dict[str, Any]:
    """现在的走势如何 → {"phase": 阶段, "note": 依据}"""
    ind = ctx.indicators
    channel = (ind.get("channel") or {}).get("state") or "sideways"
    ma = ind.get("ma") or {}
    ma5, ma10, ma20, ma60 = (_f(ma.get(k)) for k in ("ma5", "ma10", "ma20", "ma60"))
    all_ma = all(v is not None for v in (ma5, ma10, ma20, ma60))
    bull_ma = all_ma and ma5 > ma10 > ma20 > ma60
    bear_ma = all_ma and ma5 < ma10 < ma20 < ma60
    vp = (ind.get("volume_price") or {}).get("direction")
    boll = ind.get("boll") or {}
    boll_pos = boll.get("position")
    squeeze = bool(boll.get("squeeze"))
    kdj_zone = (ind.get("kdj") or {}).get("zone")
    vol_ratio = _f((ind.get("volume") or {}).get("ratio"))

    if channel == "up":
        if vp == "healthy_up" or boll_pos in ("touching_upper", "above_upper"):
            phase = "上涨通道·加速"
        elif vp == "liar_up_suspect" or (
            kdj_zone == "overbought" and vol_ratio is not None and vol_ratio < 0.8
        ):
            phase = "上涨通道·滞涨"
        else:
            phase = "上涨通道·延续"
    elif channel == "down":
        if vp == "panic_sell" or boll_pos in ("touching_lower", "below_lower"):
            phase = "下跌通道·破位"
        elif kdj_zone == "oversold" and bool((ind.get("stabilize") or {}).get("state")):
            phase = "下跌通道·筑底"
        else:
            phase = "下跌通道·延续"
    else:
        phase = "震荡收敛" if squeeze else "震荡"

    if bull_ma:
        ma_txt = "多头排列 MA5>MA10>MA20>MA60"
    elif bear_ma:
        ma_txt = "空头排列 MA5<MA10<MA20<MA60"
    else:
        ma_txt = "均线缠绕"
    boll_txt = {
        "touching_upper": "布林触上轨",
        "above_upper": "布林破上轨",
        "touching_lower": "布林触下轨",
        "below_lower": "布林破下轨",
        "middle": "布林中轨附近",
    }.get(boll_pos, "布林位置未知")
    vol_txt = f"量比 {vol_ratio:.2f}" if vol_ratio is not None else "量比未知"
    return {"phase": phase, "note": f"{ma_txt},{boll_txt},{vol_txt}"}


def _daily_amplitude_pct(klines: list[dict[str, Any]]) -> list[float]:
    """逐日振幅 % = (high - low) / 昨收 * 100"""
    out: list[float] = []
    for i in range(1, len(klines)):
        h = _f(klines[i].get("high"))
        low = _f(klines[i].get("low"))
        pc = _f(klines[i - 1].get("close"))
        if h is not None and low is not None and pc is not None and pc > 0:
            out.append((h - low) / pc * 100)
    return out


def _cum_change_pct(klines: list[dict[str, Any]], days: int) -> float | None:
    """近 days 个交易日累计涨跌幅 %"""
    if len(klines) < days + 1:
        return None
    a = _f(klines[-(days + 1)].get("close"))
    b = _f(klines[-1].get("close"))
    if a is None or b is None or a <= 0:
        return None
    return (b - a) / a * 100


def _unsuitable(reason: str, needs_position: bool) -> dict[str, Any]:
    return {
        "suitable": False,
        "t_high": None,
        "t_low": None,
        "amplitude_pct": None,
        "sell_trigger": "",
        "buyback_trigger": "",
        "base_position_pct": "",
        "unsuitable_signals": reason,
        "needs_position": needs_position,
    }


def judge_t_plan(ctx: DecisionContext) -> dict[str, Any]:
    """什么时候适合做 T → TPlan"""
    ind = ctx.indicators
    pos = ind.get("position") or {}
    p20 = _f(pos.get("p20"))
    p80 = _f(pos.get("p80"))
    ep = effective_price(ctx)
    needs_position = ctx.shares <= 0

    if ep is None or p20 is None or p80 is None:
        return _unsuitable("K 线不足,无法计算 T 区间", needs_position)

    # G1 近 5 日平均振幅 ≥ 3%
    amps = _daily_amplitude_pct(ctx.klines)[-T_WINDOW:]
    if not amps:
        return _unsuitable("K 线不足,无法计算振幅", needs_position)
    avg_amp = sum(amps) / len(amps)
    if avg_amp < T_MIN_AMPLITUDE_PCT:
        return _unsuitable(
            f"近 5 日平均振幅 {avg_amp:.2f}% 不足 {T_MIN_AMPLITUDE_PCT}%,做 T 赚不到差价",
            needs_position,
        )

    # G2 当日有成交
    last_vol = ctx.klines[-1].get("volume")
    if not last_vol or int(last_vol) <= 0:
        return _unsuitable("今日无成交(停牌或一字板),无法判断", needs_position)

    # G3 非一字板:近 5 日不存在振幅 < 0.1% 的交易日
    window = ctx.klines[-T_WINDOW:]
    one_word = False
    for i, k in enumerate(window):
        h, low = _f(k.get("high")), _f(k.get("low"))
        c = _f(k.get("close"))
        if h is None or low is None or c is None or c <= 0:
            continue
        if (h - low) / c * 100 < ONE_WORD_LIMIT_PCT:
            one_word = True
            break
    if one_word:
        return _unsuitable("近 5 日出现一字板,无法做 T", needs_position)

    # G4 现价不能远低于 P20 低位带
    if ep < p20 * 0.97:
        return _unsuitable(
            f"现价已跌破 P20 低位带 {p20:.2f},下行空间不明,不建议做 T", needs_position
        )

    # 单边排除
    ma = ind.get("ma") or {}
    ma5, ma10, ma20, ma60 = (_f(ma.get(k)) for k in ("ma5", "ma10", "ma20", "ma60"))
    all_ma = all(v is not None for v in (ma5, ma10, ma20, ma60))
    bull_ma = all_ma and ma5 > ma10 > ma20 > ma60
    bear_ma = all_ma and ma5 < ma10 < ma20 < ma60
    channel = (ind.get("channel") or {}).get("state")
    up3 = _cum_change_pct(ctx.klines, 3)
    if channel == "up" and bull_ma and up3 is not None and up3 > 5:
        return _unsuitable("单边上涨,做 T 容易做飞,建议持股不动", needs_position)
    if channel == "down" and bear_ma and up3 is not None and up3 < -5:
        return _unsuitable("单边下跌,做 T 越做越低,建议只减不加", needs_position)

    # T 区间(取保守边)
    highs = [_f(k.get("high")) for k in window]
    lows = [_f(k.get("low")) for k in window]
    hi5 = max((v for v in highs if v is not None), default=None)
    lo5 = min((v for v in lows if v is not None), default=None)
    if hi5 is None or lo5 is None:
        return _unsuitable("K 线缺少最高/最低价,无法计算 T 区间", needs_position)
    t_high = min(hi5, p80)
    t_low = max(lo5, p20)
    amplitude_pct = (t_high - t_low) / ep * 100 if ep > 0 else None

    base_pct = "≥70%" if bull_ma else "≥50%"
    stop_price = _f(pos.get("stop_loss_price"))
    stop_txt = (
        f"底仓跌破 {stop_price:.2f} 元即止损,防止做 T 做飞" if stop_price is not None else ""
    )
    over_p80 = ep > p80
    sell_txt = f"冲高至 {t_high:.2f} 元附近且量能未超 5 日均量 1.5 倍时卖出 T 仓"
    if over_p80:
        sell_txt += "(现价已高于 P80,只做卖出方向)"
    buyback_txt = f"回落至 {t_low:.2f} 元附近且缩量企稳(MACD 绿柱不放大)时买回"

    return {
        "suitable": True,
        "t_high": round(t_high, 3),
        "t_low": round(t_low, 3),
        "amplitude_pct": round(amplitude_pct, 2) if amplitude_pct is not None else None,
        "sell_trigger": sell_txt,
        "buyback_trigger": buyback_txt,
        "base_position_pct": base_pct,
        "unsuitable_signals": stop_txt,
        "needs_position": needs_position,
    }
```

> ⚠️ 上面 `bear_ma` 一行必须写成 `bear_ma = all_ma and ma5 < ma10 < ma20 < ma60`。
> 下游 `_cum_change_pct(ctx.klines, 3)` 返回**带符号**的近 3 日累计涨跌幅，
> 所以「累计跌幅 > 5%」的判定写作 `up3 < -5`（不是再取一次绝对值）。

- [ ] **Step 4: 运行测试确认通过**

同 Step 2 的命令。

Expected: PASS —— `7 passed`

- [ ] **Step 5: 提交**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/services/decision_service.py backend/tests/test_decision_service.py
git commit -m "feat(decision): 决策引擎骨架 + 走势判定 + 做T判定"
```

---

## 任务 2：买/卖/亏损/不动作判定 + verdict 组装

**Files:**
- Modify: `backend/app/services/decision_service.py`
- Modify: `backend/tests/test_decision_service.py`

**Interfaces:**
- Consumes: 任务 1 的 `DecisionContext` / `effective_price` / `judge_trend` / `judge_t_plan`
- Produces:
  ```python
  def judge_entry(ctx: DecisionContext) -> list[dict[str, Any]]     # -> Action[]
  def judge_exit(ctx: DecisionContext) -> list[dict[str, Any]]      # -> Action[]
  def judge_loss_plan(ctx: DecisionContext) -> list[dict[str, Any]] # -> Action[]
  def judge_do_not(ctx: DecisionContext) -> list[str]
  def derive_verdict(actions: list[dict], position_status: str) -> str
  def build_decision(ctx: DecisionContext) -> dict[str, Any]        # -> 完整决策 dict
  ```
  `Action` 结构：`{"kind","label","condition","price","basis","status"}`
  `build_decision` 返回键：`stock_code, stock_name, verdict, headline, confidence, role,
  position_status, actions, stop_loss, position_pct, do_not, t_plan, trend_state,
  market_env, data_quality`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_decision_service.py` 末尾追加：

```python
from app.services.decision_service import (  # noqa: E402
    build_decision,
    derive_verdict,
    judge_do_not,
    judge_entry,
    judge_exit,
    judge_loss_plan,
)


def _action_kinds(actions):
    return [a["kind"] for a in actions]


def test_derive_verdict_priority_stop_beats_exit():
    actions = [
        {"kind": "exit", "status": "now"},
        {"kind": "stop", "status": "now"},
    ]
    assert derive_verdict(actions, "loss") == "sell"


def test_derive_verdict_wait_when_nothing_now():
    assert derive_verdict([{"kind": "entry", "status": "armed"}], "empty") == "wait"


def test_derive_verdict_hold_for_position_without_signal():
    assert derive_verdict([], "profit") == "hold"


def test_entry_produces_actions_with_traceable_price():
    closes = [10.0 + (i % 9) * 0.4 for i in range(60)]
    ctx = _ctx(closes, position_status="empty", shares=0)
    actions = judge_entry(ctx)
    ind = ctx.indicators
    known = set()
    for v in (ind.get("ma") or {}).values():
        if v is not None:
            known.add(round(float(v), 3))
    pos = ind.get("position") or {}
    for key in ("p20", "p80", "support_price", "stop_loss_price"):
        if pos.get(key) is not None:
            known.add(round(float(pos[key]), 3))
    st = ind.get("stabilize") or {}
    if st.get("price") is not None:
        known.add(round(float(st["price"]), 3))
    for a in actions:
        if a["price"] is not None:
            assert round(a["price"], 3) in known
        assert a["basis"]           # 每条都要有依据
        assert a["status"] in ("now", "armed", "blocked")


def test_do_not_contains_stop_instruction_when_klines_short():
    from app.services.ta_service import compute_indicators
    klines = _kline([10.0] * 10)
    ctx = DecisionContext(
        stock_code="002185.SZ", stock_name="x",
        indicators=compute_indicators(klines), klines=klines,
        current_price=10.0, prev_close=10.0, cost_basis=None, shares=0,
        position_status="empty", env=MarketContext(),
    )
    assert any("K 线不足" in s for s in judge_do_not(ctx))


def test_build_decision_shape_and_no_llm_fields():
    closes = [10.0 + (i % 11) * 0.3 for i in range(60)]
    d = build_decision(_ctx(closes))
    for key in ("verdict", "headline", "confidence", "role", "actions",
                "stop_loss", "position_pct", "do_not", "t_plan",
                "trend_state", "market_env", "data_quality"):
        assert key in d
    assert d["verdict"] in ("buy", "add", "hold", "reduce", "sell", "wait")
    assert d["role"] in ("建仓参考", "止盈参考", "解套参考")
    assert isinstance(d["actions"], list)
    assert isinstance(d["do_not"], list)


def test_build_decision_role_follows_position_status():
    closes = [10.0 + (i % 11) * 0.3 for i in range(60)]
    d_profit = build_decision(_ctx(closes, position_status="profit", shares=100, cost_basis=9.0))
    d_loss = build_decision(_ctx(closes, position_status="loss", shares=100, cost_basis=20.0))
    assert d_profit["role"] == "止盈参考"
    assert d_loss["role"] == "解套参考"
```

- [ ] **Step 2: 运行测试确认失败**

同任务 1 Step 2 的命令。

Expected: FAIL —— `ImportError: cannot import name 'build_decision'`

- [ ] **Step 3: 实现其余判定器**

在 `backend/app/services/decision_service.py` 末尾追加：

```python
# ============================ 买入(空仓) ============================

def _recent_pressure(ind: dict[str, Any], price: float) -> float | None:
    """最近压力位:低于现价的压力位里最高的一个"""
    pressures = [_f(p) for p in ((ind.get("support_pressure") or {}).get("pressure") or [])]
    below = [p for p in pressures if p is not None and p < price]
    return max(below) if below else None


def judge_entry(ctx: DecisionContext) -> list[dict[str, Any]]:
    """什么时候该买(空仓)→ 三个候选,各自标 now / armed / blocked"""
    ind = ctx.indicators
    ep = effective_price(ctx)
    if ep is None:
        return []
    actions: list[dict[str, Any]] = []

    # C1 支撑企稳
    st = ind.get("stabilize") or {}
    st_price = _f(st.get("price"))
    if bool(st.get("state")) and st_price is not None:
        actions.append({
            "kind": "entry",
            "label": "支撑企稳建仓",
            "condition": f"回踩 {st_price:.2f} 元不破且 MACD 绿柱缩短时,首仓建仓",
            "price": round(st_price, 3),
            "basis": [
                f"企稳价 {st_price:.2f} 元(现价 {(ep / st_price - 1) * 100:+.1f}%)",
                "stabilize.state=true",
            ],
            "status": "now" if ep >= st_price else "armed",
        })

    # C2 超跌反弹
    pos = ind.get("position") or {}
    p20 = _f(pos.get("p20"))
    kdj = ind.get("kdj") or {}
    if pos.get("risk_band") == "low" and kdj.get("zone") == "oversold" and p20 is not None:
        golden = kdj.get("cross") == "golden"
        actions.append({
            "kind": "entry",
            "label": "超跌反弹建仓",
            "condition": f"站回 {p20:.2f} 元(P20 低位带)且 KDJ 出金叉时小仓位试仓",
            "price": round(p20, 3),
            "basis": [
                f"P20 低位带 {p20:.2f} 元",
                f"KDJ {kdj.get('zone')}(K={kdj.get('k')},D={kdj.get('d')})",
            ],
            "status": "now" if golden else "armed",
        })

    # C3 突破确认
    vol_ratio = _f((ind.get("volume") or {}).get("ratio"))
    pressure = _recent_pressure(ind, ep)
    if pressure is not None:
        broke = ep > pressure
        enough = vol_ratio is not None and vol_ratio >= ENTRY_MIN_VOLUME_RATIO
        if not broke:
            status, basis_extra = "armed", [f"尚未突破压力位 {pressure:.2f} 元"]
        elif enough:
            status, basis_extra = "now", [f"量比 {vol_ratio:.2f} ≥ {ENTRY_MIN_VOLUME_RATIO}"]
        else:
            status = "blocked"
            basis_extra = [f"量能仅 {vol_ratio:.2f} 倍,未达 {ENTRY_MIN_VOLUME_RATIO} 倍确认标准"]
        actions.append({
            "kind": "entry",
            "label": "放量突破追进",
            "condition": f"放量站上 {pressure:.2f} 元压力位时追进",
            "price": round(pressure, 3),
            "basis": [f"压力位 {pressure:.2f} 元"] + basis_extra,
            "status": status,
        })
    return actions


# ============================ 卖出(浮盈) ============================

def judge_exit(ctx: DecisionContext) -> list[dict[str, Any]]:
    """什么时候该卖(浮盈)"""
    ind = ctx.indicators
    ep = effective_price(ctx)
    if ep is None:
        return []
    pos = ind.get("position") or {}
    ma = ind.get("ma") or {}
    boll = ind.get("boll") or {}
    kdj = ind.get("kdj") or {}
    vp = (ind.get("volume_price") or {}).get("direction")
    channel = (ind.get("channel") or {}).get("state")
    ma5, ma10, ma20, ma60 = (_f(ma.get(k)) for k in ("ma5", "ma10", "ma20", "ma60"))
    bull_ma = all(v is not None for v in (ma5, ma10, ma20, ma60)) and ma5 > ma10 > ma20 > ma60

    actions: list[dict[str, Any]] = []
    p80 = _f(pos.get("p80"))
    if p80 is not None:
        actions.append({
            "kind": "exit",
            "label": "分批止盈",
            "condition": f"涨到 {p80:.2f} 元(P80 分位)先减仓 1/3",
            "price": round(p80, 3),
            "basis": [f"P80 分位 {p80:.2f} 元"],
            "status": "now" if ep >= p80 else "armed",
        })

    if boll.get("position") in ("touching_upper", "above_upper") and kdj.get("zone") == "overbought":
        actions.append({
            "kind": "exit",
            "label": "高位滞涨再减",
            "condition": "布林触上轨且 KDJ 超买,再减仓 1/3",
            "price": round(ep, 3),
            "basis": [f"布林位置 {boll.get('position')}", f"KDJ {kdj.get('zone')}"],
            "status": "now",
        })

    if ma5 is not None:
        actions.append({
            "kind": "exit",
            "label": "移动止盈",
            "condition": f"跌破 MA5 {ma5:.2f} 元清掉剩余仓位",
            "price": round(ma5, 3),
            "basis": [f"MA5 {ma5:.2f} 元"],
            "status": "armed",
        })

    if channel == "up" and vp == "healthy_up" and bull_ma:
        actions.append({
            "kind": "watch",
            "label": "让利润跑",
            "condition": "放量价升且均线多头,持股不动等突破,不急卖",
            "price": None,
            "basis": [f"通道 {channel}", f"量价 {vp}", "均线多头排列"],
            "status": "now",
        })

    stop = _f(pos.get("stop_loss_price"))
    if stop is not None and ep < stop:
        actions.append({
            "kind": "stop",
            "label": "止损",
            "condition": f"跌破 {stop:.2f} 元无条件减仓",
            "price": round(stop, 3),
            "basis": [f"建议止损 {stop:.2f} 元"],
            "status": "now",
        })
    return actions


# ============================ 亏损处理 ============================

def judge_loss_plan(ctx: DecisionContext) -> list[dict[str, Any]]:
    """亏损了怎么办"""
    ind = ctx.indicators
    ep = effective_price(ctx)
    if ep is None:
        return []
    pos = ind.get("position") or {}
    channel = (ind.get("channel") or {}).get("state")
    st = ind.get("stabilize") or {}
    actions: list[dict[str, Any]] = []

    stop = _f(pos.get("stop_loss_price"))
    if stop is not None and ep < stop:
        actions.append({
            "kind": "stop",
            "label": "无条件止损",
            "condition": f"已跌破 {stop:.2f} 元,无条件止损,不要等回本",
            "price": round(stop, 3),
            "basis": [f"建议止损 {stop:.2f} 元(参考支撑 × 0.97)"],
            "status": "now",
        })

    support = _f(pos.get("support_price"))
    vp = (ind.get("volume_price") or {}).get("direction")
    if support is not None and ep < support and vp == "panic_sell":
        actions.append({
            "kind": "exit",
            "label": "破位减仓",
            "condition": f"跌破 {support:.2f} 元且量增价跌(主力出货),减仓而不是补仓",
            "price": round(support, 3),
            "basis": [f"参考支撑 {support:.2f} 元", f"量价 {vp}"],
            "status": "now",
        })

    # L4 补仓摊薄
    market_state = (ctx.env.market or {}).get("state")
    reasons: list[str] = []
    if channel == "down":
        reasons.append("下跌通道(趋势未破条件不成立)")
    if not bool(st.get("state")):
        reasons.append("尚无企稳信号")
    if market_state == "cold":
        reasons.append("大盘偏冷")
    shares = ctx.shares
    cost = _f(ctx.cost_basis)
    if shares > 0 and cost is not None and cost > 0:
        add_shares = round(shares * ADD_SHARE_RATIO)
        if add_shares > 0:
            new_cost = (shares * cost + add_shares * ep) / (shares + add_shares)
            actions.append({
                "kind": "add",
                "label": "补仓摊薄",
                "condition": (
                    f"趋势未破且企稳,可补 {add_shares} 股摊薄成本到 {new_cost:.2f} 元"
                    if not reasons
                    else f"暂不补仓({';'.join(reasons)})"
                ),
                "price": round(ep, 3),
                "basis": [
                    f"持仓 {shares} 股 @ 成本 {cost:.2f} 元",
                    f"补 {add_shares} 股后均价 {new_cost:.2f} 元",
                ],
                "status": "now" if not reasons else "blocked",
            })
    return actions


# ============================ 别动清单 ============================

def judge_do_not(ctx: DecisionContext) -> list[str]:
    """什么情况别动"""
    ind = ctx.indicators
    out: list[str] = []
    ep = effective_price(ctx)

    if (ind.get("liar") or {}).get("bull_liars"):
        out.append("出现诱多信号时不要加仓")

    prev = _f(ctx.prev_close)
    if ep is not None and prev is not None and prev > 0:
        chg = (ep - prev) / prev * 100
        if chg >= NEAR_LIMIT_UP_PCT:
            out.append("涨停或接近涨停时不要追高")

    m = ctx.env.market or {}
    up_total = m.get("up_total")
    down_total = m.get("down_total")
    if isinstance(up_total, int) and isinstance(down_total, int) and up_total > 0:
        if down_total > up_total * MARKET_COLD_RATIO:
            out.append(f"大盘普跌(跌 {down_total} 家多于涨 {up_total} 家 1.5 倍)时不要加仓")

    kline_count = (ind.get("data_quality") or {}).get("kline_count") or 0
    if kline_count < MIN_KLINES_FOR_SIGNAL:
        out.append(f"K 线不足 {MIN_KLINES_FOR_SIGNAL} 根,指标不可靠,先别动手")

    if (ind.get("channel") or {}).get("state") == "down":
        out.append("下跌通道中不要抄底")

    last_vol = ctx.klines[-1].get("volume") if ctx.klines else None
    if not last_vol or int(last_vol) <= 0:
        out.append("今日无成交,无法判断")

    return out


# ============================ 结论组装 ============================

_VERDICT_BY_KIND = {"stop": "sell", "exit": "reduce", "entry": "buy", "add": "add"}


def derive_verdict(actions: list[dict[str, Any]], position_status: str) -> str:
    """actions → 单一结论"""
    now_kinds = {a["kind"] for a in actions if a.get("status") == "now"}
    for kind in ("stop", "exit", "entry", "add"):
        if kind in now_kinds:
            return _VERDICT_BY_KIND[kind]
    if position_status in ("profit", "loss"):
        return "hold"
    return "wait"


def _headline(
    ctx: DecisionContext,
    verdict: str,
    actions: list[dict[str, Any]],
    position_status: str,
) -> str:
    """一句话结论(白话,带具体数字)"""
    ep = effective_price(ctx)
    price_txt = f"现价 {ep:.2f} 元" if ep is not None else "现价未知"
    now = [a for a in actions if a.get("status") == "now"]
    armed = [a for a in actions if a.get("status") == "armed"]

    if verdict == "sell" and now:
        return f"{price_txt},{now[0]['label']}:{now[0]['condition']}"
    if verdict == "reduce" and now:
        return f"{price_txt},{now[0]['label']}:{now[0]['condition']}"
    if verdict == "buy" and now:
        return f"{price_txt},{now[0]['label']}:{now[0]['condition']}"
    if verdict == "add" and now:
        return f"{price_txt},{now[0]['label']}:{now[0]['condition']}"
    if armed:
        return f"{price_txt},等触发:{armed[0]['condition']}"
    if position_status == "profit":
        return f"{price_txt},暂无止盈触发条件,持股观察"
    if position_status == "loss":
        return f"{price_txt},等解套信号,未到止损位"
    return f"{price_txt},暂不满足建仓条件,继续观察"


def build_decision(ctx: DecisionContext) -> dict[str, Any]:
    """组装完整决策(纯函数)"""
    ind = ctx.indicators
    ep = effective_price(ctx)
    degraded: list[str] = list(ctx.env.degraded or [])
    if ctx.current_price is None and ep is not None:
        degraded.append(f"实时价不可用,按最新收盘价 {ep} 计算")

    trend = judge_trend(ctx)
    t_plan = judge_t_plan(ctx)

    if ctx.position_status == "empty":
        actions = judge_entry(ctx)
    elif ctx.position_status == "profit":
        actions = judge_exit(ctx)
    else:
        actions = judge_loss_plan(ctx)

    verdict = derive_verdict(actions, ctx.position_status)
    role = {"empty": "建仓参考", "profit": "止盈参考", "loss": "解套参考"}[ctx.position_status]

    # 仓位建议
    pos = ind.get("position") or {}
    signal = ind.get("signal") or {}
    score = _f(signal.get("score"))
    base = 20
    if score is not None:
        for upper, pct in POSITION_TIERS:
            if score < upper:
                base = pct
                break
    if pos.get("risk_band") == "low":
        base = min(base + 10, 30)
    ma20 = _f((ind.get("ma") or {}).get("ma20"))
    add_to = min(base * 2, POSITION_ADD_CAP)
    if ctx.position_status == "empty":
        position_pct = f"首仓 {base}%"
        if ma20 is not None:
            position_pct += f",站稳 MA20 {ma20:.2f} 元后加至 {add_to}%"
    elif ctx.position_status == "profit":
        position_pct = f"分批止盈,每次减 1/3,保留底仓 ≥50%"
    else:
        position_pct = f"解套优先,减仓不追补;确需补仓时单次不超过 {add_to}%"

    # 止损
    stop_loss = None
    stop_price = _f(pos.get("stop_loss_price"))
    support = _f(pos.get("support_price"))
    if stop_price is not None:
        stop_loss = {
            "price": round(stop_price, 3),
            "basis": (
                f"参考支撑 {support:.2f} 元 × 0.97" if support is not None else "参考支撑 × 0.97"
            ),
        }

    # 置信度
    conf = signal.get("confidence") or "medium"
    if degraded and conf == "high":
        conf = "medium"

    market_env = {
        "market": ctx.env.market or {},
        "sector": ctx.env.sector or {},
        "stock_flow": ctx.env.stock_flow or {},
        "relative": ctx.env.relative or {},
        "degraded": list(ctx.env.degraded or []),
    }

    return {
        "stock_code": ctx.stock_code,
        "stock_name": ctx.stock_name,
        "verdict": verdict,
        "headline": _headline(ctx, verdict, actions, ctx.position_status),
        "confidence": conf,
        "role": role,
        "position_status": ctx.position_status,
        "actions": actions,
        "stop_loss": stop_loss,
        "position_pct": position_pct,
        "do_not": judge_do_not(ctx),
        "t_plan": t_plan,
        "trend_state": trend,
        "market_env": market_env,
        "data_quality": {"degraded": degraded},
    }
```

- [ ] **Step 4: 运行测试确认通过**

同任务 1 Step 2 的命令。

Expected: PASS —— `14 passed`

- [ ] **Step 5: 跑全量后端测试确认零回归**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest -q --no-header -p no:cacheprovider
```

Expected: 全绿（基线 1033 passed；新增用例后应为 1040+ passed, 0 failed）

- [ ] **Step 6: 提交**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/services/decision_service.py backend/tests/test_decision_service.py
git commit -m "feat(decision): 买/卖/亏损/别动判定 + verdict 组装 + build_decision"
```

---

## 任务 3：市场环境聚合

**Files:**
- Create: `backend/app/services/market_context_service.py`
- Create: `backend/tests/test_market_context_service.py`

**Interfaces:**
- Consumes:
  - `app.services.industry_service.resolve_industry(code) -> dict`（返回 `{code, industry, source, note}`；`industry` 为 **证监会口径**名，一级命中时来自离线表）
  - `app.services.sector_kline_service.get_sector_kline(industry, period="daily", count=N) -> dict`（`items` **只有 date / close**）
  - `app.services.sector_fund_flow_service.get_sector_fund_flow(fenlei=1, num=40, sort="netamount") -> list[dict]`（**新浪口径**板块名；每项含 `name` / `netamount_yi` / `change_pct` / `top_stock`）
  - `app.services.market_overview_service.fetch_market_sentiment() -> dict`
  - `app.services.market_overview_service.get_market_overview() -> dict`（取 `indexes[].change_pct` 作大盘涨跌幅）
  - `app.services.fund_flow_service.list_recent(stock_code, limit=1) -> list[FundFlow]`
- Produces:
  ```python
  async def get_market_context(stock_code: str, stock_change_pct: float | None = None) -> MarketContext
  ```

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_market_context_service.py`：

```python
"""市场环境聚合单测(全部数据源 mock,验证降级不崩、不编数字)"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.decision_service import MarketContext
from app.services.market_context_service import get_market_context


def _sentiment(up=3777, down=1667, flat=124, lu=59, ld=10):
    return {
        "up_total": up, "down_total": down, "flat_total": flat,
        "limit_up": lu, "limit_down": ld, "sample_size": 5568,
        "amount_yi": 14711.94, "partial": False,
    }


def _overview(chg=0.12):
    return {"indexes": [{"code": "000001.SH", "name": "上证指数",
                         "close": 3735.37, "change_pct": chg}]}


def _patched(sentiment=None, overview=None, industry=None, flows=None, stock_flows=None):
    """统一 patch 全部 5 个数据源(不 patch 会真联网,测试会变慢且不稳定)"""
    return (
        patch("app.services.market_context_service.fetch_market_sentiment",
              AsyncMock(return_value=sentiment if sentiment is not None else _sentiment())),
        patch("app.services.market_context_service.get_market_overview",
              AsyncMock(return_value=overview if overview is not None else _overview())),
        patch("app.services.market_context_service.resolve_industry",
              AsyncMock(return_value=industry if industry is not None
                        else {"code": "002185.SZ", "industry": "C39计算机、通信和其他电子设备制造业",
                              "source": "baostock", "note": None})),
        patch("app.services.market_context_service.get_sector_fund_flow",
              AsyncMock(return_value=flows if flows is not None else [])),
        patch("app.services.market_context_service.list_recent",
              AsyncMock(return_value=stock_flows if stock_flows is not None else [])),
    )


@pytest.mark.asyncio
async def test_market_warm_when_up_dominates():
    p = _patched()
    with p[0], p[1], p[2], p[3], p[4]:
        ctx = await get_market_context("002185.SZ")
    assert ctx.market["state"] == "warm"
    assert ctx.market["up_total"] == 3777
    assert ctx.market["change_pct"] == 0.12


@pytest.mark.asyncio
async def test_all_sources_failing_does_not_raise():
    with patch("app.services.market_context_service.fetch_market_sentiment",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.market_context_service.get_market_overview",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.market_context_service.resolve_industry",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.market_context_service.get_sector_fund_flow",
               AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.services.market_context_service.list_recent",
               AsyncMock(side_effect=RuntimeError("boom"))):
        ctx = await get_market_context("002185.SZ")
    assert ctx.market["state"] is None
    assert ctx.market["change_pct"] is None
    assert ctx.sector["industry"] is None
    assert ctx.stock_flow["direction"] is None
    assert len(ctx.degraded) >= 3


@pytest.mark.asyncio
async def test_missing_fields_are_none_not_zero():
    p = _patched(sentiment={"up_total": 100, "down_total": 90})
    with p[0], p[1], p[2], p[3], p[4]:
        ctx = await get_market_context("002185.SZ")
    assert ctx.market.get("limit_up") is None
    assert ctx.market.get("limit_down") is None


@pytest.mark.asyncio
async def test_leading_sectors_available_even_when_name_mismatch():
    """证监会行业名匹配不上新浪板块名时,仍应给出「资金主攻板块」"""
    flows = [
        {"name": "电子元件", "netamount_yi": 12.3, "change_pct": 2.1},
        {"name": "半导体", "netamount_yi": 8.1, "change_pct": 1.4},
        {"name": "银行", "netamount_yi": -3.2, "change_pct": -0.5},
    ]
    p = _patched(flows=flows)
    with p[0], p[1], p[2], p[3], p[4]:
        ctx = await get_market_context("002185.SZ")
    assert ctx.sector["fund_net_yi"] is None          # 口径不匹配 → 不编数字
    assert len(ctx.sector["leading"]) == 2              # 只取净流入为正的 Top N
    assert ctx.sector["leading"][0]["name"] == "电子元件"
    assert ctx.sector["leading"][0]["net_yi"] == 12.3
    assert any("口径" in d for d in ctx.degraded)
```

- [ ] **Step 2: 运行测试确认失败**

同任务 1 Step 2 的命令（改 `tests/test_market_context_service.py`）。

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.market_context_service'`

- [ ] **Step 3: 实现 market_context_service.py**

创建 `backend/app/services/market_context_service.py`：

```python
"""市场环境聚合(大盘温度 / 行业强弱 + 资金 / 本股资金 / 相对强弱)

只读项目既有服务,**不新增任何抓取逻辑**;任一子项失败只降级该项,
对应字段置 None 并写入 degraded —— 绝不编数字。

⚠️ 两套行业命名口径(**必须分清,否则匹配永远失败**):
- **证监会行业名**(离线表 baostock,形如 "C39计算机、通信和其他电子设备制造业")
  → 用于 `get_sector_kline()`(行业等权 K 线),与 `overview_service.fetch_sector` 同源
- **新浪行业板块名**(形如 "电子元件")
  → 用于 `get_sector_fund_flow()`(板块资金流排行)
两套名字互不相通。`resolve_industry()` 优先返回证监会口径(离线表命中时),
因此**用它的返回值去匹配板块资金流通常会落空** —— 落空就如实降级,
同时用「今日资金主攻板块」补充市场主线信息(该口径恒可用)。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.decision_service import MarketContext
from app.services.fund_flow_service import list_recent
from app.services.industry_service import resolve_industry
from app.services.market_overview_service import fetch_market_sentiment, get_market_overview
from app.services.sector_fund_flow_service import get_sector_fund_flow
from app.services.sector_kline_service import get_sector_kline

logger = logging.getLogger(__name__)

MARKET_WARM_RATIO = 1.5   # 涨家数 > 跌家数 × 该系数 → 偏暖
MARKET_COLD_RATIO = 1.5   # 跌家数 > 涨家数 × 该系数 → 偏冷
LEADING_SECTOR_TOP_N = 3  # 今日资金主攻板块展示条数


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


async def _safe(coro_factory, label: str, degraded: list[str]):
    """跑一个 IO 调用;失败返回 None 并记录降级原因"""
    try:
        return await coro_factory()
    except Exception as e:  # noqa: BLE001
        logger.warning("市场环境 %s 取数失败: %s", label, e)
        degraded.append(f"{label} 不可用")
        return None


async def get_market_context(
    stock_code: str, stock_change_pct: float | None = None
) -> MarketContext:
    """聚合某只票的市场环境

    stock_change_pct: 该股当日涨跌幅(%),用于算相对强弱;None → 相对强弱为 None。
    """
    degraded: list[str] = []

    sentiment, overview, industry, flows, stock_flows = await asyncio.gather(
        _safe(lambda: fetch_market_sentiment(), "大盘情绪", degraded),
        _safe(lambda: get_market_overview(), "大盘指数", degraded),
        _safe(lambda: resolve_industry(stock_code), "行业归属", degraded),
        _safe(lambda: get_sector_fund_flow(fenlei=1, num=40, sort="netamount"),
              "板块资金流", degraded),
        _safe(lambda: list_recent(stock_code, limit=1), "本股资金流", degraded),
    )

    # ---- 大盘 ----
    market: dict[str, Any] = {
        "state": None, "up_total": None, "down_total": None, "flat_total": None,
        "limit_up": None, "limit_down": None, "sample_size": None,
        "change_pct": None, "summary": "大盘数据暂不可用",
    }
    if isinstance(sentiment, dict):
        up = sentiment.get("up_total")
        down = sentiment.get("down_total")
        market.update({
            "up_total": up, "down_total": down,
            "flat_total": sentiment.get("flat_total"),
            "limit_up": sentiment.get("limit_up"),
            "limit_down": sentiment.get("limit_down"),
            "sample_size": sentiment.get("sample_size"),
        })
        if isinstance(up, int) and isinstance(down, int) and up + down > 0:
            if up > down * MARKET_WARM_RATIO:
                market["state"] = "warm"
            elif down > up * MARKET_COLD_RATIO:
                market["state"] = "cold"
            else:
                market["state"] = "neutral"
            tone = {"warm": "偏暖", "cold": "偏冷", "neutral": "分化"}[market["state"]]
            market["summary"] = (
                f"大盘{tone}:涨 {up} / 跌 {down},"
                f"涨停 {market['limit_up']} / 跌停 {market['limit_down']}"
            )
    # 大盘涨跌幅:取上证指数真实涨跌幅(不用涨跌家数近似)
    market_chg = _index_change_pct(overview)
    if market_chg is not None:
        market["change_pct"] = market_chg

    # ---- 行业 ----
    industry_name = None
    if isinstance(industry, dict):
        industry_name = industry.get("industry")
    sector: dict[str, Any] = {
        "industry": industry_name, "change_pct": None, "vs_market_pct": None,
        "fund_net_yi": None, "fund_direction": None, "state": None,
        "leading": [], "summary": "行业归属未知" if industry_name is None else "",
    }

    # 行业等权 K 线(证监会口径,与 resolve_industry 一级结果同源)
    if industry_name:
        kline = await _safe(
            lambda: get_sector_kline(industry_name, period="daily", count=60),
            "行业K线", degraded,
        )
        chg = _sector_change_pct(kline)
        if chg is not None:
            sector["change_pct"] = chg
            if chg > 1:
                sector["state"] = "leading"
            elif chg > 0:
                sector["state"] = "warm"
            elif chg > -1:
                sector["state"] = "lagging"
            else:
                sector["state"] = "cold"

    # 板块资金流(新浪口径):只有行业名恰好是新浪板块名时才命中,否则如实降级
    if isinstance(flows, list) and flows:
        # 今日资金主攻板块(该口径恒可用,回答「今天钱在往哪走」)
        ranked = sorted(
            (f for f in flows if _f(f.get("netamount_yi")) is not None),
            key=lambda f: f["netamount_yi"],
            reverse=True,
        )[:LEADING_SECTOR_TOP_N]
        sector["leading"] = [
            {"name": f.get("name"), "net_yi": round(float(f["netamount_yi"]), 2)}
            for f in ranked
        ]
        if industry_name:
            for it in flows:
                if it.get("name") == industry_name:
                    net = _f(it.get("netamount_yi"))
                    if net is not None:
                        sector["fund_net_yi"] = net
                        sector["fund_direction"] = (
                            "in" if net > 0 else ("out" if net < 0 else None)
                        )
                    break
            else:
                degraded.append("板块资金流无该行业(行业名为证监会口径,与新浪板块名不同)")
    elif industry_name:
        degraded.append("板块资金流不可用")

    if sector["state"] and sector["fund_direction"] == "out":
        sector["state"] = {
            "leading": "warm", "warm": "lagging", "lagging": "cold", "cold": "cold",
        }[sector["state"]]

    parts: list[str] = []
    if industry_name:
        parts.append(f"所属 {industry_name}")
    if sector["change_pct"] is not None:
        parts.append(f"今日 {sector['change_pct']:+.2f}%")
    if sector["fund_net_yi"] is not None:
        parts.append(f"板块主力净流入 {sector['fund_net_yi']:+.2f} 亿")
    if sector["leading"]:
        top = "、".join(
            f"{s['name']} {s['net_yi']:+.1f}亿" for s in sector["leading"]
        )
        parts.append(f"资金主攻 {top}")
    sector["summary"] = " · ".join(parts) if parts else "行业数据暂不可用"

    # ---- 本股资金流 ----
    stock_flow: dict[str, Any] = {
        "direction": None, "amount_wan": None, "category": None, "summary": "暂无资金流数据",
    }
    if isinstance(stock_flows, list) and stock_flows:
        ff = stock_flows[0]
        amt = _f(getattr(ff, "amount", None))
        direction = getattr(ff, "direction", None)
        if direction in ("in", "out"):
            stock_flow["direction"] = direction
            stock_flow["amount_wan"] = amt
            stock_flow["category"] = getattr(ff, "category", None)
            verb = "净流入" if direction == "in" else "净流出"
            stock_flow["summary"] = (
                f"本股今日主力{verb} {amt:.2f} 万"
                if amt is not None else f"本股今日主力{verb}"
            )

    # ---- 相对强弱 ----
    relative: dict[str, Any] = {
        "vs_sector_pct": None, "vs_market_pct": None, "summary": "相对强弱暂无数据",
    }
    if stock_change_pct is not None:
        if sector["change_pct"] is not None:
            relative["vs_sector_pct"] = round(stock_change_pct - sector["change_pct"], 2)
        if market_chg is not None:
            relative["vs_market_pct"] = round(stock_change_pct - market_chg, 2)
        bits = []
        if relative["vs_sector_pct"] is not None:
            bits.append(f"强于行业 {relative['vs_sector_pct']:+.2f}%")
        if relative["vs_market_pct"] is not None:
            bits.append(f"强于大盘 {relative['vs_market_pct']:+.2f}%")
        if bits:
            relative["summary"] = f"本股 {stock_change_pct:+.2f}% · " + " · ".join(bits)

    return MarketContext(
        market=market,
        sector=sector,
        stock_flow=stock_flow,
        relative=relative,
        degraded=degraded,
    )


def _sector_change_pct(kline: Any) -> float | None:
    """行业等权 K 线近 1 日涨幅 %

    ⚠️ `get_sector_kline()` 返回的 items **只有 date / close**(等权合成收盘价),
    没有 open/high/low —— 所以只能算收盘对收盘的涨幅。
    """
    if not isinstance(kline, dict):
        return None
    items = kline.get("items") or []
    if len(items) < 2:
        return None
    try:
        prev = float(items[-2]["close"])
        cur = float(items[-1]["close"])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if prev <= 0:
        return None
    return round((cur - prev) / prev * 100, 2)


def _index_change_pct(overview: Any) -> float | None:
    """大盘涨跌幅 %:取上证指数真实涨跌幅(不用涨跌家数近似)

    `get_market_overview()` → {"indexes": [{"code","name","close","change_pct",...}], ...}
    取第一个 change_pct 非空的指数。
    """
    if not isinstance(overview, dict):
        return None
    for idx in overview.get("indexes") or []:
        if not isinstance(idx, dict):
            continue
        chg = _f(idx.get("change_pct"))
        if chg is not None:
            return round(chg, 2)
    return None
```

- [ ] **Step 4: 运行测试确认通过**

同任务 1 Step 2 的命令（改 `tests/test_market_context_service.py`）。

Expected: PASS —— `4 passed`

- [ ] **Step 5: 提交**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/services/market_context_service.py backend/tests/test_market_context_service.py
git commit -m "feat(decision): 市场环境聚合(大盘/行业/资金/相对强弱),全链路降级"
```

---

## 任务 4：API 端点

**Files:**
- Modify: `backend/app/api/stock.py`（在 `@router.get("/{code}/analysis")` **之前**插入新端点）
- Create: `backend/tests/test_decision_api.py`

**Interfaces:**
- Consumes: 任务 2 的 `build_decision` / `DecisionContext`；任务 3 的 `get_market_context`
- Produces: `GET /api/stock/{code}/decision` → `{"decision": {...}}`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_decision_api.py`：

```python
"""决策端点契约测试"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_invalid_code_returns_422():
    r = client.get("/api/stock/123/decision")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INVALID_STOCK_CODE"


@pytest.mark.asyncio
async def test_decision_endpoint_returns_shape():
    klines = [{
        "date": f"2026-01-{i + 1:02d}", "open": 10.0, "high": 10.5,
        "low": 9.8, "close": 10.2, "volume": 10000,
    } for i in range(60)]

    with patch(
        "app.api.stock.fetch_klines", AsyncMock(return_value=klines)
    ), patch(
        "app.api.stock.QuoteService.get_quotes",
        AsyncMock(return_value=[]),
    ), patch(
        "app.api.stock.get_position", AsyncMock(return_value=None)
    ), patch(
        "app.api.stock.get_market_context", AsyncMock(return_value=None)
    ):
        r = client.get("/api/stock/002185.SZ/decision")
    assert r.status_code == 200
    body = r.json()
    assert "decision" in body
    d = body["decision"]
    for key in ("verdict", "headline", "actions", "role", "trend_state",
                "t_plan", "do_not", "data_quality"):
        assert key in d
```

> ⚠️ 实现时若 `get_market_context` 的 patch 路径不生效，改用 patch `app.services.market_context_service.get_market_context`；
> 或直接在端点里 `from app.services.market_context_service import get_market_context`（模块级 import，便于 patch）。

- [ ] **Step 2: 运行测试确认失败**

同任务 1 Step 2 的命令（改 `tests/test_decision_api.py`）。

Expected: FAIL —— 404 / `KeyError: 'decision'`

- [ ] **Step 3: 实现端点**

在 `backend/app/api/stock.py` 的 `@router.get("/{code}/analysis")` **之前**插入：

```python
@router.get("/{code}/decision")
async def decision(code: str) -> dict:
    """确定性决策卡(零 LLM):现在该做什么 + 价位 + 触发条件 + 止损 + 别动清单

    与 /analysis 的分工:
    - /decision  **纯算法**,秒出、无费用、无 LLM 依赖,回答「该买/该卖/做T/走势/市场情况」
    - /analysis  LLM 白话解读(可选),是 /decision 的解释层

    任何一个数据源失败都只降级对应项(字段为 null + data_quality.degraded),
    只有 K 线完全不可用才返回 502。
    """
    await _check_code(code)
    klines, quote = await asyncio.gather(
        _load_klines(code),
        _load_quote(code),
    )
    current_price, _ = _sanitize_current_price(quote, klines)
    position = await get_position(code)
    position_status, _ = _resolve_position_status(position, current_price)

    from app.services.decision_service import DecisionContext, build_decision
    from app.services.market_context_service import get_market_context

    indicators = compute_indicators(klines)
    prev_close = None
    if quote is not None:
        try:
            prev_close = float(quote.prev_close) if quote.prev_close is not None else None
        except (TypeError, ValueError):
            prev_close = None
    if prev_close is None and len(klines) >= 2:
        try:
            prev_close = float(klines[-2]["close"])
        except (TypeError, ValueError):
            prev_close = None

    change_pct = None
    if quote is not None and quote.change_pct is not None:
        try:
            change_pct = float(quote.change_pct)
        except (TypeError, ValueError):
            change_pct = None

    env = await get_market_context(code, stock_change_pct=change_pct)

    ctx = DecisionContext(
        stock_code=code,
        stock_name=getattr(position, "stock_name", None) if position is not None else None,
        indicators=indicators,
        klines=klines,
        current_price=float(current_price) if current_price is not None else None,
        prev_close=prev_close,
        cost_basis=(
            float(position.avg_cost)
            if position is not None and position.avg_cost is not None else None
        ),
        shares=int(position.shares) if position is not None and position.shares else 0,
        position_status=position_status,
        env=env,
    )
    return {"decision": build_decision(ctx)}
```

同时在 `backend/app/api/stock.py` 顶部 import 区补：

```python
from app.services.ta_service import compute_indicators
from app.services.market_context_service import get_market_context
```

> 注意：`compute_indicators` 在 K 线为空时会抛 `TaError`。`_load_klines` 已经保证非空或抛 502，
> 但为稳妥，包一层：

```python
    try:
        indicators = compute_indicators(klines)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"code": "DATA_SOURCE_UNAVAILABLE", "message": f"K 线指标计算失败: {e}"},
        ) from e
```

- [ ] **Step 4: 运行测试确认通过**

同任务 1 Step 2 的命令（改 `tests/test_decision_api.py`）。

Expected: PASS

- [ ] **Step 5: 用真实服务验一次端点**

```powershell
Set-Location 'D:\zga-study\rich'
cmd /c "scripts\dev.cmd" -Action restart
Start-Sleep -Seconds 12
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/stock/002185.SZ/decision' -TimeoutSec 40 |
  ConvertTo-Json -Depth 6
```

Expected: 200，`decision.verdict` / `actions` / `t_plan` / `trend_state` / `market_env` 均有内容且数字真实。

- [ ] **Step 6: 提交**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/api/stock.py backend/tests/test_decision_api.py
git commit -m "feat(api): GET /api/stock/{code}/decision 确定性决策端点"
```

---

## 任务 5：回测闸门

**Files:**
- Create: `backend/app/services/decision_backtest.py`
- Create: `backend/tests/test_decision_backtest.py`
- Create: `docs/analysis/decision-backtest-report.md`

**Interfaces:**
- Consumes: `decision_service.build_decision` / `DecisionContext`；`app.services.kline_service.fetch_klines`
- Produces:
  ```python
  async def run_backtest(codes: list[str], days: int = 120) -> dict
      # -> {"samples": int, "codes": int, "days": int,
      #     "entry": {...}, "exit": {...}, "stop": {...}, "passed": bool, "gates": [...]}
  def evaluate_gates(report: dict) -> tuple[bool, list[dict]]
  ```

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_decision_backtest.py`：

```python
"""回测闸门脚本自身正确性(小样本 sanity)"""
from app.services.decision_backtest import evaluate_gates


def test_evaluate_gates_fails_when_samples_insufficient():
    report = {
        "samples": 3, "codes": 1, "days": 10,
        "entry": {"win_rate": 0.9, "avg_return": 0.2, "baseline_avg_return": 0.01},
        "exit": {"avg_drawdown": -0.02, "baseline_avg_drawdown": -0.05},
        "stop": {"avg_drawdown": -0.01, "baseline_avg_drawdown": -0.05},
    }
    ok, gates = evaluate_gates(report)
    assert ok is False
    assert any(g["name"] == "样本量" and not g["passed"] for g in gates)


def test_evaluate_gates_passes_when_all_gates_met():
    report = {
        "samples": 5000, "codes": 40, "days": 120,
        "entry": {"win_rate": 0.56, "avg_return": 0.031, "baseline_avg_return": 0.011},
        "exit": {"avg_drawdown": -0.04, "baseline_avg_drawdown": -0.06},
        "stop": {"avg_drawdown": -0.02, "baseline_avg_drawdown": -0.04},
    }
    ok, gates = evaluate_gates(report)
    assert ok is True
    assert all(g["passed"] for g in gates)
```

- [ ] **Step 2: 运行测试确认失败**

同任务 1 Step 2 的命令（改 `tests/test_decision_backtest.py`）。

Expected: FAIL —— `ModuleNotFoundError: No module named 'app.services.decision_backtest'`

- [ ] **Step 3: 实现回测脚本**

创建 `backend/app/services/decision_backtest.py`：

```python
"""决策规则回测闸门

用历史 K 线逐日跑决策器,统计决策信号的实际效果,与「买入并持有」基准对比。
**门槛先定、事后不得下调** —— 不达标就改规则,不得跳过闸门上线。

口径(与设计文档 §10.1.1 一致):
- 买入价 = 信号日**次日**开盘价(信号在收盘后产生)
- 持有期 = 买入日起 10 个交易日
- 胜 = 持有期内最高收盘价 > 买入价 × 1.02
- 平均收益 = 第 10 个交易日收盘价 / 买入价 - 1
- 最大回撤 = 持有期内最低收盘价 / 买入价 - 1
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.decision_service import DecisionContext, MarketContext, build_decision
from app.services.ta_service import compute_indicators

logger = logging.getLogger(__name__)

HOLD_DAYS = 10
WIN_THRESHOLD = 0.02
MIN_SAMPLES = 30 * 120        # ≥30 只 × 120 交易日
MIN_WIN_RATE = 0.53
MIN_EXCESS_RETURN = 0.01
MIN_EXIT_DD_IMPROVE = 0.01
MIN_STOP_DD_IMPROVE = 0.015


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _forward_return(klines: list[dict], idx: int) -> tuple[float | None, float | None, float | None]:
    """信号日 idx 的次日开盘买入 → (胜?, 平均收益, 最大回撤)

    返回 (is_win, ret, max_dd);数据不足返回 (None, None, None)。
    """
    entry_idx = idx + 1
    if entry_idx >= len(klines):
        return None, None, None
    entry = _f(klines[entry_idx].get("open"))
    if entry is None or entry <= 0:
        return None, None, None
    hold = klines[entry_idx: entry_idx + HOLD_DAYS]
    if len(hold) < HOLD_DAYS:
        return None, None, None
    closes = [_f(k.get("close")) for k in hold]
    if any(c is None for c in closes):
        return None, None, None
    max_close = max(closes)
    min_close = min(closes)
    last_close = closes[-1]
    is_win = 1.0 if max_close > entry * (1 + WIN_THRESHOLD) else 0.0
    ret = last_close / entry - 1
    dd = min_close / entry - 1
    return is_win, ret, dd


def _baseline(klines: list[dict], idx: int) -> tuple[float | None, float | None]:
    """基准:同一天买入并持有 HOLD_DAYS 日 → (收益, 最大回撤)"""
    _, ret, dd = _forward_return(klines, idx)
    return ret, dd


def evaluate_gates(report: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """按设计文档 §10.2 的门槛判定;返回 (是否通过, 每条门槛明细)"""
    gates: list[dict[str, Any]] = []

    samples = report.get("samples", 0)
    gates.append({
        "name": "样本量",
        "target": f"≥ {MIN_SAMPLES} 条信号样本",
        "actual": samples,
        "passed": samples >= MIN_SAMPLES,
    })

    entry = report.get("entry") or {}
    wr = entry.get("win_rate")
    gates.append({
        "name": "entry 后 10 日胜率",
        "target": f"≥ {MIN_WIN_RATE:.0%}",
        "actual": wr,
        "passed": wr is not None and wr >= MIN_WIN_RATE,
    })
    exc = _f(entry.get("avg_return"))
    base = _f(entry.get("baseline_avg_return"))
    gates.append({
        "name": "entry 超额收益",
        "target": f"> 基准 + {MIN_EXCESS_RETURN:.1%}",
        "actual": None if exc is None or base is None else round(exc - base, 4),
        "passed": exc is not None and base is not None and (exc - base) > MIN_EXCESS_RETURN,
    })

    exit_dd = _f((report.get("exit") or {}).get("avg_drawdown"))
    exit_base = _f((report.get("exit") or {}).get("baseline_avg_drawdown"))
    gates.append({
        "name": "exit 后回撤改善",
        "target": f"≥ {MIN_EXIT_DD_IMPROVE:.1%}",
        "actual": None if exit_dd is None or exit_base is None else round(exit_base - exit_dd, 4),
        "passed": exit_dd is not None and exit_base is not None
        and (exit_base - exit_dd) >= MIN_EXIT_DD_IMPROVE,
    })

    stop_dd = _f((report.get("stop") or {}).get("avg_drawdown"))
    stop_base = _f((report.get("stop") or {}).get("baseline_avg_drawdown"))
    gates.append({
        "name": "stop 后回撤改善",
        "target": f"≥ {MIN_STOP_DD_IMPROVE:.1%}",
        "actual": None if stop_dd is None or stop_base is None else round(stop_base - stop_dd, 4),
        "passed": stop_dd is not None and stop_base is not None
        and (stop_base - stop_dd) >= MIN_STOP_DD_IMPROVE,
    })

    return all(g["passed"] for g in gates), gates


async def run_backtest(codes: list[str], days: int = 120) -> dict[str, Any]:
    """对给定股票池逐日跑决策器,产出统计报告"""
    from app.services.kline_service import fetch_klines

    stats = {
        "entry": {"wins": 0, "n": 0, "ret": 0.0, "base_ret": 0.0},
        "exit": {"dd": 0.0, "n": 0, "base_dd": 0.0},
        "stop": {"dd": 0.0, "n": 0, "base_dd": 0.0},
    }

    for code in codes:
        try:
            klines = await fetch_klines(code, period="daily", count=days + HOLD_DAYS + 5)
        except Exception as e:  # noqa: BLE001
            logger.warning("回测 %s 取 K 线失败: %s", code, e)
            continue
        if len(klines) < 60:
            continue
        for i in range(59, len(klines) - HOLD_DAYS - 1):
            window = klines[: i + 1]
            try:
                ind = compute_indicators(window)
            except Exception:  # noqa: BLE001
                continue
            ctx = DecisionContext(
                stock_code=code,
                stock_name=None,
                indicators=ind,
                klines=window,
                current_price=_f(window[-1].get("close")),
                prev_close=_f(window[-2].get("close")) if len(window) >= 2 else None,
                cost_basis=None,
                shares=0,
                position_status="empty",
                env=MarketContext(),
            )
            decision = build_decision(ctx)
            kinds = {
                a["kind"] for a in decision["actions"] if a.get("status") == "now"
            }
            if not kinds:
                continue
            win, ret, dd = _forward_return(klines, i)
            b_ret, b_dd = _baseline(klines, i)
            if win is None or ret is None or dd is None:
                continue
            if "entry" in kinds:
                stats["entry"]["wins"] += int(win)
                stats["entry"]["n"] += 1
                stats["entry"]["ret"] += ret
                stats["entry"]["base_ret"] += (b_ret or 0.0)
            if "exit" in kinds:
                stats["exit"]["n"] += 1
                stats["exit"]["dd"] += dd
                stats["exit"]["base_dd"] += (b_dd or 0.0)
            if "stop" in kinds:
                stats["stop"]["n"] += 1
                stats["stop"]["dd"] += dd
                stats["stop"]["base_dd"] += (b_dd or 0.0)

    def _avg(total: float, n: int) -> float | None:
        return round(total / n, 4) if n > 0 else None

    entry_n = stats["entry"]["n"]
    report = {
        "codes": len(codes),
        "days": days,
        "samples": entry_n,
        "entry": {
            "win_rate": _avg(stats["entry"]["wins"], entry_n),
            "avg_return": _avg(stats["entry"]["ret"], entry_n),
            "baseline_avg_return": _avg(stats["entry"]["base_ret"], entry_n),
            "n": entry_n,
        },
        "exit": {
            "avg_drawdown": _avg(stats["exit"]["dd"], stats["exit"]["n"]),
            "baseline_avg_drawdown": _avg(stats["exit"]["base_dd"], stats["exit"]["n"]),
            "n": stats["exit"]["n"],
        },
        "stop": {
            "avg_drawdown": _avg(stats["stop"]["dd"], stats["stop"]["n"]),
            "baseline_avg_drawdown": _avg(stats["stop"]["base_dd"], stats["stop"]["n"]),
            "n": stats["stop"]["n"],
        },
    }
    passed, gates = evaluate_gates(report)
    report["gates"] = gates
    report["passed"] = passed
    return report


def main() -> None:
    """CLI:python -m app.services.decision_backtest 002185.SZ 600519.SH ..."""
    import json
    import sys

    codes = sys.argv[1:] or ["002185.SZ", "600519.SH", "000001.SZ"]
    report = asyncio.run(run_backtest(codes, days=120))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

同任务 1 Step 2 的命令（改 `tests/test_decision_backtest.py`）。

Expected: PASS —— `2 passed`

- [ ] **Step 5: 跑真实回测**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:PYTHONIOENCODING='utf-8'
& '.\.venv\Scripts\python.exe' -m app.services.decision_backtest 002185.SZ 600519.SH 000001.SZ 002594.SZ 300750.SZ 600036.SH 000725.SZ 002230.SZ 601318.SH 002415.SZ 000651.SZ 300059.SZ 600030.SH 002714.SZ 300760.SZ 688981.SH
```

Expected: 打印 JSON 报告。若 `passed=false`：

1. 把报告存到 `docs/analysis/decision-backtest-report.md`（含每条门槛的 target/actual/passed）
2. **按报告调整规则阈值**（改 `decision_service.py` 顶部的阈值常量），重跑
3. 重复直到 `passed=true`，或明确判定「该规则无价值」并从设计中移除
4. **不得下调门槛、不得跳过闸门**

- [ ] **Step 6: 写回测报告**

创建 `docs/analysis/decision-backtest-report.md`，含：样本池与样本量、每条门槛的 target/actual/passed、结论与所采取的规则调整。

- [ ] **Step 7: 提交**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- backend/app/services/decision_backtest.py backend/tests/test_decision_backtest.py backend/app/services/decision_service.py docs/analysis/decision-backtest-report.md
git commit -m "feat(decision): 回测闸门 + 规则校准报告"
```

---

## 任务 6：前端类型 + 决策卡组件

**Files:**
- Modify: `frontend/src/lib/types.ts`（文件末尾追加）
- Create: `frontend/src/components/desk/DecisionCard.tsx`

**Interfaces:**
- Consumes: `GET /api/stock/{code}/decision` → `{ decision: StockDecision }`
- Produces:
  ```tsx
  export interface DecisionAction {
    kind: 'entry' | 'add' | 'exit' | 'stop' | 't_sell' | 't_buyback' | 'watch';
    label: string;
    condition: string;
    price: number | null;
    basis: string[];
    status: 'now' | 'armed' | 'blocked';
  }
  export interface DecisionTPlan {
    suitable: boolean;
    tHigh: number | null;
    tLow: number | null;
    amplitudePct: number | null;
    sellTrigger: string;
    buybackTrigger: string;
    basePositionPct: string;
    unsuitableSignals: string;
    needsPosition: boolean;
  }
  export interface StockDecision {
    stockCode: string;
    stockName: string | null;
    verdict: 'buy' | 'add' | 'hold' | 'reduce' | 'sell' | 'wait';
    headline: string;
    confidence: 'high' | 'medium' | 'low';
    role: string;
    positionStatus: 'empty' | 'profit' | 'loss';
    actions: DecisionAction[];
    stopLoss: { price: number; basis: string } | null;
    positionPct: string;
    doNot: string[];
    tPlan: DecisionTPlan | null;
    trendState: { phase: string; note: string };
    marketEnv: {
      market: { state: string | null; upTotal: number | null; downTotal: number | null;
                 limitUp: number | null; limitDown: number | null;
                 changePct: number | null; summary: string };
      sector: { industry: string | null; changePct: number | null; fundNetYi: number | null;
                state: string | null; summary: string;
                leading: { name: string; netYi: number }[] };
      stockFlow: { direction: string | null; amountWan: number | null; category: string | null; summary: string };
      relative: { vsSectorPct: number | null; vsMarketPct: number | null; summary: string };
      degraded: string[];
    };
    dataQuality: { degraded: string[] };
  }
  // 组件
  export function DecisionCard({ decision, loading, error }: {
    decision: StockDecision | null;
    loading: boolean;
    error: string | null;
  }): JSX.Element
  ```

- [ ] **Step 1: 追加前端类型**

在 `frontend/src/lib/types.ts` 末尾追加上述类型定义（注意字段名是 camelCase —— 后端返回 snake_case，由 `api.ts` 的 `snakeToCamel` 拦截器转换；`up_5_10` 这类数字段名由 `camelKey` 的窄口径规则处理，本接口无此类字段）。

- [ ] **Step 2: 创建 DecisionCard.tsx**

创建 `frontend/src/components/desk/DecisionCard.tsx`：

```tsx
'use client';

import { useState } from 'react';

import clsx from 'clsx';

import type { DecisionAction, StockDecision } from '@/lib/types';

const VERDICT_META: Record<StockDecision['verdict'], { label: string; cls: string }> = {
  buy: { label: '可以建仓', cls: 'text-up border-up/40 bg-up-bg' },
  add: { label: '可以加仓', cls: 'text-up border-up/40 bg-up-bg' },
  hold: { label: '持股观察', cls: 'text-text-pri border-border-def bg-bg-subtle' },
  reduce: { label: '建议减仓', cls: 'text-warn border-warn/40 bg-warn-bg' },
  sell: { label: '建议止损', cls: 'text-down border-down/40 bg-down-bg' },
  wait: { label: '继续等待', cls: 'text-text-ter border-border-def bg-bg-subtle' },
};

const STATUS_META: Record<DecisionAction['status'], { label: string; cls: string }> = {
  now: { label: '现在可做', cls: 'text-up border-up/40 bg-up-bg' },
  armed: { label: '待触发', cls: 'text-text-ter border-border-def bg-bg-subtle' },
  blocked: { label: '已否决', cls: 'text-text-ter border-border-def bg-bg-subtle' },
};

function fmtNum(n: number | null | undefined, digits = 2): string {
  return n == null ? '--' : n.toFixed(digits);
}

/**
 * 操作决策卡(v0.9)
 *
 * **定位**:确定性引擎算出来的行动清单,**不是** LLM 解读。
 * 与 AI 解读冲突时以本卡为准(AI 只是一层白话解释)。
 *
 * 三态:loading(骨架)/ ready / error(显示降级原因,不空白)。
 */
export function DecisionCard({
  decision,
  loading,
  error,
}: {
  decision: StockDecision | null;
  loading: boolean;
  error: string | null;
}) {
  const [showBlocked, setShowBlocked] = useState(false);

  if (loading) {
    return (
      <div className="rounded-md border border-border-def bg-bg-subtle p-3 space-y-2" aria-busy>
        <div className="h-4 w-1/2 rounded-sm bg-bg-elevated animate-pulse" />
        <div className="h-3 w-full rounded-sm bg-bg-elevated animate-pulse" />
        <div className="h-3 w-4/5 rounded-sm bg-bg-elevated animate-pulse" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-border-def bg-bg-subtle p-3">
        <div className="text-[11px] font-semibold text-text-pri">操作决策</div>
        <div className="mt-1 text-[11px] text-text-ter">决策暂不可用:{error}</div>
      </div>
    );
  }

  if (!decision) {
    return (
      <div className="rounded-md border border-border-def bg-bg-subtle p-3">
        <div className="text-[11px] font-semibold text-text-pri">操作决策</div>
        <div className="mt-1 text-[11px] text-text-ter">选一只股票后给出买卖建议</div>
      </div>
    );
  }

  const vm = VERDICT_META[decision.verdict] ?? VERDICT_META.wait;
  const shown = decision.actions.filter((a) => a.status !== 'blocked');
  const blocked = decision.actions.filter((a) => a.status === 'blocked');
  const tp = decision.tPlan;
  const env = decision.marketEnv;

  return (
    <div className="rounded-md border border-border-def bg-bg-subtle p-3 space-y-2.5">
      {/* 头部:结论 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11px] font-semibold text-text-pri">操作决策</span>
        <span className={clsx('text-[10px] px-1.5 py-px rounded-sm border', vm.cls)}>{vm.label}</span>
        <span className="text-[10px] text-text-ter">{decision.role}</span>
        <span className="ml-auto text-[10px] text-text-ter">
          置信度{decision.confidence === 'high' ? '高' : decision.confidence === 'low' ? '低' : '中'}
        </span>
      </div>
      <div className="text-[11.5px] leading-[1.5] text-text-pri">{decision.headline}</div>

      {/* 行动清单 */}
      {shown.length > 0 ? (
        <ul className="space-y-1.5">
          {shown.map((a, i) => (
            <li key={`${a.kind}-${i}`} className="rounded-sm bg-bg-elevated px-2 py-1.5">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-medium text-text-pri">{a.label}</span>
                <span className={clsx('text-[9px] px-1 py-px rounded-sm border', STATUS_META[a.status].cls)}>
                  {STATUS_META[a.status].label}
                </span>
                {a.price != null && (
                  <span className="ml-auto font-mono text-[11px] tabular-nums text-text-pri">
                    {fmtNum(a.price)} 元
                  </span>
                )}
              </div>
              <div className="mt-0.5 text-[10.5px] leading-[1.45] text-text-sec">{a.condition}</div>
              {a.basis.length > 0 && (
                <div className="mt-0.5 text-[9.5px] leading-[1.4] text-text-ter">{a.basis.join(' · ')}</div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-[10.5px] text-text-ter">当前没有可执行动作,等条件触发。</div>
      )}

      {/* 仓位 / 止损 */}
      <div className="grid grid-cols-2 gap-1.5">
        <div className="rounded-sm bg-bg-elevated px-2 py-1.5">
          <div className="text-[9px] text-text-ter">仓位建议</div>
          <div className="mt-0.5 text-[10.5px] leading-[1.4] text-text-sec">{decision.positionPct}</div>
        </div>
        <div className="rounded-sm bg-bg-elevated px-2 py-1.5">
          <div className="text-[9px] text-text-ter">止损</div>
          <div className="mt-0.5 text-[10.5px] leading-[1.4] text-text-sec">
            {decision.stopLoss
              ? `${fmtNum(decision.stopLoss.price)} 元(${decision.stopLoss.basis})`
              : '暂无止损位'}
          </div>
        </div>
      </div>

      {/* 做 T */}
      {tp && (
        <div className="rounded-sm bg-bg-elevated px-2 py-1.5">
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] text-text-ter">做 T</span>
            {tp.suitable ? (
              <span className="text-[9.5px] text-up">可做</span>
            ) : (
              <span className="text-[9.5px] text-text-ter">不建议</span>
            )}
            {tp.suitable && (
              <span className="ml-auto font-mono text-[10px] tabular-nums text-text-pri">
                {fmtNum(tp.tLow)}~{fmtNum(tp.tHigh)} 元(振幅 {fmtNum(tp.amplitudePct, 1)}%)
              </span>
            )}
          </div>
          <div className="mt-0.5 text-[10px] leading-[1.4] text-text-sec">
            {tp.suitable ? (
              <>
                {tp.sellTrigger}
                <br />
                {tp.buybackTrigger}
                {tp.basePositionPct && <span> · 底仓留 {tp.basePositionPct}</span>}
                {tp.needsPosition && <span className="text-warn"> · 当前无底仓,做 T 前需先建仓</span>}
              </>
            ) : (
              tp.unsuitableSignals
            )}
          </div>
        </div>
      )}

      {/* 别动 */}
      {decision.doNot.length > 0 && (
        <div className="text-[10px] leading-[1.5] text-text-ter">
          <span className="text-warn">别动:</span> {decision.doNot.join(' · ')}
        </div>
      )}

      {/* 走势 / 市场环境 */}
      <div className="border-t border-border-def/60 pt-1.5 space-y-0.5">
        <div className="text-[10px] leading-[1.45] text-text-sec">
          <span className="text-text-ter">走势:</span> {decision.trendState.phase}
          <span className="text-text-ter"> · {decision.trendState.note}</span>
        </div>
        <div className="text-[10px] leading-[1.45] text-text-ter">
          {env.market.summary}
          {env.sector.summary && <span> · {env.sector.summary}</span>}
          {env.stockFlow.summary && <span> · {env.stockFlow.summary}</span>}
        </div>
        {env.relative.summary && (
          <div className="text-[10px] leading-[1.45] text-text-ter">{env.relative.summary}</div>
        )}
        {decision.dataQuality.degraded.length > 0 && (
          <div className="text-[9.5px] leading-[1.4] text-text-ter">
            降级:{decision.dataQuality.degraded.join(' · ')}
          </div>
        )}
      </div>

      {/* 已否决 */}
      {blocked.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setShowBlocked((v) => !v)}
            className="text-[10px] text-text-ter hover:text-text-sec"
          >
            {showBlocked ? '收起' : `为什么不做(${blocked.length})`}
          </button>
          {showBlocked && (
            <ul className="mt-1 space-y-1">
              {blocked.map((a, i) => (
                <li key={`b-${a.kind}-${i}`} className="rounded-sm bg-bg-subtle px-2 py-1">
                  <div className="text-[10.5px] text-text-sec">{a.label}</div>
                  <div className="text-[9.5px] text-text-ter">
                    {a.basis.join(' · ')}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: 类型检查**

```powershell
Set-Location 'D:\zga-study\rich\frontend'
npm run typecheck
```

Expected: 无错误（`JSX.Element` 若在 React 18 + 新版 typescript 下报找不到，用 `React.JSX.Element` 或直接去掉返回类型标注）。

- [ ] **Step 4: 提交**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- frontend/src/lib/types.ts frontend/src/components/desk/DecisionCard.tsx
git commit -m "feat(frontend): 决策卡组件 + 类型定义"
```

---

## 任务 7：接入盯盘台右栏

**Files:**
- Modify: `frontend/src/components/desk/DecisionColumn.tsx`
- Modify: `frontend/src/app/(app)/page.tsx`

**Interfaces:**
- Consumes: 任务 6 的 `DecisionCard` / `StockDecision`
- Produces: `DecisionColumn` 新增 props `decision` / `decisionLoading` / `decisionError`

- [ ] **Step 1: DecisionColumn 接props并渲染**

修改 `frontend/src/components/desk/DecisionColumn.tsx`：

导入：
```tsx
import { DecisionCard } from '@/components/desk/DecisionCard';
import type { StockDecision } from '@/lib/types';
```

在 props 类型里加三项：
```tsx
  decision: StockDecision | null;
  decisionLoading: boolean;
  decisionError: string | null;
```

在组件内（`const ind = analysis?.indicators ?? null;` 之后）加：
```tsx
  const decisionDegraded = decision?.dataQuality?.degraded ?? [];
```

在 return 的最前面（`<div className="flex flex-col min-h-0">` 的第一个子元素）插入：
```tsx
      {/* 0. 操作决策卡(确定性引擎,置顶 —— 用户问的第一个问题是「我现在该干什么」) */}
      <section className="px-3 py-2.5 border-b border-border-def">
        <DecisionCard
          decision={decision}
          loading={decisionLoading}
          error={decisionError}
        />
      </section>
```

> `decisionDegraded` 若未使用会触发 lint 告警 —— 不用它就不要加这一行。

- [ ] **Step 2: page.tsx 并发拉取 decision**

在 `frontend/src/app/(app)/page.tsx`：

(a) 导入类型：
```tsx
import type {
  ...
  StockDecision,
} from '@/lib/types';
```

(b) 加 state：
```tsx
  const [decision, setDecision] = useState<StockDecision | null>(null);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
```

(c) 加一个拉取函数（放在 `selectStock` 之前）：
```tsx
  /** 决策卡:纯确定性、无 LLM —— 与 analysis 并行拉取,互不阻塞 */
  const fetchDecision = useCallback(async (code: string) => {
    setDecisionLoading(true);
    setDecisionError(null);
    try {
      const r = await apiGet<{ decision: StockDecision }>(
        `/stock/${encodeURIComponent(code)}/decision`,
      );
      setDecision(r.decision ?? null);
    } catch (e) {
      setDecision(null);
      setDecisionError(e instanceof Error ? e.message : '未知错误');
    } finally {
      setDecisionLoading(false);
    }
  }, []);
```

(d) 在 `selectStock` 里调用它（`selectStock` 是 `useCallback`，依赖需加 `fetchDecision`）：
```tsx
    apiGet<Quote>(`/quotes/${encodeURIComponent(code)}`)
      .then(setSelectedQuote)
      .catch(() => {});
    fetchDecision(code);
```
并把 `selectStock` 的依赖数组改为 `[fetchDecision]`。

(e) 把 props 传给 `<DecisionColumn ...>`：
```tsx
                decision={decision}
                decisionLoading={decisionLoading}
                decisionError={decisionError}
```

- [ ] **Step 3: 类型检查**

```powershell
Set-Location 'D:\zga-study\rich\frontend'
npm run typecheck
```

Expected: 无错误

- [ ] **Step 4: 提交**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- frontend/src/components/desk/DecisionColumn.tsx "frontend/src/app/(app)/page.tsx"
git commit -m "feat(frontend): 决策卡接入盯盘台右栏(选中即出,不等 AI)"
```

---

## 任务 8：端到端实测 + 文档登记

**Files:**
- Modify: `docs/roadmap.md`
- Create: `docs/design/trading-desk-v3-decision-card.md`（可选：版面与交互说明）

**Interfaces:**
- Consumes: 全部前置任务
- Produces: 文档 + 实测证据

- [ ] **Step 1: 生产构建**

```powershell
Set-Location 'D:\zga-study\rich'
cmd /c "scripts\dev.cmd" -Action stop
Set-Location 'D:\zga-study\rich\frontend'
npm run build
```

Expected: 构建成功，27+ 路由全部生成

- [ ] **Step 2: 重启服务**

```powershell
Set-Location 'D:\zga-study\rich'
cmd /c "scripts\dev.cmd"
```

Expected: backend/frontend 均 OK

- [ ] **Step 3: 端点实测**

```powershell
$r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/stock/002185.SZ/decision' -TimeoutSec 40
$r.decision.verdict
$r.decision.headline
$r.decision.actions | Format-Table kind,label,status,price
$r.decision.t_plan
$r.decision.trend_state
$r.decision.market_env.market.summary
$r.decision.do_not
```

Expected: 全部有真实内容，无 null 崩溃

- [ ] **Step 4: 浏览器实测（真实页面）**

1. 打开 `http://localhost:5173/`
2. 选一只**空仓**股票 → 决策卡应显示「建仓参考」+ 买点条件
3. 选一只**持仓**股票（如 002185.SZ 华天科技）→ 应显示「止盈参考」或「解套参考」+ 做T 区块
4. 切换主题（深/浅）→ 决策卡配色跟随
5. 窄屏（<1024px）→ 决策栏仍在（不隐藏）
6. 控制台无 error

> 宽屏布局验证走 `frontend/public/previews/desk-frame.html`（把真实首页按 1440px 渲染进 iframe）。

- [ ] **Step 5: 登记 roadmap**

在 `docs/roadmap.md` 阶段表后追加一段：

```markdown
### 阶段 8 · 盯盘决策引擎 ✅ 已完成

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 确定性行动卡 | `GET /api/stock/{code}/decision` | 买/卖/做T/亏损/盈利/走势/市场环境七问,**零 LLM** |
| 判定器 | `backend/app/services/decision_service.py` | 纯函数,可单测可回测 |
| 市场环境 | `backend/app/services/market_context_service.py` | 大盘/行业/资金/相对强弱,全链路降级 |
| 回测闸门 | `backend/app/services/decision_backtest.py` | 门槛先定,不达标不上线 |
| 前端 | `frontend/src/components/desk/DecisionCard.tsx` | 盯盘台右栏置顶 |

> 设计文档:`docs/superpowers/specs/2026-10-21-stock-decision-engine-design.md`
```

- [ ] **Step 6: 全量后端测试 + 前端构建最终确认**

```powershell
Set-Location 'D:\zga-study\rich\backend'
$env:DATABASE_URL='sqlite+aiosqlite:///./.pytest_tmp/pytest_run.db'
$env:PYTHONIOENCODING='utf-8'
$env:RICH_TEST_TMP='D:\zga-study\rich\backend\.pytest_tmp\rich'
& '.\.venv\Scripts\python.exe' -m pytest -q --no-header -p no:cacheprovider
```

Expected: 全绿，0 failed

- [ ] **Step 7: 提交**

```powershell
Set-Location 'D:\zga-study\rich'
git add -- docs/roadmap.md docs/design/trading-desk-v3-decision-card.md
git commit -m "docs: 登记阶段 8 盯盘决策引擎 + 实测记录"
```

---

## 完成标准

全部任务完成后，下列每一条都必须**有证据**：

- [ ] `GET /api/stock/{code}/decision` 返回 200，字段完整，数字真实（任务 4 Step 5、任务 8 Step 3）
- [ ] `pytest -q` 全绿，0 failed（任务 8 Step 6）
- [ ] `npm run typecheck` + `npm run build` 通过（任务 6 Step 3、任务 8 Step 1）
- [ ] 回测报告存在且 `passed=true`，否则**规则已按报告调整并重跑**（任务 5 Step 5~6）
- [ ] 浏览器实测：空仓票显示建仓参考、持仓票显示止盈/解套参考、做T 区块有内容、别动清单非空（任务 8 Step 4）
- [ ] 决策卡与 AI 解读同时存在，且**决策卡不依赖**「开始分析」按钮
- [ ] 降级路径验证：断网 / 删掉 industry_map.json 时，决策卡仍返回，只在 `data_quality.degraded` 标注，**不空白、不编数字**
