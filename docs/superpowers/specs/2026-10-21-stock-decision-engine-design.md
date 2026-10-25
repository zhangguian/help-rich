# 盯盘决策引擎设计（Deterministic Decision Engine）

> 日期：2026-10-21
> 状态：设计已批准，实施中（v0.9 修订：§6.2 补 G5 T 区间宽度校验、止损提示归位到 Decision 顶层 `stop_loss`）
> 背景：用户诉求「股民盯盘，还是不知道这只股票什么时候该买什么时候该卖，什么时候适合做T，亏损时该怎么做，盈利是该怎么做，这股票的市场情况如何，现在的走势如何」
> 原则：遵循项目既有铁律 **「LLM 只翻译不计算」——确定性指标由算法算**（见 `docs/roadmap.md` 阶段 4）

---

## 一、背景与问题定位

### 1.1 现状盘点（已核实，非推测）

项目**已经拥有**这些能力：

| 能力 | 实现位置 | 状态 |
| --- | --- | --- |
| LLM 操作建议（建仓/止盈/解套三种角色） | `backend/app/services/stock_advice_service.py` `ANALYSIS_SYSTEM` schema | 已有 |
| 做 T 策略（区间/底仓比例/卖出触发/买回触发） | 同上 `t_strategy` 字段 | 已有 |
| 6 个结构化操作字段（价位/止损/仓位/触发/周期/不动） | 同上 `advice` 子结构 | 已有 |
| 全套技术指标 | `backend/app/services/ta_service.py` | 已有 |
| 行业归属（三级兜底） | `backend/app/services/industry_service.py` | 已有 |
| 行业强弱（成分股等权合成 K 线，30min 缓存） | `backend/app/services/sector_kline_service.py` | 已有 |
| 板块资金流排行 | `backend/app/services/sector_fund_flow_service.py` | 已有 |
| 全市场情绪（5568 只全量，60s 缓存） | `backend/app/services/market_snapshot.py` + `market_overview_service.py` | 已有 |
| 本股资金流 | `backend/app/services/fund_flow_service.py` | 已有 |
| 历史同向信号胜率回检 | `backend/app/services/signal_winrate.py` | 已有 |
| 回测引擎 | `backend/app/services/backtest/` | 已有 |

### 1.2 为什么用户仍然「不知道」

四个真实原因（均已在代码与实拍中确认）：

1. **答案 100% 依赖 LLM**：必须手动点「开始分析」（20~35s、计费）。LLM 未配置 / 超时 / JSON 畸形 → `ai=None` → 前端**一条买/卖建议都没有**，只剩指标。
2. **答案是散文**：如「建仓参考 95.00~98.50 元，跌破 92 止损」，用户必须自己翻译成动作。
3. **「市场情况」根本不在分析里**：板块资金流、大盘情绪、本股资金流都是独立接口、独立页面（`/market`、`/sector-fund-flow`），盯盘时看不到。
4. **「现在的走势如何」散落多处**：`channel` / `signal` / AI `trend` 三处各说一半，没有一句话结论。

### 1.3 本设计要解决什么

把「买/卖/做T/亏损怎么办/盈利怎么办/市场情况/走势」从 **LLM 散文**变成 **确定性、可执行、带证据的条件清单**，
且**在没有 LLM 的情况下也能秒出答案**。

---

## 二、目标与非目标

### 2.1 目标

1. 新增**纯算法决策层**（后端），输入已有指标 + 持仓 + 市场环境，输出结构化决策卡。
2. 决策以**条件清单**为主形态：「触发条件 → 动作 + 价位 + 依据数字」。
3. 新增**市场环境聚合层**，把行业强弱、板块资金流、全市场情绪、本股资金流、相对强弱接进同一条链路。
4. 在**盯盘台右栏置顶**渲染决策卡；不依赖「开始分析」按钮。
5. **回测验证闸门**：决策规则必须跑赢基准才允许上线。

### 2.2 非目标（本轮明确不做）

- 不接消息面（新闻 / 公告 / 事件因子 / 龙虎榜）。
- 不接多智能体辩论结论。
- 不做「条件命中 → 推送提醒」（价格提醒 / 微信通知）联动。
- 不做模拟盘下单联动。
- 不改 `ta_service` 现有指标算法，只消费其输出。
- 不做**网格自动挂单 / 执行引擎**：网格只给配置建议（区间、格数、资金、失效条件），不下单、不回测收益。
- 不做盘中复盘逐票建议的口径统一（本期只统一「操作决策卡 ↔ AI 解读」这一对）。

### 2.3 目标补充（2026-10-25 增补：操作建议增强）

> 本节为 v0.10「操作建议增强」增补。上文 §2.1 的目标仍然有效，以下为**同层新增**，
> 与之冲突处以本节为准。

1. **操作决策卡内新增「操作建议」区**：六格要素（价位 / 止损 / 仓位 / 触发 / 时间 / 不动）+ AI 白话 + **网格交易配置建议**。
2. **决策引擎补 5 个维度**：成本锚点 / 时间窗口 / 费用影响 / 品种规则 / 集中度。**只增信息，不改既有 verdict 逻辑与阈值**（见 §6.8）。
3. **新增网格交易配置建议**：判定器 `judge_grid_plan`（见 §6.9），产出独立子块 `grid_plan`。
4. **口径统一（消除两套说法）**：把决策压成**事实包**（见 §5.4），`/analysis` 的提示词注入同一份事实包，
   AI 只能引用、不得改写其中的数字；前端**以决策卡为准**，AI 解读区只保留白话。
5. **AI 白话是增量增强，不是依赖**：
   - `/decision` 端点**仍然零 LLM、纯算法、秒出**（本条不可动摇）；
   - 白话默认复用既有 `/analysis` 结果（零额外成本），另提供**按钮触发**的 `GET /api/stock/{code}/decision-advice`；
   - LLM 失败即退回规则文案，**决策卡永不空白**。

> ⚠️ **与旧版 §2.2 首条的冲突说明**：旧版写「不增强 LLM schema、不新增 LLM 调用」。
> 本轮**确实新增**了一个显式触发的端点（`/decision-advice`）与一个事实包注入（`/analysis` 提示词），
> 故该条已被本节取代。**「决策端点不得依赖 LLM」这一条仍然成立且继续强制。**

---

## 三、方案选型

### 3.1 引擎内部结构的三条路线

| | A. 单点结论 | **B. 条件清单（选定）** | C. 情景决策树 |
| --- | --- | --- | --- |
| 输出形态 | 「现在该买」+ 少量参数 | N 条「触发条件 → 动作」，每条带价位 + 依据 | 完整 if/else 树 |
| 能否回答「**什么时候**该买」 | 否 | 是 | 是 |
| 可解释性 | 弱 | 每条可追溯到具体指标数字 | 强但难读 |
| 组合爆炸 | 无 | 无 | 严重 |
| 可单测性 | 易 | 易（判定器彼此独立） | 难 |

**选定 B**。核心理由：用户问的是「**什么时候**」，B 的每一条都是可执行的条件
（「回踩 13.61 不破且绿柱缩短 → 首仓 20%」）；条件未触发时明确回答「在等什么」。
且每条都携带**依据数字**，天然满足项目「引用的数字必须与输入完全一致」的纪律。

### 3.2 引擎位置

**后端**。理由：可单测、可被将来的提醒引擎与多智能体复用、前端不做业务判断。

### 3.3 已确认的范围选择

- 决策产出形态：**确定性行动卡为主，LLM 降级为可选白话翻译**
- 市场环境范围：**技术面 + 资金面 + 大盘**（行业板块强弱、板块资金流、全市场涨跌家数情绪、本股资金流）
- 交付位置：**只做盯盘台首页右栏**（改动最小，选股即出答案）

---

## 四、架构

```
┌─────────────────────────────────────────────────────────────┐
│  backend/app/services/decision_service.py                   │
│  纯判定器（零 IO、零 LLM、可单测）                            │
│    judge_trend()      现在的走势如何                          │
│    judge_t_plan()     什么时候适合做T                        │
│    judge_entry()      什么时候该买（空仓）                    │
│    judge_exit()       什么时候该卖（浮盈）                    │
│    judge_loss_plan()  亏损了怎么办                           │
│    judge_do_not()     什么情况别动                           │
│    derive_verdict()   actions → 单一结论                       │
├─────────────────────────────────────────────────────────────┤
│  backend/app/services/market_context_service.py             │
│  市场环境聚合（只读现有服务，不新增抓取逻辑）                    │
│    get_market_context(code, stock_change_pct)               │
├─────────────────────────────────────────────────────────────┤
│  backend/app/api/stock.py                                   │
│    GET /api/stock/{stock_code}/decision                     │
└─────────────────────────────────────────────────────────────┘
                              ▲
                              │ HTTP
┌─────────────────────────────────────────────────────────────┐
│  frontend/src/components/desk/DecisionCard.tsx（新）          │
│  渲染在 DecisionColumn 顶部                                  │
│  frontend/src/app/(app)/page.tsx                            │
│    选中股票时并发请求 /decision（与 analysis 并行，互不阻塞）   │
└─────────────────────────────────────────────────────────────┘
```

**依赖方向**：`decision_service` 只依赖 `ta_service` 的输出字典与 `market_context_service` 的输出，
不依赖 FastAPI、不依赖数据库、不依赖 LLM provider。IO 全部收敛在 `market_context_service` 与 API 层。

---

## 五、数据契约

### 5.1 输入 `DecisionContext`

```python
@dataclass(frozen=True)
class DecisionContext:
    stock_code: str
    stock_name: str | None
    indicators: dict[str, Any]      # ta_service.compute_indicators(klines) 原样传入
    klines: list[dict[str, Any]]     # 原始日 K（升序）—— 近 5 根振幅 / 近 3 日涨幅 / high-low 需从原始序列算
    current_price: float | None      # 实时价；None → 用 indicators.latest_close 并标注
    prev_close: float | None         # 昨收（来自实时报价 quote.prevClose）
                                      # 报价缺失时 → 用 K 线倒数第二根收盘价
    cost_basis: float | None         # 用户持仓均价；None → 空仓
    shares: int                      # 持股数；0 → 空仓
    position_status: str             # 'empty' | 'profit' | 'loss'
    env: MarketContext               # 市场环境
```

