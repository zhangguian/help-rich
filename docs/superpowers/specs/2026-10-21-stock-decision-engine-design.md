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

- 不增强 LLM schema、不新增 LLM 调用；现有「开始分析」保持原样，作为**可选的白话翻译层**。
- 不接消息面（新闻 / 公告 / 事件因子 / 龙虎榜）。
- 不接多智能体辩论结论。
- 不做「条件命中 → 推送提醒」（价格提醒 / 微信通知）联动。
- 不做模拟盘下单联动。
- 不改 `ta_service` 现有指标算法，只消费其输出。

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
持有期   = 买入日 起 10 个交易日
胜       = 持有期内最高收盘价 > 买入价 × 1.02（+2%）
平均收益 = 第 10 个交易日收盘价 / 买入价 - 1
基准     = 同一天同一只票「次日开盘买入并持有 10 日」的同样口径
最大回撤 = 持有期内 (收盘价序列的最低点 / 买入价 - 1)
不止损基准 = 忽略 stop 信号,持有到第 10 个交易日
不止盈基准 = 忽略 exit 信号,持有到第 10 个交易日
```

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
> 另：`stop` 的回撤观察窗是 **5 日**（`exit` 是 10 日），基准则**始终**按 §10.1.1 的 10 日口径计算。

### 10.3 不达标怎么办

调整阈值 / 权重 → 重跑 → 直至达标或明确判定「此规则无价值」并从设计中移除。
**不得下调门槛，不得跳过回测直接上线。**

---

## 十一、测试策略

| 文件 | 覆盖 |
| --- | --- |
| `backend/tests/test_decision_service.py` | 每个判定器的命中 / 不命中边界（合成 K 线构造）；`derive_verdict` 映射表全覆盖；**数字可追溯不变量**（每个 `action.price` 必须能在输入中找到来源，或是输入两个数的显式运算结果） |
| `backend/tests/test_market_context_service.py` | 各数据源 mock；验证降级不崩、不编数字、`degraded` 正确记录 |
| `backend/tests/test_decision_api.py` | 端点结构完整性；400 / 503 错误码 |
| `backend/tests/test_decision_backtest.py` | 回测脚本自身正确性（小样本 sanity：合成数据下方向可预期） |

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
| 位置 | `indicators.position.support_price` | float \| None（近 20 日最低收盘 × 0.98） |
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