`position_status` 判定规则（唯一来源，不接受外部传入的其它值）：

```
shares == 0                      → 'empty'
current_price >= cost_basis      → 'profit'
否则                              → 'loss'
```

**统一计算价 `effective_price`**

所有涉及价格与百分比的计算**一律**使用 `effective_price`：

```
effective_price = current_price if current_price is not None else indicators.latest_close
```

若使用了 `latest_close`（即实时价缺失），必须在 `data_quality.degraded` 写入
`「实时价不可用,按最新收盘价 {latest_close} 计算」`，前端据此标注「按收盘价计算」。
实现时不得在各个判定器里各自判断 `current_price` 是否为 None。

### 5.2 输出 `Decision`

```python
{
  "stock_code": str,
  "stock_name": str | None,
  "verdict": "buy" | "add" | "hold" | "reduce" | "sell" | "wait",
  "headline": str,                 # 一句话结论（中文白话，含具体数字）
  "confidence": "high" | "medium" | "low",
  "role": "建仓参考" | "止盈参考" | "解套参考",
  "position_status": "empty" | "profit" | "loss",
  "actions": [Action],
  "stop_loss": {"price": float, "basis": str} | None,
  "position_pct": str,
  "do_not": [str],
  "t_plan": TPlan | None,
  "grid_plan": GridPlan | None,        # v0.10：网格交易配置建议（§6.9）
  "suggestions": Suggestions | None,   # v0.10：操作建议六格（§6.10）
  "advice": str | None,                # v0.10：规则白话兜底（零 LLM）
  "cost_anchor": CostAnchor | None,        # v0.10：§6.8 成本锚点
  "time_window": TimeWindow | None,        # v0.10：§6.8 时间窗口
  "cost_effect": CostEffect | None,        # v0.10：§6.8 费用影响
  "instrument_rule": InstrumentRule | None, # v0.10：§6.8 品种规则
  "concentration": Concentration | None,    # v0.10：§6.8 集中度
  "trend_state": {"phase": str, "note": str},
  "market_env": MarketContext,
  "data_quality": {"degraded": [str]},
}
```

```python
Action = {
  "kind": "entry" | "add" | "exit" | "stop" | "t_sell" | "t_buyback" | "watch",
  "label": str,          # 短标签，如「支撑企稳建仓」
  "condition": str,      # 触发条件，必须含具体数字
  "price": float | None, # 该动作对应的价位
  "basis": [str],        # 依据列表，每条引用一个输入里的具体数字
  "status": "now" | "armed" | "blocked",
}
# now   = 此刻条件已满足，该做
# armed = 条件待触发，写明触发什么
# blocked = 已否决，必须写明否决理由

TPlan = {
  "suitable": bool,
  "t_high": float | None,
  "t_low": float | None,
  "amplitude_pct": float | None,
  "sell_trigger": str,
  "buyback_trigger": str,
  "base_position_pct": str,
  "unsuitable_signals": str,   # suitable=False 时写明原因
  "needs_position": bool,      # 空仓时 True：做 T 需先有底仓
}

# ---- v0.10 网格交易配置建议（§6.9）----
GridPlan = {
  "suitable": bool,
  "mode": "add" | "base" | None,   # add=加仓网格（需额外现金）；base=底仓高抛低吸（零额外现金）
  "reason": str,
  "range_low": float | None,       # 区间下沿（保守边：max(近20日最低价, P20)）
  "range_high": float | None,      # 区间上沿（保守边：min(近20日最高价, P80)）
  "span_pct": float | None,        # 区间宽度 %（相对现价）
  "grids": int | None,             # 网格档数（≤ GRID_MAX_GRIDS）
  "step_pct": float | None,        # 每格步长 %
  "step_price": float | None,      # 每格价差（元）
  "shares_per_grid": int | None,   # 每格股数（A 股 / ETF 场内均为 100 股 1 手）
  "capital_per_grid": float | None,   # 每格所需资金（元）
  "cash_needed": float | None,     # 加仓网格最坏情况累计所需现金（元）
  "cash_available": float | None,  # 账户可用资金（元）；None = 未填写
  "net_step_pct": float | None,    # 单格净收益率 %（已扣往返费用率）
  "roundtrip_fee_pct": float | None,   # 往返费用率 %（股票 0.102 / ETF 0.052 口径）
  "fee_basis": "configured" | "default_estimate" | None,  # 费用口径标注（见 §6.8.3）
  "net_profit_per_grid": float | None,   # 单格净收益金额（元，已扣最低佣金）
  "replace_t_plan": bool,          # True = 建议用网格替代手动做 T（二者择一）
  "risk": str,                     # 失效条件（跌破下沿 / 单边下行资金耗尽）
  "unsuitable_signals": str,       # suitable=False 时写明原因
}

# ---- v0.10 操作建议六格（§6.10）----
Suggestions = {
  "price":     {"label": "价位", "value": str} | None,
  "stop_loss": {"label": "止损", "value": str} | None,
  "position":  {"label": "仓位", "value": str} | None,
  "trigger":   {"label": "触发", "value": str} | None,
  "timing":    {"label": "时间", "value": str} | None,
  "avoid":     {"label": "不动", "value": str} | None,
}

# ---- v0.10 五个补维度（§6.8）----
CostAnchor = {
  "cost_basis": float | None,
  "current_price": float | None,
  "pnl_pct": float | None,          # 浮盈(+)/浮亏(-) %
  "break_even_gap_pct": float | None,  # 回本还需涨幅 %（浮亏时）
  "distance_to_stop_pct": float | None,  # 距止损位 %（负 = 已在止损下方）
  "distance_to_target_pct": float | None,  # 到第一目标 P80 的空间 %
  "risk_reward": float | None,      # 风险收益比 = 上行空间 / 下行空间
}
TimeWindow = {
  "holding_days": int | None,       # 自然日
  "source": "transactions" | "snapshot" | None,  # 起点来源(决定文案口径,见 §6.8.2)
  "overdue": bool | None,           # 是否超过 HOLD_DAYS_LIMIT
  "overdue_text": str | None,       # 超期文案(未超期为 None)
  "note": str,                     # 口径说明(随 source 变化)
}
CostEffect = {
  "roundtrip_fee_pct": float | None,
  "fee_basis": "configured" | "default_estimate" | None,
  "spread_pct": float | None,       # 做 T 预期差价 %
  "worth_it": bool | None,          # 差价 ≥ 2 × 往返费用率
  "note": str,                     # ETF 免印花税 / 过户费说明
}
InstrumentRule = {
  "kind": "stock" | "etf",
  "t0": bool,
  "notes": [str],                  # 无涨跌停 / 免印花税过户费 / 当日可回转
}
Concentration = {
  "cost_share_pct": float | None,  # 该票持仓成本占比 %
  "level": "low" | "warn" | "strong" | None,
  "note": str,
}
```

### 5.3 市场环境 `MarketContext`

```python
{
  "market": {
    "state": "warm" | "neutral" | "cold" | None,
    "up_total": int | None, "down_total": int | None, "flat_total": int | None,
    "limit_up": int | None, "limit_down": int | None, "sample_size": int | None,
    "summary": str,
  },
  "sector": {
    "industry": str | None,
    "change_pct": float | None,      # 行业等权 K 线近 1 日涨幅
    "vs_market_pct": float | None,   # 行业涨幅 - 大盘涨幅
    "fund_net_yi": float | None,     # 板块资金净流入（亿元）—— 口径不匹配时为 None
    "fund_direction": "in" | "out" | None,
    "state": "leading" | "warm" | "lagging" | "cold" | None,
    "leading": [{"name": str, "net_yi": float}],   # 今日资金主攻板块 Top3
    "summary": str,
  },
  "stock_flow": {
    "direction": "in" | "out" | None,
    "amount_wan": float | None,
    "category": str | None,          # 'large' | 'medium' | 'small'
    "summary": str,
  },
  "relative": {
    "vs_sector_pct": float | None,   # 个股涨幅 - 行业涨幅
    "vs_market_pct": float | None,   # 个股涨幅 - 大盘涨幅
    "summary": str,
  },
  "degraded": [str],                 # 本层降级说明
}
```

### 5.4 事实包 `FactPack`（v0.10 · 单一真相源）

**目的**：决策卡与 AI 解读对同一只票给出两套说法。事实包把决策压成**可序列化的确定性数字集合**，
两端都只引用它 → 口径天然统一，不再事后校对。

```python
FactPack = {
  "stock_code": str,
  "as_of": str | None,              # K 线最新日（AI 解读的数据时间）
  "verdict": str,
  "headline": str,
  "role": str,
  "confidence": str,
  "position_status": str,
  "actions": [Action],              # 只保留 status ∈ {now, armed} 的可执行项
  "suggestions": Suggestions | None, # 六格（确定性）
  "t_plan": TPlan | None,
  "grid_plan": GridPlan | None,
  "cost_anchor": CostAnchor | None,
  "time_window": TimeWindow | None,
  "cost_effect": CostEffect | None,
  "instrument_rule": InstrumentRule | None,
  "concentration": Concentration | None,
  "stop_loss": {"price": float, "basis": str} | None,
  "position_pct": str,
  "do_not": [str],
  "degraded": [str],
}
```

**铁律**：
1. 事实包**只含确定性数字**，不得出现任何 LLM 生成的措辞或推算值。
2. LLM 提示词里，事实包是**唯一真相源**：必须原样引用，不得改写、不得另算、不得补充未列出的价位。
3. 事实包**不含**「预计赚多少 / 目标价 / 胜率」——沿用 §10.4 口径（胜率型概率提示，不承诺收益）。
4. 任一字段为 `None` 时，LLM 必须写「暂无」，不得用 `0` 或空串顶替（零编造不变量，见 §11）。

**落点**：
- `backend/app/services/decision_advice_service.py::build_fact_pack(decision)`（纯函数）
- `/analysis` 端点把事实包 JSON 追加进 `user_msg`（复用该端点已有的 klines/quote/position，**不增加网络 IO**）
- `/decision-advice` 端点把事实包作为 LLM 输入，只输出白话

---

## 六、判定规则规格

> 以下规则是**实现契约**，不是示意。每条阈值都写死，实现时不得自行调整。

### 6.1 `judge_trend` → 现在的走势如何

输入：`indicators` 的 `channel.state`、`ma`、`volume_price.direction`、`boll.position` / `boll.squeeze`、
`kdj.zone`、`volume.ratio`。

先算两个中间量：

```
bull_ma = ma5 > ma10 > ma20 > ma60
bear_ma = ma5 < ma10 < ma20 < ma60
```

阶段映射（**按顺序命中即止**）：

```
if channel == 'up':
    if vp == 'healthy_up' or boll_pos in ('touching_upper', 'above_upper'):
        phase = '上涨通道·加速'
    elif vp == 'liar_up_suspect' or (kdj_zone == 'overbought' and vol_ratio < 0.8):
        phase = '上涨通道·滞涨'
    else:
        phase = '上涨通道·延续'
elif channel == 'down':
    if vp == 'panic_sell' or boll_pos in ('touching_lower', 'below_lower'):
        phase = '下跌通道·破位'
    elif kdj_zone == 'oversold' and stabilize.state:
        phase = '下跌通道·筑底'
    else:
        phase = '下跌通道·延续'
else:  # sideways
    phase = '震荡收敛' if boll.squeeze else '震荡'
```

`note` 拼接固定三段：MA 排列（多头排列 / 空头排列 / 均线缠绕）+ 布林位置（中文名）+ 量比
（例：`多头排列 MA5>MA10>MA20>MA60，布林触上轨，量比 1.32`）。

### 6.2 `judge_t_plan` → 什么时候适合做T

**门槛（任一不满足 → `suitable=False`，`unsuitable_signals` 写明原因）**

```
G0 p20 与 p80 必须存在（否则无法计算 T 区间）
   → 不满足：'K 线不足,无法计算 T 区间'
G1 近 5 日平均振幅 ≥ 3.0%
   振幅_i = (high_i - low_i) / close_{i-1} * 100   （取最近 5 根的算术平均）
   → 不满足：'近 5 日平均振幅 {x}% 不足 3%,做 T 赚不到差价'
G2 当日有成交：最新一根 volume > 0
   → 不满足：'今日无成交（停牌或一字板）,无法判断'
G3 非一字板：近 5 日不存在 (high - low) / close < 0.1% 的交易日
   → 不满足：'近 5 日出现一字板,无法做 T'
G4 effective_price ≥ p20 * 0.97（不能远低于 P20 低位带）
   → 不满足：'现价已跌破 P20 低位带 {p20},下行空间不明,不建议做 T'
```

**单边排除（G1~G4 通过后继续判定）**

```
S1 channel == 'up' and bull_ma and 近 3 日累计涨幅 > 5%
   → unsuitable_signals = '单边上涨,做 T 容易做飞,建议持股不动'
S2 channel == 'down' and bear_ma and 近 3 日累计跌幅 > 5%
   → unsuitable_signals = '单边下跌,做 T 越做越低,建议只减不加'
```

**T 区间（取保守边）**

```
t_high = min(近 5 根 K 线 high 的最大值, p80)   # p80 为 None 时取近 5 根 high 最大值
t_low  = max(近 5 根 K 线 low 的最小值, p20)   # p20 为 None 时取近 5 根 low 最小值
amplitude_pct = (t_high - t_low) / effective_price * 100
```

若 `effective_price > p80`：`t_high` 仍按上式计算，但 `sell_trigger` 说明「现价已高于 P80,只做卖出方向」。

**T 区间宽度校验（G5，与 G1 同属「做 T 赚不到差价」语义）**

```
G5 t_high > t_low —— T 区间必须有正宽度
   P20≈P80（横盘分位带退化）或近 5 日波动区间被分位带完全覆盖时，
   t_high == t_low（甚至 t_high < t_low），区间宽为 0，此时给出「区间 0 宽」是无效输出
   → suitable=False：'T 区间无宽度(P20~P80 分位带与近 5 日波动区间无重叠),做 T 无差价'
```

> 说明：G5 在 T 区间计算之后判定，不属于 G0~G4 的前置门槛序列。

**底仓比例**

```
base_position_pct = '≥70%' if bull_ma else '≥50%'
```

**触发条件文案（数字全部取自计算结果）**

```
sell_trigger   = f'冲高至 {t_high:.2f} 元附近且量能未超 5 日均量 1.5 倍时卖出 T 仓'
buyback_trigger= f'回落至 {t_low:.2f} 元附近且缩量企稳（MACD 绿柱不放大）时买回'
```

**止损提示的归属（修正）**

`stop_loss` 文案 `f'底仓跌破 {stop_loss_price:.2f} 元即止损,防止做 T 做飞'` **不属于 TPlan**：
TPlan 的键集合固定为 §5.2 的 9 个键，`unsuitable_signals` 的语义是
「**suitable=False 时**写明为什么不适合做 T」，不得在 suitable=True 时用来装止损提示。

因此约定：

- `judge_t_plan` 在 `suitable=True` 时，`unsuitable_signals` 返回**空字符串**；
- 止损提示由 `build_decision` 的**顶层** `stop_loss` 字段承载（通用持仓止损，非 T 专属）：

  ```python
  stop_loss = {
      "price": stop_loss_price,
      "basis": (f"参考支撑 {support} 元 × 0.97,跌破 {stop_loss_price} 元即止损"
                if support is not None else
                f"跌破 {stop_loss_price} 元即止损"),
  }
  ```

- `stop_loss_price` 缺失时顶层 `stop_loss = None`，此时 TPlan 也不得出现止损文案；
- 「防止做 T 做飞」属于 T 场景话术，不再写入 TPlan；做 T 场景的止损信息由顶层 `stop_loss`
  与 T 卡的 `sell_trigger` 共同承载。

**空仓特例**：`position_status == 'empty'` 时仍返回 `t_plan`，但 `needs_position=True`，
且 `headline` 补充「当前无底仓,做 T 前需先建仓」。

### 6.3 `judge_entry` → 什么时候该买（`position_status == 'empty'`）

三个候选，各自独立判定并给出 `status`：

```
C1 支撑企稳
   条件: indicators.stabilize.state == True 且 stabilize.price != None
   price = stabilize.price
   status = 'now'   if effective_price >= stabilize.price
            'armed' otherwise
   label = '支撑企稳建仓'
   condition = f'回踩 {stabilize.price:.2f} 元不破且 MACD 绿柱缩短时,首仓建仓'

C2 超跌反弹
   条件: indicators.position.risk_band == 'low' 且 indicators.kdj.zone == 'oversold'
   price = indicators.position.p20
   status = 'now'   if kdj.cross == 'golden' 且 effective_price >= p20   # 两个合取项都要成立
            'armed' otherwise                                            # 等金叉 / 等站回 P20
   label = '超跌反弹建仓'
   condition = f'站回 {p20:.2f} 元（P20 低位带）且 KDJ 出金叉时小仓位试仓'
   basis 需写明还差哪一项（未站回 / 未金叉）
```

> **口径修订（2026-10-21，父代理实跑评审）**：原写法 `status = 'now' if kdj.cross == 'golden'`
> **只判了 condition 的一个合取项**（KDJ 金叉），漏判「站回 P20 低位带」。
> 违反 §5 对 `now` 的定义（`now = 此刻条件已满足`），实测产出自相矛盾的卡片：
>
> ```
> 现价 14.35 元
> ▶ 超跌反弹建仓          [现在可做]
>   触发: 站回 15.19 元（P20 低位带）且 KDJ 出金叉时小仓位试仓   ← 现价 14.35 < 15.19
> ```
>
> 现改为**两个合取项都成立才标 `now`**，否则标 `armed` 并在 `basis` 写明还差哪一项。
>
> **触发量影响**（30 只 × 120 交易日 = 3600 个信号日实测）：
> 原口径 entry 触发日 **339** → 修订后 **267**。

C3 突破确认
   条件: effective_price > 最近压力位 且 volume.ratio >= 1.5
   price = 最近压力位（indicators.support_pressure.pressure 中低于现价的最高值）
   status = 'now'    if 突破成立 且 量比 ≥ 1.5
            'armed'  if 尚未突破压力位（理由写明还差多少）
            'blocked' if 突破成立 但 量比 < 1.5（理由必须写明差在哪）
   label = '放量突破追进'
   blocked 理由示例: f'量能仅 {vol_ratio:.2f} 倍,未达 1.5 倍确认标准'
```

> **口径澄清（2026-10-21 修订）**：原写法把「突破成立但量比不足」标成 `armed`，
> 与下方「blocked 理由示例」（量能不足）自相矛盾。
> 现统一为：**突破成立但量比不足 → `blocked`**（不追无量突破，属已否决，理由写明量能差多少）；
> **尚未突破压力位 → `armed`**（等突破，这是可以等待的条件）。
> 实现按此口径（`decision_service.py` 的 `judge_entry` C3 分支）。

**主行动选择**：`status == 'now'` 中按 `C1 > C2 > C3` 取第一个作为主行动（支撑最稳）。
`status == 'blocked'` 的候选全部保留在 `actions` 里（前端折叠展示「为什么不做」）。

#### 6.3.1 下跌通道守卫（2026-10-21 父代理实跑评审新增）

§6.6 把「下跌通道中不要抄底」列为**全局**别动规则，但 C1/C2/C3 原来完全不看通道，
于是卡片会同时出现两条互相打架的指令：

```
● 可以建仓          置信度 中
▶ 超跌反弹建仓      [现在可做]
🚫 别动: 下跌通道中不要抄底
```

股民该听哪条？**全局规则必须赢**。补充条款：

```
当 indicators.channel.state == 'down' 时:
  C1 / C2 / C3 的 status 一律不得为 'now'  →  降级为 'armed'
  并在 basis 追加: '下跌通道中(趋势未修复),按全局「别动」规则不抄底'
```

判据与 §6.6 完全一致（`channel == 'down'`），不多不少；只影响 `status`，不删候选。

> **触发量影响**（30 只 × 120 交易日 = 3600 个信号日实测）：
> 现状 entry 触发日 **339** → C2 口径修订后 **267** → 本守卫后 **158**。
> 仍高于 §10.2 要求的「有效 entry 信号 ≥ 100 条」，闸门不至于因样本量被否。
>
> 通道分布（同一批样本）：sideways 1658 日(46%) / down 1429 日(40%) / up 513 日(14%)。
> 即：**四成的建仓信号原本落在下跌通道里**，这条守卫不是空转。

**仓位建议 `position_pct`**

```
base = 10 if signal.score < 45 else (20 if signal.score < 65 else 30)
if indicators.position.risk_band == 'low': base = min(base + 10, 30)
add_to = min(base * 2, 60)
position_pct = f'首仓 {base}%,站稳 MA20 {ma20:.2f} 元后加至 {add_to}%'
```

**止损 `stop_loss`**：`indicators.position.stop_loss_price`，`basis = f'参考支撑 {support_price:.2f} 元 × 0.97'`

> **支撑窗口口径修订（2026-10-21，父代理实跑评审）**：
> 参考支撑原本取 `min(closes[-20:])`，**含当前这根 K 线**。于是
> `support_price ≤ 当前收盘 × 0.98` → `stop_loss_price ≤ 当前收盘 × 0.9506`，
> 而止损触发条件是 `effective_price < stop_loss_price` ——
> 在**收盘价口径**下该不等式**数学上永不可能成立**。
>
> 实测证据：**15900 个信号日里 `close < stop` 命中 0 次**。
> 后果：止损规则是**死代码**；实盘里它只在「盘中比 20 日收盘最低点还低 5%」的崩盘级行情
> 才可能触发，与「跌破参考支撑就止损」的意图严重不符；
> 且回测里「stop 后 5 日回撤改善」那条闸门**永远无法被评估**。
>
> 现改为取**当前根之前**的 20 根：`min(closes[:-1][-20:]) × 0.98`。
> 语义 = 「跌破**已经确立的**支撑位就止损」，并让实盘与回测口径完全一致：
>
> | 场景 | 支撑取自 | 现价取自 |
> | --- | --- | --- |
> | 实盘 | 前 20 根**已收盘** K 线 | 盘中实时价 |
> | 回测 | 信号日**之前**的 20 根 | 信号日收盘 |
>
> 实测（5 只票 600 个信号日）：命中 **0 次 → 3 次**。
> 实现见 `backend/app/services/ta_service.py` 的 `_position`（注释已写明原因）。

### 6.4 `judge_exit` → 什么时候该卖（`position_status == 'profit'`）

```
E1 分批止盈
   条件: effective_price >= indicators.position.p80
   kind='exit', label='分批止盈', price=p80
   status='now' if 成立 else 'armed'
   condition = f'涨到 {p80:.2f} 元（P80 分位）先减仓 1/3'

E2 高位滞涨
   条件: boll.position in ('touching_upper','above_upper') 且 kdj.zone == 'overbought'
   kind='exit', label='高位滞涨再减', price=effective_price
   status='now' if 成立 else 'armed'
   condition = '布林触上轨且 KDJ 超买,再减仓 1/3'

E3 移动止盈
   条件: 跌破 MA5
   kind='exit', label='移动止盈', price=ma5
   status='armed'（MA5 是动态的，不预设 now）
   condition = f'跌破 MA5 {ma5:.2f} 元清掉剩余仓位'

E4 让利润跑（watch）
   条件: channel=='up' 且 volume_price.direction=='healthy_up' 且 bull_ma
   kind='watch', label='让利润跑', status='now'
   condition = '放量价升且均线多头,持股不动等突破,不急卖'

S 止损
   条件: effective_price < indicators.position.stop_loss_price
   kind='stop', label='止损', price=stop_loss_price, status='now'
   condition = f'跌破 {stop_loss_price:.2f} 元无条件减仓'
```

`S` 优先级最高（见 6.7）。

### 6.5 `judge_loss_plan` → 亏损了怎么办（`position_status == 'loss'`）

```
L1 硬止损
   条件: effective_price < indicators.position.stop_loss_price
   kind='stop', label='无条件止损', price=stop_loss_price, status='now'
   condition = f'已跌破 {stop_loss_price:.2f} 元,无条件止损,不要等回本'

L2 破位减仓
   条件: effective_price < indicators.position.support_price
         且 indicators.volume_price.direction == 'panic_sell'
   kind='exit', label='破位减仓', price=support_price, status='now'
   condition = f'跌破 {support_price:.2f} 元且量增价跌(主力出货),减仓而不是补仓'

L3 解套路径（**kind='watch' 的 action**，label='解套路径'，status='armed'）
   —— 亏损时最该先回答的问题:「还能不能回本?要涨多少?」
   need_pct = (cost_basis - effective_price) / effective_price * 100
   if p80 > cost_basis:
       condition = f'涨到 {p80:.2f} 元可解套(需涨 {need_pct:.1f}%)'
       basis   = [f'持仓成本 {cost_basis:.2f} 元', f'现价 {ep:.2f} 元', f'需涨 {need_pct:.1f}%']
   else:
       condition = f'按 P80 {p80:.2f} 元也回不了本,建议降低预期或换股'
       basis   = [f'持仓成本 {cost_basis:.2f} 元', f'P80 仅 {p80:.2f} 元']
       —— need_pct > 30 且 p80 < cost_basis 时追加 '不建议死扛'
   price = p80
   任一输入缺失(cost_basis / effective_price / p80)→ 不生成这条 action,更不编数字

L4 补仓摊薄
   条件: channel != 'down' 且 indicators.stabilize.state 且 env.market.state != 'cold'
   add_shares = round(shares * 0.3)
   new_cost = (shares * cost_basis + add_shares * effective_price) / (shares + add_shares)
   kind='add', label='补仓摊薄', price=effective_price, status='now'
   condition = f'趋势未破且企稳,可补 {add_shares} 股摊薄成本到 {new_cost:.2f} 元'
   —— 不满足时 status='blocked'，理由写明缺哪一项
```

### 6.6 `judge_do_not` → 什么情况别动（全局）

按下列顺序收集，输出为字符串数组：

```
诱多信号    indicators.liar.bull_liars 非空
           → '出现诱多信号时不要加仓'
涨停/近涨停  当日涨幅 ≥ 9.5%
           涨幅 = (effective_price - prev_close) / prev_close * 100
           prev_close 取 DecisionContext.prev_close（报价昨收,缺失时取 K 线倒数第二根收盘）
           → '涨停或接近涨停时不要追高'
大盘普跌    env.market.down_total > env.market.up_total * 1.5
           → '大盘普跌(跌 {down} 家多于涨 {up} 家 1.5 倍)时不要加仓'
K 线不足    indicators.data_quality.kline_count < 23
           → 'K 线不足 23 根,指标不可靠,先别动手'
单边下跌    channel == 'down'
           → '下跌通道中不要抄底'
无成交      最新一根 volume == 0
           → '今日无成交,无法判断'
```

### 6.7 `derive_verdict` → 单一结论

```
now_kinds = {a.kind for a in actions if a.status == 'now'}
if 'stop' in now_kinds:  verdict = 'sell'
elif 'exit' in now_kinds: verdict = 'reduce'
elif 'entry' in now_kinds: verdict = 'buy'
elif 'add' in now_kinds:   verdict = 'add'
elif position_status in ('profit', 'loss'): verdict = 'hold'
else: verdict = 'wait'
```

**置信度**

```
base = indicators.signal.confidence          # 'high' | 'medium' | 'low'
if degraded 非空 and base == 'high': base = 'medium'
confidence = base
```

**角色 `role`**

```
empty  → '建仓参考'
profit → '止盈参考'
loss   → '解套参考'
```

---

### 6.8 五个补维度（v0.10）

> **只增信息，不改既有 verdict 逻辑与阈值。** 这五个维度不参与 `derive_verdict`，
> 不改变任何 `now`/`armed`/`blocked` 判定，不改 §6.1~§6.7 的任何阈值。
> 任一输入缺失 → 对应字段 `None` + 写进 `degraded`，**绝不编数字**。

#### 6.8.1 `judge_cost_anchor` → 成本锚点

```
输入：ctx.cost_basis / effective_price(ctx) / indicators.position.p80 / indicators.position.stop_loss_price
pnl_pct             = (ep - cost_basis) / cost_basis * 100          # 浮盈(+)/浮亏(-)
break_even_gap_pct  = (cost_basis - ep) / ep * 100   仅浮亏时给；浮盈时 None
distance_to_stop_pct= (stop_loss_price - ep) / ep * 100              # 负 = 已在止损下方
distance_to_target_pct = (p80 - ep) / ep * 100                      # 浮盈时给
risk_reward         = distance_to_target_pct / abs(distance_to_stop_pct)   # 分母为 0 → None
```

#### 6.8.2 `judge_time_window` → 时间窗口

```
输入：ctx.holding_days（自然日，由 IO 层算好注入；判定层不做日历计算）
      ctx.holding_days_source（'transactions' | 'snapshot'，IO 层一并注入）
HOLD_DAYS_LIMIT = 20（自然日，约合 14 个交易日）
overdue     = holding_days > HOLD_DAYS_LIMIT
overdue_text= f'已超 {HOLD_DAYS_LIMIT} 天阈值 {holding_days - HOLD_DAYS_LIMIT} 天' if overdue else None
```

**起点来源决定文案措辞（不得含糊）**：

| `source` | 起点含义 | `note` 文案 | 六格「时间」格文案 |
|---|---|---|---|
| `'transactions'` | 该票**最早一笔流水**的 `trade_date`（真实起点可追溯） | `已持有 N 天（自然日，起点=最早一笔流水）` | `已持有 N 天` |
| `'snapshot'` | `positions.created_at`（**快照导入日，真实建仓日未知**） | `自纳入本系统起 N 天（自然日，真实建仓日未知）` | `自纳入本系统起 N 天（建仓日未知）` |

> 来源缺失（`None`）时**按保守口径处理**（等同 `snapshot`）：宁可说"不知道"，不得把"不知道"说成"已持有 N 天"。

**超期必须出文案**：`overdue` 只是布尔值，真正要提示的是 `overdue_text`；
六格「时间」格要带上超期信号（超期是行动信息，不能只躺在折叠区）。

**取数口径（IO 层，优先级从高到低）**：
1. `transactions` 表该票**最早 `trade_date`**（活链起点，最准）→ `source='transactions'`；
2. `positions.created_at` 的日期（**快照导入日，不是真实建仓日**）→ `source='snapshot'`；
3. 都拿不到 → `holding_days = None` + degraded。

> ⚠️ `Position` 数据类**没有** `base_date` 字段——`base_date` 只是导入接口的入参（决定吸收哪些流水），**从未落库**。
> 实现不得假设 `position.base_date` 存在。

#### 6.8.3 `judge_cost_effect` → 费用影响（含费用口径约定）

**费用口径 `fee_basis`（三态，全项目统一）**：

| 取值 | 条件 | 说明 |
|---|---|---|
| `'configured'` | 费用设置 `enabled=true` | 按用户自己的费率算 |
| `'default_estimate'` | 费用设置 `enabled=false`（**当前默认态**） | 按**系统默认档**估算（佣金万 2.5 / 最低 5 元 / 印花税千 0.5 / 过户费万 0.1），并在 degraded 写明「费用设置未启用，费用按默认档估算」 |
| `None` | 费用档读取失败 | 该维度整体 None + degraded |

> 默认档是**系统常量、来源可追溯**，不属于「编造数字」。
> 若不启用估算，费用维度与网格净收益将对当前用户**完全不显示数字**（网格会因此无法给出结论）。

```
roundtrip_fee_pct = 2×commission_rate + stamp_tax_rate + 2×transfer_fee_rate
  股票口径 = 0.025%×2 + 0.05% + 0.001%×2 = 0.102%
  ETF  口径 = 0.025%×2 + 0    + 0          = 0.05%
spread_pct = t_plan.amplitude_pct（做 T 区间振幅 %）
worth_it   = spread_pct >= T_SPREAD_MIN_MULTIPLE(2) × roundtrip_fee_pct
```

#### 6.8.4 `judge_instrument_rule` → 品种规则

```
ETF ：notes += 'ETF 无涨跌幅限制' + '免印花税、免过户费（只收佣金）'
      t0=True  → notes += '当日可回转（T+0）'
      t0=False → notes += 'T+1，当日买入当日不可卖出'
股票：notes += '股票有涨跌幅限制（±10%）' + 'T+1，当日买入当日不可卖出'
```

#### 6.8.5 `judge_concentration` → 集中度

```
输入：ctx.position_share_pct（该票持仓成本 ÷ 全量持仓成本合计 × 100，IO 层算好）
cost_share_pct <  CONCENTRATION_WARN_PCT(30)   → level='low'
cost_share_pct >= CONCENTRATION_WARN_PCT(30)   → level='warn'
cost_share_pct >= CONCENTRATION_STRONG_PCT(50) → level='strong'
```

> 口径取**成本占比**（而非市值占比）：只多 1 次本地 DB 查询，不额外拉全量行情。

### 6.9 `judge_grid_plan` → 网格交易配置建议（v0.10）

**定位**：网格是**长期挂单式策略**，与「做 T」（盘中手动来回）**互为替代关系**，不是叠加。
判定必须比 `judge_t_plan` **更保守**——`judge_t_plan` 只看均线排列 + 3 日涨跌，
而网格在单边市里会越买越多直到资金耗尽。

**新增阈值常量**：

```
GRID_WINDOW = 20                  # 网格观察窗口（根）
GRID_MIN_AMPLITUDE_PCT = 3.0      # 近 20 日平均振幅下限
GRID_MIN_SPAN_PCT = 8.0           # 区间宽度下限（相对现价）
GRID_TARGET_STEP_PCT = 2.0        # 目标步长
GRID_MAX_GRIDS = 10               # 最多档数
GRID_MIN_PROFIT_MULTIPLE = 2      # 单格净收益需 ≥ 2× 往返费用率
GRID_LOT_SIZE = 100               # 1 手 = 100 股（A股 / 场内 ETF / LOF 均是）
```

**判定链（顺序即优先级，先否决）**：

| # | 判据 | 不通过 → `unsuitable_signals` |
|---|---|---|
| G0 | K 线 ≥ `GRID_WINDOW` 根 且 `p20`/`p80` 齐备 且 现价可得 | `K 线不足，无法计算网格区间` |
| G1 | `channel.state` 既不是 `'up'` 也不是 `'down'` | 下行 → `下跌通道中不要布网格：越买越套`；上行 → `上涨通道中布网格会卖飞底仓` |
| G2 | 近 20 日平均振幅 ≥ `GRID_MIN_AMPLITUDE_PCT` | `近 20 日平均振幅 {x}% 不足 3%，网格抓不到差价` |
| G3 | `span_pct ≥ GRID_MIN_SPAN_PCT` | `区间宽度 {x}% 不足 8%，放不下有意义的网格` |
| G4 | 现价在区间内（容差 1 格） | `现价已跌破网格下沿 {x}，布网格等于接飞刀` |
| G5 | 持仓 ≥ `GRID_LOT_SIZE` | `当前无底仓，网格需先建底仓` |
| G6 | 步长与费用：费率口径 + **金额口径**（扣最低佣金后 > 0） | `每格毛收益 {x} 元，扣手续费 {y} 元后为负，网格不划算` |
| G7 | 资金：`cash_available ≥ cash_needed` → `mode='add'`，否则 `mode='base'` | **不否决**，降级为底仓模式 + 注明「现金不足，只能做底仓高抛低吸」 |
| G8 | 集中度：`position_share_pct ≥ CONCENTRATION_STRONG_PCT(50)` → 禁止 `mode='add'` | **不否决**，强制 `mode='base'` + 警示「该标的已占持仓成本 {x}%，加仓会放大单一暴露」 |

**计算细节**：

```
lo20 / hi20   = 近 20 根 K 线的最低 low / 最高 high
range_low     = max(lo20, p20)          # 保守边（与 t_plan 同思路）
range_high    = min(hi20, p80)
span_pct      = (range_high - range_low) / ep * 100
step_pct      = max(GRID_TARGET_STEP_PCT, round(GRID_MIN_PROFIT_MULTIPLE × roundtrip_fee_pct, 2))
                step_pct > span_pct → 不适合（区间放不下一个步长）
grids         = min(GRID_MAX_GRIDS, floor(span_pct / step_pct))
step_price    = ep × step_pct / 100
shares_per_grid = GRID_LOT_SIZE（100 股）
capital_per_grid = shares_per_grid × ep          # 每格涉及的资金（一手金额），**不是**每格利润
cash_needed   = ceil(grids / 2) × capital_per_grid      # 最坏情况：跌到下沿时累计买入档数
net_step_pct  = step_pct - roundtrip_fee_pct
毛收益         = shares_per_grid × step_price           # 卖一档买回一档的价差 × 股数
费用           = buy_fee(shares, price) + sell_fee(shares, price)      # 含最低佣金
net_profit_per_grid = 毛收益 - 费用       # ≤ 0 → G6 不通过
```

> ⚠️ **口径提醒**：`capital_per_grid`（一手金额）与 `gross_profit`（每格利润）是两个数。
> 把两者混为一谈会让「所需资金」和「每格净收益」同时算错 ——
> 例如 25 元股价、2% 步长、100 股：一手金额 2516 元，每格毛收益 50.3 元，
> 扣掉 10 元最低佣金后净赚 40.3 元；按「一手金额 = 毛收益」算会得出「净亏 9 元」的荒谬结论。

**`mode` 语义**：
- `'add'` = 加仓网格：每跌一档买一档，需要额外现金（`cash_needed`）；
- `'base'` = 底仓高抛低吸：零额外现金，卖出档数 ≤ 底仓手数；
- `None` = 不适用（`suitable=false`）。

**`replace_t_plan` 与互斥文案**：

```
replace_t_plan = grid.suitable AND t_plan.suitable
  → reason  = '震荡市建议以网格为主（不用盯盘），手动做 T 与网格互斥，择一执行'
grid.suitable AND NOT t_plan.suitable
  → reason  = '震荡市建议以网格为主（不用盯盘）；当前手动做 T 条件不满足'
```

**`risk` 文案（必须含失效条件与最坏风险）**：

```
跌破 {range_low} 元（区间下沿）网格失效，按止损离场，不要继续接；
突破 {range_high} 元只是少赚，不损；
单边下行时网格会越买越多直到资金耗尽 —— 这是网格最大的风险。
```

**不承诺收益**：只给「每格净收益 X 元 / 需要资金 Y 元 / 区间 Z~W 元」，
不给目标价、不给「预计赚多少」（沿用 §10.4 口径）。

### 6.10 「操作建议」六格 `suggestions`（v0.10）

**六格固定、值可为 `None`**（`None` = 该维度数据不足，前端**不渲染该格**，不显示空框）。

| 格 | 标签 | 取值来源（**全部来自既有判定结果，不新算价**） |
|---|---|---|
| `price` | 价位 | `actions` 中第一条 `status ∈ {now, armed}` 的 `condition` + `price` |
| `stop_loss` | 止损 | 既有 `stop_loss.price` + §6.8.1 的 `distance_to_stop_pct` |
| `position` | 仓位 | 既有 `position_pct` |
| `trigger` | 触发 | 第一条 `status == 'armed'` 的 `condition` |
| `timing` | 时间 | §6.8.2 `time_window` + §6.8.1 `break_even_gap_pct` |
| `avoid` | 不动 | 既有 `do_not`（多条用 `·` 连接） |

> 「建议」区与既有「行动清单」「做 T 块」「网格块」是**同一套数字的不同切面**，不得互相矛盾：
> 六格里的价位/止损必须与 `actions`、`stop_loss`、`t_plan`、`grid_plan` 完全一致（同一事实源）。

---

## 七、市场环境规格

### 7.1 大盘 `market`

数据源：`fetch_market_sentiment()`（全市场 5568 只，60s 缓存）+ `get_market_overview()`（取上证指数真实涨跌幅）。

```
up_total, down_total, flat_total, limit_up, limit_down, sample_size 取自 sentiment 接口
change_pct   = get_market_overview() 的 indexes[0].change_pct（第一个非空者）
state:
  up_total > down_total * 1.5                        → 'warm'
  down_total > up_total * 1.5                        → 'cold'
  否则                                                → 'neutral'
summary = f'大盘偏暖/偏冷/分化:涨 {up_total} / 跌 {down_total},涨停 {limit_up} / 跌停 {limit_down}'
```

### 7.2 行业 `sector`

> ⚠️ **两套行业命名口径必须分清**（实现时的头号坑）：
>
> | 口径 | 形态 | 适用 |
> | --- | --- | --- |
> | **证监会行业名**（离线表 baostock） | `C39计算机、通信和其他电子设备制造业` | `get_sector_kline()` 行业等权 K 线 |
> | **新浪行业板块名** | `电子元件` | `get_sector_fund_flow()` 板块资金流 |
>
> `resolve_industry()` 优先返回证监会口径（离线表命中时），
> 因此**用它的返回值去匹配板块资金流通常落空** —— 落空就如实降级，**不得编造**。

数据源：`resolve_industry(code)` → 行业名；`get_sector_kline(industry)` → 行业等权 K 线（`items` 只有 `date`/`close`）；
`get_sector_fund_flow(fenlei=1)` → 新浪行业板块资金流排行。

```
change_pct    = 行业等权 K 线最后一根 close / 倒数第二根 close - 1
vs_market_pct = change_pct - 大盘 change_pct
fund_net_yi   = 板块资金流排行中**同名**板块的 netamount_yi（找不到 → None）
fund_direction= 'in'  if fund_net_yi > 0 / 'out' if < 0 / None if 无

leading       = 排行中 netamount_yi 为正的前 3 个板块 [{name, net_yi}]
                （该口径**恒可用**,回答「今天钱在往哪走」,不依赖行业名匹配）
                ⚠️ 单位:`netamount_yi` / `inamount_yi` / `outamount_yi` 的新浪原始值是**元**,
                由 `sector_fund_flow_service` 在源头换算成**亿**;`turnover_yi` 原始就是亿。
                （2026-10-21 修正:此前三个字段原样透传元值却叫 `_yi`，
                导致下游把 51.46 亿显示成 5146220275.88 亿、「≥1 亿」阈值恒成立。）

state:
  change_pct > 1   → 'leading'
  change_pct > 0   → 'warm'
  change_pct > -1  → 'lagging'
  else             → 'cold'
  若 fund_direction == 'out' → 降一级（leading→warm, warm→lagging, lagging→cold）
```

### 7.3 本股资金流 `stock_flow`

数据源：`list_recent(code, limit=1)`。

```
direction = 'in' | 'out' | None
amount_wan= 数值 | None
category  = 'large' | 'medium' | 'small' | None
```

### 7.4 相对强弱 `relative`

```
vs_sector_pct = 个股涨幅 - change_pct
vs_market_pct = 个股涨幅 - 大盘指数涨幅
```

### 7.5 降级纪律（铁律）

| 子项失败 | 行为 |
| --- | --- |
| 行业归属查不到 | `industry=None`，summary 写「行业归属未知」，**不编造** |
| 行业 K 线拉不到 | `change_pct=None`，只给资金流部分，summary 说明缺哪项 |
| 板块资金流无该板块 | `fund_net_yi=None`，`fund_direction=None` |
| 本股无资金流记录 | `direction=None`，summary 写「暂无资金流数据」 |
| 全市场情绪失败 | `market.state=None`，summary 写「大盘数据暂不可用」 |
| 个别资金流拉取抛错 | 捕获后置 None，**绝不整体失败** |

任一子项失败 → 对应字段为 None + 写入 `degraded` 列表 + 前端显示「暂无数据」。

---

## 八、API 规格

```
GET /api/stock/{stock_code}/decision
```

**成功 200**

```jsonc
{
  "decision": { /* §5.2 全量结构,含 data_quality.degraded */ }
}
```

降级信息只保留 `decision.data_quality.degraded` 一处来源，不做顶层重复。

**错误**

| 码 | 条件 | 含义 |
| --- | --- | --- |
| 422 | `stock_code` 格式非法 | `{"code":"INVALID_STOCK_CODE","message":"代码格式应为 6 位数字 + .SH/.SZ"}`（沿用 `stock.py` 既有 `_check_code`） |
| 502 | K 线完全不可用 | `{"code":"DATA_SOURCE_UNAVAILABLE","message":"..."}`（沿用 `_load_klines`） |

**特性**

- 纯确定性：**不调用 LLM**，不产生 LLM 费用。
- 无副作用、不落库。
- 可加 60s 进程内内存缓存（按 stock_code），首版可不加。
- **v0.10 增补**：`/decision` 响应新增 §6.8 五个维度、§6.9 `grid_plan`、§6.10 `suggestions` 六格、
  以及规则白话 `advice`（零 LLM）。**全部为纯增量，旧字段语义不变。**

### 8.2 `GET /api/stock/{stock_code}/decision-advice`（v0.10 新增）

**用途**：显式触发的 AI 白话生成（**按钮触发**，不在决策卡首屏自动烧 token）。

```
GET /api/stock/{stock_code}/decision-advice
```

**成功 200**

```jsonc
{
  "advice": {
    "headline": "一句话结论（≤120 字）",
    "bullets": ["要点 1", "要点 2", "要点 3"],
    "source": "llm" | "rule",     // LLM 不可用 → 'rule'（规则白话兜底）
    "generated_at": "2026-10-25T16:00:00"
  },
  "degraded": []
}
```

**失败语义**

| 情况 | 行为 |
| --- | --- |
| LLM 未配置 / 超时 / 解析失败 | `source='rule'`，用规则文案，**仍返回 200** |
| K 线不可用 | 502 `DATA_SOURCE_UNAVAILABLE`（沿用既有语义） |
| 决策本身不可用 | 502 同上 |

**缓存**：进程内**当日缓存**，key = `stock_code + 日期 + headline 摘要`，跨日自动失效。
避免用户在多只票之间来回切换时反复烧 token。

### 8.3 `GET /api/stock/{stock_code}/analysis`（v0.10 变更）

- 响应结构**不变**；AI 不可用时 `ai=null` 行为不变。
- **变更**：`user_msg` 追加 §5.4 事实包 JSON；`ANALYSIS_SYSTEM` 增加硬规则
  「以下数字是唯一真相源，必须原样引用，不得改写 / 另算 / 补充未列出的价位；缺字段写『暂无』」。
- 该端点已有 klines / quote / position，**复用即可，不增加网络 IO**。
- **已知时间差**：analysis 有当日缓存（`daily_analyses`），缓存里的白话对应**当时**的决策数字，
  盘中价格变了会与实时决策卡不一致 →
  - 六格与网格块**永远以实时决策为准**；
  - AI 白话行标注「AI 解读 · 数据时间 {latest_kline_date}」；
  - 规则兜底文案永远与当前决策一致。

---

## 九、前端规格

### 9.1 新组件

`frontend/src/components/desk/DecisionCard.tsx`

**位置**：渲染在 `frontend/src/components/desk/DecisionColumn.tsx` 的**最顶部**（持仓概览之上）——
用户问的第一个问题是「我现在该干什么」，所以它必须第一眼可见。

**三种状态**

| 状态 | 表现 |
| --- | --- |
| loading | 骨架屏（保持与最终卡同高，避免布局跳动） |
| ready | 渲染决策卡 |
| error | 显示「决策暂不可用」+ 降级原因，**不空白**（遵循「不要做降级式 UI」：模块完整渲染，只是内部无数据） |

**渲染规则**

```
┌───────────────────────────────────────────┐
│ ● 空仓 · 建仓参考            置信度 中     │
│ 现在该做什么:等支撑企稳再进,别追高          │
├───────────────────────────────────────────┤
│ ▶ 支撑企稳建仓              [待触发]        │
│   触发: 回踩 13.61 元不破且 MACD 绿柱缩短  │
│   价位: 13.61 元      止损: 13.20 元      │
│   依据: 近20日支撑 13.61 / 量比 0.80 缩量  │
│                                            │
│ ▶ 放量突破追进              [已否决]        │
│   否决理由: 量能仅 0.90 倍,未达 1.5 倍    │
├───────────────────────────────────────────┤
│ 仓位: 首仓 20%,站稳 MA20 14.35 后加至 50% │
│ 做T: 可做 · 区间 14.20~15.19(振幅 7.0%)   │
│   上沿减 / 下沿补,底仓留 ≥50%              │
├───────────────────────────────────────────┤
│ 🚫 别动: 出现诱多信号时不要加仓              │
│ 市场: 大盘偏暖(涨3777/跌1667)             │
│       C39 行业 +2.14%,主力净流入 12.3 亿   │
└───────────────────────────────────────────┘
```

- 只直接展示 `status ∈ {now, armed}` 的 action。
- `status == 'blocked'` 的折叠在「为什么不做」里（默认收起，可展开）。
- `t_plan` 为 `None` 或 `suitable=False` 时也要显示（写明不适合的原因），不隐藏。
- `market_env` 各子项为 `None` 时显示「暂无数据」，不显示空白格。

### 9.2 数据获取

`frontend/src/app/(app)/page.tsx`：

- 选中股票时**并发**请求 `/stock/{code}/decision`，与现有 analysis 请求并行，互不阻塞。
- 决策卡**不依赖**「开始分析」按钮；LLM 解读仍是可选的白话层。
- 若两者结论冲突，**以决策卡为准**，LLM 区域标注「AI 白话参考」。

### 9.3 「操作建议」区（v0.10）

**位置**：决策卡内，**「结论头」之下、「行动清单」之上**。
读卡顺序是「先结论 → 再建议 → 再细节」。

```
┌───────────────────────────────────────────────┐
│ 操作建议  [解套参考]        确定性引擎 · 实时   │
├───────────────────────────────────────────────┤
│ 价位   涨到 19.16 元可解套(需涨 5.1%)         │
│ 止损   13.20 元(距现价 -18.5%)                │
│ 仓位   解套优先,减仓不追补                     │
│ 触发   涨到 19.16 元(P80 分位)                │
│ 时间   已持有 23 天,回本还需 +5.1%            │
│ 不动   下跌通道中不要抄底                      │
├───────────────────────────────────────────────┤
│ 网格   [不建议]                                │
│   下跌通道中不要布网格:越买越套                │
├───────────────────────────────────────────────┤
│ AI 解读 · 数据时间 2026-10-24                  │
│   现价 16.19 元,离回本还差 5.1%,别急着补仓…    │
│                              [AI 写白话]       │
├───────────────────────────────────────────────┤
│ ▸ 更多维度(成本锚点/时间窗口/费用影响/…)        │
└───────────────────────────────────────────────┘
```

**渲染规则**

- 六格：`suggestions` 中值为 `None` 的格子**不渲染**（不显示空框）；有值才显示。
- **网格子块**：紧跟六格之下、**做 T 块之上**（先看"要不要布网格"，再看"要不要手动做 T"）。
  - `suitable=true` → 徽章「可配置」，并标出模式（`加仓模式` / `底仓模式`）、区间、格数、
    每格净收益、需资金、失效条件；
  - `suitable=false` → 徽章「不建议」+ `unsuitable_signals` 原文，**不隐藏、不空白**。
  - `replace_t_plan=true` → 做 T 块追加一行「已建议配置网格，二者择一，勿同时执行」。
- 白话行：优先 `analysis.ai.advice.rationale`（标注来源与「数据时间」），
  否则用 `decision.advice`（规则文案，零延迟）。
- 「AI 写白话」按钮：调 `/decision-advice`（**按钮触发，显式烧 token**）；
  失败则 toast 提示并保留规则文案。
- 五个新维度放在**默认收起的折叠区**，避免决策卡变啰嗦。

### 9.4 AI 解读区收敛（v0.10）

`frontend/src/components/advice/AnalysisPanel.tsx` 的 `OperationAdviceBlock`：

- **移除**六格（价位/止损/仓位/触发/时间/不动）与 `t_strategy` 区块 → 已上移到决策卡，
  避免同一屏出现**两套说法**。
- **保留** `rationale`（AI 白话）与风险提示；`rationale` 标注「与操作决策同源」。

### 9.5 并发与降级（v0.10）

- `/decision-advice` 是独立请求 → 必须复用 `page.tsx` 现有的**请求序号守卫**
  （切票时旧响应不得贴到新票）。
- 降级链：LLM 白话 → 规则白话 → 空（仅当决策本身不可用，此时卡片显示既有错误态）。
- **不做**：不改 `ta_service` 指标算法；不改 `derive_verdict` 判定顺序；不改既有阈值。

---

## 十、可信度闸门（上线判据）

单测只能证明「代码按规则跑」，不能证明「规则有用」。**必须用项目已有的回测引擎对历史数据验证**。

### 10.1 回测方法

- 样本：≥ 30 只股票 × ≥ 120 个交易日（从现有 `kline_cache` 取）。
- 逐日推进：每个交易日只用**当日可见**的数据（严格无前视偏差）跑一遍决策器。
- 记录每个 `entry` / `exit` / `stop` 信号。

### 10.1.1 指标口径（避免歧义）

```
买入价   = 信号日**次日**的开盘价（无前视：信号在收盘后产生，最早次日开盘成交）
持有期   = 买入日 起 10 个交易日（stop 信号用 5 个交易日作为观察窗）
胜       = 持有期内最高收盘价 > 买入价 × 1.02（+2%）
平均收益 = 第 10 个交易日收盘价 / 买入价 - 1
最大回撤 = 持有期内 (收盘价序列的最低点 / 买入价 - 1)
```

> **基准口径修订（2026-10-21，父代理回测评审）**：原写法
> 「基准 = 同一天同一只票『次日开盘买入并持有 10 日』的同样口径」**在数学上恒等于信号自身**——
> 信号当天的买入交易**就是**基准那一笔交易，两者相减必然是 0，
> 于是「entry 超额收益」这条门槛会**结构性恒为 false**，闸门形同虚设。
> 同理，exit 的两臂若用同一窗口，「exit 后回撤改善」也恒为 0。
>
> 修订为**无条件基准**：
>
> ```
> 基准(无操作条件基准) = 同一只票在回测窗口内**所有可回测日**的
>                        「次日开盘买入并持有 W 日」同样口径的**平均值**
>                        （W = 10 日 / 5 日各算一套）
> ```
>
> 这才是「随便哪天买并持有」的可比基准，也是「择时有没有价值」唯一能回答的问题。
>
> **两臂可比性铁律**：信号臂与基准臂必须**同一参考价、同一观察窗口**。
> 否则「改善」量到的是窗口长度差，而不是信号质量 ——
> 例如 stop 用 5 日窗、基准用 10 日窗，5 日窗的最低点天然 ≥ 10 日窗的最低点，
> 「改善」会凭空为正，门槛变成假通过。
>
> **改善的方向**：一律写成 `基准 − 信号`，**正值 = 信号情形比常态更好**。
>
> | 信号 | 观察窗 W | 信号臂 | 基准臂 | 指标 |
> | --- | --- | --- | --- | --- |
> | `entry` | 10 日 | 次日开盘买入持有 10 日 → 收益/胜率/回撤 | 同窗口无条件平均 | 超额收益 = 信号均值 − 无条件均值；胜率 = 信号胜率 |
> | `exit` | 10 日 | 信号日之后 10 日的实测回撤（= 按信号卖出所规避的回撤） | 同窗口无条件平均回撤 | 改善 = 无条件回撤 − 信号回撤 |
> | `stop` | 5 日 | 信号日之后 5 日的实测回撤 | 同窗口无条件平均回撤 | 改善 = 无条件回撤 − 信号回撤 |
>
> 语义说明：exit/stop 的「按信号做」= 你在信号次日开盘离场，**规避了**之后窗口内的回撤。
> 所以「改善 = 无条件回撤 − 信号回撤」为正，等价于「这批信号发出后，股价确实比常态跌得更深」
> → 止盈/止损信号有择时价值；为负则说明信号发早了（卖在反弹前），这批信号没有价值。

### 10.2 验收门槛（**先定，事后不得下调**）

| 指标 | 门槛 |
| --- | --- |
| `entry` 信号后 10 日胜率 | ≥ 53%（对比基准 50%） |
| `entry` 信号后 10 日平均收益 | > 买入并持有基准 + 1.0% |
| `stop` 信号后 5 日最大回撤 | 比「不止损」基准改善 ≥ 1.5% |
| `exit` 信号后 10 日最大回撤 | 比「不止盈」基准改善 ≥ 1.0% |
| 样本池规模 | ≥ 30 只股票（不足则结论无效） |
| 样本池回测窗口 | ≥ 120 个交易日 / 只（不足则结论无效） |
| 有效 `entry` 信号数 | ≥ 100 条（不足则结论无效） |

> **口径澄清（2026-10-21 修订，非下调）**：原表述「样本量 ≥ 30 只 × 120 交易日」是
> **样本池规模**的定义（30 只股票 × 每只 120 个交易日的回测窗口），**不是「3600 条信号」**。
> 实施时把它拆成可执行的三条：样本池股票数、每只的回测窗口长度、以及有效 entry 信号条数下限。
> 三条与原门槛同向、只多不少，**没有降低任何要求**。
>
> 另：`stop` 的回撤观察窗是 **5 日**（`exit` 是 10 日）；
> 按 §10.1.1 的**两臂可比性铁律**，基准臂必须用**同一窗口**的无条件均值
> （stop 用 5 日、exit 用 10 日），否则「改善」量到的是窗口长度差而非信号质量。
> 门槛数字本身**未做任何调整**。
>
> **「基准」= 无条件基准**（同票、同窗口、全部可回测日的均值），
> 不是「信号当天的同一笔交易」—— 后者会让改善恒等于 0、门槛形同虚设。
> 详见 §10.1.1 的「基准口径修订」。

### 10.3 不达标怎么办

调整阈值 / 权重 → 重跑 → 直至达标或明确判定「此规则无价值」并从设计中移除。
**不得下调门槛，不得跳过回测直接上线。**

### 10.4 回测结论记录（2026-10-21 · 闸门未全过）

> **样本**：60 只 × 120 个交易日 = 7200 个可回测日（新浪日 K，样本期 2026-01-05 ~ 2026-10-20，每只 190 根，0 只跳过）
> **配置**：**现网规则**（未收紧），entry 有效信号 308 条
> **完整报告**：`docs/analysis/decision-backtest-report.md`（含 5 轮迭代记录、逐票明细、量比阈值全量扫描）

**7 条闸门：5 通过 / 2 未过。**

| # | 闸门 | target | actual | 结果 |
| --- | --- | --- | --- | --- |
| 1 | 样本池股票数 | ≥ 30 只 | 60 | ✅ |
| 2 | 样本池回测窗口 | ≥ 120 交易日/只 | 120 | ✅ |
| 3 | 有效 entry 信号数 | ≥ 100 条 | 308 | ✅ |
| 4 | entry 后 10 日胜率 | ≥ 53% | **53.90%**（基准 52.74%） | ✅ |
| 5 | entry 超额收益 | > 基准 + 1.0% | **−0.76%**（信号 −1.43% / 基准 −0.67%） | ❌ |
| 6 | exit 后 10 日回撤改善 | ≥ 1.0% | **+1.84%**（n=945） | ✅ |
| 7 | stop 后 5 日回撤改善 | ≥ 1.5% | **+0.17%**（n=30） | ❌ |

**§10.3 的明确判定（限定在本样本池 + 本样本期 + 现有 entry 条件）：**

1. **entry 建仓信号：胜率型有效、收益型无效。** 5 轮迭代中胜率优势全部为正（+1.16 ~ +2.16pp），
   但 10 日平均收益**始终低于**「随便哪天买并持有」—— 典型的「赢小钱、亏大钱」结构。
   → **产品定位收敛为「胜率型概率提示」**：卡面只讲条件、价位与依据数字，
   **不承诺收益**，不把「条件已满足」表述成「此时买入会赚钱」。
2. **止盈（exit）：通过闸门**，回撤改善 +1.84%（样本充分，n=945）→ 保留。
3. **止损（stop）：样本不足（n=30），不下结论。** 既不判有效也不判无效；
   60 只池观测 +0.17%、30 只池观测 −0.14%，方向都不一致 —— 需要更大样本池或更长窗口才能判定。
4. **两条 entry 闸门在本样本上互斥**：量比阈值在 [0, 2.0] 全区间扫描，
   **没有任何取值**能同时满足「有效信号 ≥ 100 条」与「超额收益 > +1.0%」
   （唯一正超额的是 `量比 ≥ 1.8`，+2.25%，但 n=26 只有闸门下限的 1/4）。
   → 这不是「还没调到位」，而是**这批 entry 信号本身没有收益方向的择时能力**。

**未采纳的收紧（重要决策）**：回测侧的「C1 量比 ≥ 1.5 放量确认」**没有落到产品代码**。
理由两条 —— ① 该配置下 entry 信号 n=53 < 100，按 §10.2「不足则结论无效」其结论不成立，
拿一个未成立的结论去改线上规则属于本末倒置；② 它会把线上建仓触发率从 4.28% 压到 0.71%，
用明显的可用性损失换一个未经验证的收益。
旋钮保留在 `backend/app/services/decision_backtest.py:EntryRule`，供日后扩样本后复验。

**本结论的固有局限**：无条件基准**无法把「择时能力」与「市场状态」分离** ——
样本期恰逢大盘回落（基准 10 日平均收益 −0.67%），单边下跌期会压缩所有规则的超额、
普涨期会放大所有规则的超额。因此「未通过」= **在本样本池本样本期未通过**，
不等于规则在任何市场状态下都无价值；若要把 +1.16pp 的胜率优势当作可依赖的产品结论，
需要**跨市场状态的分段回测**（超出 §10.3 的规则参数调整范围）。

**口径纪律（本轮修正过的三处，全部有单测钉死）**：

- 基准 = **无条件基准**（同票、同窗口、全部可回测日均值），不是「信号当天的同一笔交易」
  —— 后者会让「改善 / 超额」恒等于 0，闸门形同虚设。
- 两臂可比性：信号臂与基准臂**同一参考价、同一观察窗口**（stop 两臂都用 5 日窗）；
  改善方向一律 `基准 − 信号`。
- 无前视：信号日 i 的判定器只喂 `klines[: i+1]`，前向收益用 `klines[i+1].open` 买入。

---

## 十一、测试策略

| 文件 | 覆盖 |
| --- | --- |
| `backend/tests/test_decision_service.py` | 每个判定器的命中 / 不命中边界（合成 K 线构造）；`derive_verdict` 映射表全覆盖；**数字可追溯不变量**（每个 `action.price` 必须能在输入中找到来源，或是输入两个数的显式运算结果） |
| `backend/tests/test_market_context_service.py` | 各数据源 mock；验证降级不崩、不编数字、`degraded` 正确记录 |
| `backend/tests/test_decision_api.py` | 端点结构完整性；400 / 503 错误码 |
| `backend/tests/test_decision_backtest.py` | 回测脚本自身正确性（小样本 sanity：合成数据下方向可预期）；7 条闸门数字与 §10.2 逐条钉死 |
| `backend/tests/test_decision_backtest_invariants.py` | **回测口径不变量**：无条件基准覆盖全部可回测日（不是只有信号日）；stop 基准臂用 5 日窗；改善方向 = 基准 − 信号。这三条一旦被改坏，闸门会安静地给出漂亮但无意义的结论 |

### 零编造不变量（必须写进单测）

1. `action.price` ∈ {`indicators` 中的值, `current_price`, `cost_basis`, 由上述值的显式四则运算结果}。
2. 每条 `basis` 至少含一个输入里出现过的具体数字。
3. `summary` 里的每个数字都能追溯到输入。
4. 任一数据源返回 None 时，对应输出为 None，**不是 0、不是空串、不是猜测值**。

---

## 十二、风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 规则拍脑袋、没有实际价值 | §10 回测闸门；不达标不上线 |
| 右栏信息过载 | 只直显 `now`/`armed`；`blocked` 折叠；决策卡整体可折叠 |
| 数据源缺失 / 抖动 | 全链路降级 + `degraded` 标注 + 前端「暂无数据」，绝不编数字 |
| 盘中实时价缺失 | 用 `latest_close` 计算，并在 UI 标注「按收盘价计算」 |
| 确定性卡与 LLM 解读冲突 | 以确定性卡为准，LLM 降级为「白话参考」层 |
| 阈值过严导致长期「观望」 | 回测报告输出各动作触发频次；触发率过低说明阈值需调 |

---

## 十三、交付物清单

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `backend/app/services/decision_service.py` | 新建 | 判定器（纯函数） |
| `backend/app/services/market_context_service.py` | 新建 | 市场环境聚合 |
| `backend/app/api/stock.py` | 修改 | 新增 `/decision` 端点 |
| `backend/app/services/decision_backtest.py` | 新建 | 回测闸门脚本 |
| `backend/tests/test_decision_service.py` | 新建 | 单测 |
| `backend/tests/test_market_context_service.py` | 新建 | 单测 |
| `backend/tests/test_decision_api.py` | 新建 | 单测 |
| `backend/tests/test_decision_backtest.py` | 新建 | 单测 |
| `frontend/src/components/desk/DecisionCard.tsx` | 新建 | 决策卡组件 |
| `frontend/src/components/desk/DecisionColumn.tsx` | 修改 | 置顶插入决策卡 |
| `frontend/src/app/(app)/page.tsx` | 修改 | 并发拉取 decision |
| `frontend/src/lib/types.ts` | 修改 | 新增类型 |
| `docs/roadmap.md` | 修改 | 登记本阶段 |
| `docs/superpowers/specs/2026-10-21-stock-decision-engine-design.md` | 新建 | 本文档 |

---

## 附录 A：已核实的指标字段路径

> 来源：`backend/app/services/ta_service.py` `compute_indicators()` 的真实返回结构（已逐字段核对）。
> **实现时只能引用下列路径**；遇到不在表里的字段说明设计有误，改设计而不是猜字段。

| 用途 | 字段路径 | 取值说明 |
| --- | --- | --- |
| 最新收盘 | `indicators.latest_close` | float |
| 均线 | `indicators.ma.ma5 / ma10 / ma20 / ma60` | float \| None |
| 量比 | `indicators.volume.ratio` | float \| None |
| 量能状态 | `indicators.volume.state` | `expand` / `shrink` / `normal` / None |
| 通道 | `indicators.channel.state` | `up` / `down` / `sideways` |
| 压力位 | `indicators.support_pressure.pressure` | `list[float]`（升序） |
| 支撑位 | `indicators.support_pressure.support` | `list[float]` |
| 企稳 | `indicators.stabilize.state` / `.price` / `.reasons` | bool / float \| None / list |
| MACD | `indicators.macd.dif / dea / hist / cross` | `cross` ∈ `golden` / `dead` / None |
| KDJ | `indicators.kdj.k / d / j / zone / cross` | `zone` ∈ `overbought` / `oversold` / `normal` |
| BOLL | `indicators.boll.upper / mid / lower / bandwidth / squeeze / position` | `position` ∈ `touching_upper` / `above_upper` / `middle` / `touching_lower` / `below_lower` |
| 量价 | `indicators.volume_price.direction` | `healthy_up` / `panic_sell` / `liar_up_suspect` / `natural_pullback` / `insufficient` |
| 形态 | `indicators.patterns[].name` | list |
| 诱多诱空 | `indicators.liar.bull_liars` / `.bear_liars` | list |
| 位置 | `indicators.position.risk_band` | `high` / `mid` / `low`（近 120 日 P20/P80 分位） |
| 位置 | `indicators.position.band` | `high` / `mid` / `low`（近 60 日涨幅） |
| 位置 | `indicators.position.p20` / `.p80` | float \| None |
| 位置 | `indicators.position.support_price` | float \| None（**当前根之前** 20 日最低收盘 × 0.98，见下方口径修订） |
| 位置 | `indicators.position.stop_loss_price` | float \| None（参考支撑 × 0.97） |
| 信号融合 | `indicators.signal.view` / `.score` / `.confidence` / `.reasons` / `.summary` | `view` ∈ `bullish` / `bearish` / `neutral` |
| 历史信号 | `indicators.signal_series` | list |
| 数据质量 | `indicators.data_quality.kline_count` / `.degraded` | int / list[str] |

**不在指标字典里、必须从别处取的字段**

| 字段 | 来源 |
| --- | --- |
| 实时价 | 实时报价 `quote.currentPrice` |
| 昨收 | 实时报价 `quote.prevClose`（缺失时用 K 线倒数第二根收盘价） |
| 持仓均价 / 股数 | `positions` 服务（`avg_cost` / `shares`） |
| 行业名 | `industry_service.resolve_industry(code)` |
| 行业涨幅 | `sector_kline_service.get_sector_kline(industry)` 的最后一根 |
| 板块资金流 | `sector_fund_flow_service.get_sector_fund_flow()`（按名称匹配） |
| 大盘情绪 | `market_overview_service.fetch_market_sentiment()` |
| 本股资金流 | `fund_flow_service.list_recent(code, limit=1)` |

**K 线原始字段**（`ta_service` 输入的 `list[dict]`）

```
{"date": str, "open": str, "high": str, "low": str, "close": str, "volume": int}
```
注意 `open/high/low/close` 是**字符串**，用 `float()` 转换；`volume` 是 int。
「近 5 根 high 最大值」等计算自行从原始 K 线取，`compute_indicators` 不保留原始序列，
因此决策层需要同时拿到 `klines` 与 `indicators`（或由决策层自行传入 `klines` 做这几处窗口计算）。

