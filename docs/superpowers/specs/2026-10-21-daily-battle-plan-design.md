# 每日作战计划（复盘 + 明日操作预期）设计文档

> 日期：2026-10-21
> 阶段：9（接阶段 8「盯盘决策引擎」之后）
> 状态：待评审

---

## 一、问题陈述与本设计的定位

### 1.1 用户原话

> 「现在复盘工具和技能不足，股民复盘空难，无法带着操作预期去看明天股市，没有目标，对明天的股市一脸茫然。」

拆成三个可归因的痛点：

| 痛点 | 现象 | 系统现状（已勘察确认） |
|---|---|---|
| **复盘空难** | 收盘后不知道该复盘什么、怎么复盘 | `daily_analyses` 是**单票历史存档**；`replay_records` 是回放记录；`/brief` 的盘前简报只罗列「持仓成本/盈亏 + 昨日选股结果」并用 LLM 润色，**没有任何复盘结构** |
| **没有目标** | 看完不知道明天要干什么 | `decision_service.build_decision()` 回答的是**「此刻」**该买/卖/做 T/止损，**没有任何「明天」的维度** |
| **对明天一脸茫然** | 不知道明天大盘偏多还是偏空 | `market_context_service` 给的是**当日**市场环境（涨跌家数/行业/资金流），**不含次日推断** |

全库检索证实：`次日/明日/作战/预案` 等前瞻性关键词在业务代码中**零命中**（仅在回测引擎里作为「次日开盘价」的成交假设出现）。

### 1.2 本设计的定位（必须先说清，否则会走偏）

> **「明日作战计划」不是预测器，是纪律锚点。**

它的价值**不在于**「预测明天涨还是跌」——那既做不到，也不该承诺。
它的价值在于：**在今天收盘后、明天开盘前，把「什么价位、什么条件、做什么动作、依据是什么、什么情况下这条作废」写死成清单**，让明天盘中的每一笔临时决策，都变成「按预案执行」或「明知故违并被记录」。

这直接对应用户的三句抱怨：

- 「复盘空难」→ 复盘段有**固定结构**：今天市场怎么走 + 我的持仓怎么走 + **昨天的预案兑现了没**。
- 「没有目标」→ 明日段有**逐票可执行动作**（触发价 → 动作 → 依据 → 失效条件）。
- 「一脸茫然」→ 明日预期段有**四维度规则推断 + 关键位**，且**明确标注这是规则推断不是预测**。

**诚实性铁律**（继承项目既有约束）：
- 所有数字来自真实数据源或对其显式四则运算，**零 mock、零编造**。
- LLM **只做白话翻译**，不参与任何数值计算（项目铁律「LLM 只翻译不计算」）。本设计**完全不需要 LLM**——明日预期由确定性规则算出，卡面文案是模板拼装。
- 「明日预期」在文案上只能写**倾向**（偏多/震荡/偏空），**禁止**写「必涨/必跌/一定/明日将」，并必须携带「基于 N/4 维度规则推断，非预测」标注。
- 主力资金是**估算值**（沿用项目 IR-6 既有约定），在明日预期中必须带「估算」标签。

### 1.3 与既有能力的关系（不重复造轮子）

| 既有能力 | 位置 | 本设计如何用 |
|---|---|---|
| 确定性决策引擎 | `backend/app/services/decision_service.py` | **主要原料来源**。`build_decision(ctx)` 的 `actions[]` 已带 `{kind, label, condition, price, basis, status}`，直接就是预案项 |
| 市场环境聚合 | `backend/app/services/market_context_service.py` | 提供当日市场/行业/资金，作为明日预期的维度输入 |
| 大盘概览 | `backend/app/services/market_overview_service.py` | `fetch_market_sentiment()`（涨跌家数）、`get_market_overview()`（指数）、`fetch_amount_trend()`（量能） |
| 板块资金流 | `backend/app/services/sector_fund_flow_service.py` | `get_sector_fund_flow()` → 明日预期的资金维度 |
| K 线 | `backend/app/services/kline_service.py` | `fetch_klines("000001.SH")` 取上证指数日 K（自带 volume）→ 量能 + 均线 + 关键位 |
| 持仓 / 流水 | `backend/app/modules/portfolio/` | 目标股票池来源 + 兑现比对的「是否真的执行了」 |
| 技术指标 | `backend/app/services/ta_service.py` | `compute_indicators` → 决策引擎的 indicators 输入 |

**本设计新增的只有三件事**：①「明日预期」规则算法 ②「决策→预案」的转换规则 ③「兑现比对」状态机。

---

## 二、已确认的产品决策

| 决策项 | 选择 | 理由（用户确认） |
|---|---|---|
| 交付形态 | **新增独立页面 `/plan`** | 复盘与计划是文档式内容，与盯盘台（实时盯盘）、`/brief`（轻量推送速览）职责不同 |
| 覆盖范围 | **持仓 5 只 + ★关注 6 只，去重后最多 11 只** | 真正的「我的票」；11 只约 15~25 秒可生成完全部预案 |
| 复盘闭环 | **做闭环**：今日复盘含昨日预案兑现比对 + 明日计划 | 只有前瞻没有回看，闭环才谈得上「有目标」，错误才可归因 |

实测数据（2026-10-21 开发库）：`watchlist` 43 条，其中 `is_favorite=1` **6 条**；`positions` **5 条**。

---

## 三、整体数据流

```text
                     ┌──────────────────── 用户点击「生成今日计划」/ 定时触发
                     ▼
        ┌────────────────────────────────────────────────────┐
        │  battle_plan_service.build_plan(plan_date=D)       │  编排层
        └───┬───────────────┬───────────────┬──────────────┘
            │               │               │
            ▼               ▼               ▼
      ① 取数(并发)    ② 明日预期      ③ 逐票预案        ④ 今日复盘
      ┌──────────┐   ┌────────────┐  ┌──────────────┐  ┌──────────────┐
      │ 11 只票  │   │outlook_    │  │plan_item_    │  │fulfillment_  │
      │K线+指标  │   │service     │  │builder       │  │checker       │
      │+报价+持仓│   │(纯函数)     │  │(纯函数)       │  │(纯函数)       │
      │+大盘快照 │   │ 4 维度规则  │  │决策→预案项     │  │昨日预案×今日 │
      └──────────┘   └────────────┘  └──────────────┘  │行情+流水     │
            │               │               │           └──────────────┘
            └───────────────┴───────────────┘
                            ▼
              ┌──────────────────────────────┐
              │ 落库: battle_plans(D)         │
              │        + battle_plan_items(D) │
              │  (D 日报: 今日复盘=今日实际   │
              │   + 昨日兑现; 明日预案=对 D+1)│
              └──────────────────────────────┘
                            ▼
              ┌──────────────────────────────┐
              │ GET /api/battle-plan?date=D  │
              └──────────────────────────────┘
                            ▼
                   ┌────────────────┐
                   │  /plan 页面     │
                   │ 左=明日预案清单 │
                   │ 右=明日预期+复盘│
                   └────────────────┘
```

### 3.1 关键设计：一份日报 = 一个自然日 D

`battle_plans` 一行对应一个**生成日 D**，其内容里同时装着两个时间语义：

| 段 | 时间语义 | 内容来源 |
|---|---|---|
| `review`（今日复盘） | **D 当天已发生** | D 当天真实行情 + D-1 日报的预案兑现比对 |
| `outlook`（明日预期） | **对 D+1 的推断** | D 收盘后的真实数据 + 确定性规则 |
| `items`（明日预案） | **对 D+1 的操作计划** | D 收盘时的决策引擎输出转换而来 |

**闭环的闭合方式**：
- D 日盘后生成日报 → 产出「对 D+1 的预案」，`fulfillment` 初值 `pending`。
- D+1 日盘后生成日报时，`fulfillment_checker` 读取 **D 日报的 items**（不是 D+1 日报的），用 D+1 的真实 K 线 + D+1 的交易流水判定兑现，**回填 D 日报**的 `fulfillment` 字段，并写进 D+1 日报的 `review` 段。
- 于是 D 日报的 items 最终带着 `touched / executed / missed` 状态留存——**历史日报永远保留当时的预案和最终的兑现结果**，形成可回溯的决策档案。

> 为何不把「明日预案」单独建一张按目标日索引的表？因为那样 D 日和 D+1 日会各持一份，日期语义容易混。**生成日唯一**是更简单也更不易错的模型。

---

## 四、后端设计

### 4.1 模块划分（四个单一职责单元 + 一个编排）

| 文件 | 职责 | IO | LLM | 可测性 |
|---|---|---|---|---|
| `backend/app/services/outlook_service.py` | 明日市场预期：4 维度规则推断 + 关键位 | 无（纯函数，入参为已取好的数据） | 无 | 纯单测 |
| `backend/app/services/plan_item_builder.py` | 决策输出 → 预案项列表 | 无（纯函数） | 无 | 纯单测 |
| `backend/app/services/fulfillment_checker.py` | 昨日预案 × 今日行情/流水 → 兑现状态 | 无（纯函数） | 无 | 纯单测 |
| `backend/app/services/battle_plan_service.py` | 取数 → 调用三者 → 落库 | 有 | 无 | 集成测试（mock 外部 IO） |
| `backend/app/repositories/battle_plan_repo.py` | 两张表的读写 | 有 | — | — |

**边界原则**：三个纯函数模块**不 import 任何 IO 服务**，只接受已准备好的 dict/list 输入。这与 `decision_service` 的既有做法一致（`DecisionContext` 是纯数据）。

### 4.2 数据模型

> ORM 风格对齐项目既有写法（SQLAlchemy 2.0 `Mapped[...]` + `mapped_column`，如 `DailyAnalysis` / `ReplayRecord`）。

```python
# backend/app/models/orm.py 新增两表

class BattlePlan(Base):
    """每日作战日报。一行 = 一个生成日 D 的日报。"""
    __tablename__ = "battle_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_date: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)  # D
    outlook_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # 明日市场预期（对 D+1）
    review_json: Mapped[str | None] = mapped_column(Text, nullable=True)    # 今日复盘（D 实际 + 昨日兑现）
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)      # 生成时点/降级项/数据质量/目标股票池
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class BattlePlanItem(Base):
    """日报内的一条逐票预案（目标日 = plan_date 的次日）。"""
    __tablename__ = "battle_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("battle_plans.id"), nullable=False, index=True)
    plan_date: Mapped[str] = mapped_column(String, nullable=False, index=True)  # 冗余,便于按日查
    stock_code: Mapped[str] = mapped_column(String, nullable=False)
    stock_name: Mapped[str | None] = mapped_column(String, nullable=True)
    item_kind: Mapped[str] = mapped_column(String, nullable=False)   # entry/exit/stop/t_plan/unlock/do_not
    direction: Mapped[str] = mapped_column(String, nullable=False)    # buy/sell/none
    label: Mapped[str] = mapped_column(String, nullable=False)       # 动作名
    trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)         # 触发价
    trigger_condition: Mapped[str] = mapped_column(Text, nullable=False)              # 触发条件原文
    basis_json: Mapped[str | None] = mapped_column(Text, nullable=True)              # 依据数字 list[str]
    invalid_if: Mapped[str | None] = mapped_column(Text, nullable=True)              # 失效条件
    status_now: Mapped[str] = mapped_column(String, nullable=False)    # 生成时该动作状态 now/armed/blocked
    fulfillment: Mapped[str] = mapped_column(String, default="pending", nullable=False)
                                               # pending/touched/executed/missed/n_a
    fulfillment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
```

**迁移**（已核实项目实际机制，2026-10-21）：

- 项目走 **Alembic**，迁移文件在 `backend/migrations/versions/`，**不在** `backend/alembic/versions/`。
- 当前库 HEAD = **`f6a7b8c9d0e1`**（`restore_kline_cache`）。新迁移 `down_revision = "f6a7b8c9d0e1"`。
- 迁移写法对齐既有惯例（见 `f6a7b8c9d0e1_restore_kline_cache.py`）：
  - `upgrade()` 内用 `sa.inspect(bind).has_table(...)` **先查再建**（幂等，避免"迁移已应用但表被删"导致 `upgrade head` 失败——这正是 `kline_cache` 踩过的坑，务必照抄这个防御）；
  - `downgrade()` 删表。
- 兜底路径：启动时 `create_all(checkfirst=True)` 只补建**缺失**表，已存在的表一个字节不动。
- 表名 `battle_plans` / `battle_plan_items` 不与既有 33 张表冲突。

### 4.3 明日市场预期算法（`outlook_service`）★核心新增

#### 4.3.1 输入（全部由编排层取好传入）

```python
def build_outlook(
    index_klines: list[dict],      # 上证指数日K,含 date/open/high/low/close/volume,升序
    sentiment: dict | None,        # fetch_market_sentiment(): up_total/down_total/...
    sector_flows: list[dict] | None,  # get_sector_fund_flow(): [{name, netamount_yi}, ...]
) -> dict
```

#### 4.3.2 四维度打分

每维度取值 `-1`（偏空）/ `0`（中性或缺失）/ `+1`（偏多）。**缺失一律记 0 且不计入有效维度数 N**。

| 维度 | 数据源 | 偏多（+1） | 偏空（-1） | 中性（0） | 缺失处理 |
|---|---|---|---|---|---|
| **量能** | 上证日K `volume` | 今日量 ≥ 近 5 日均量 × **1.10** | 今日量 ≤ 近 5 日均量 × **0.90** | 介于两者之间 | K线不足 6 根 → 缺失 |
| **涨跌家数** | `sentiment.up_total/down_total` | 上涨占比 ≥ **60%** | 上涨占比 ≤ **40%** | 40%~60% | `up_total+down_total=0` 或缺字段 → 缺失 |
| **指数均线** | 上证 `close` vs MA5/MA10 | `close > MA5 > MA10` | `close < MA5 < MA10` | 其余形态 | K线不足 11 根 → 缺失 |
| **板块资金** | `sector_flows` | 净流入**总额** > 0 | 净流入**总额** < 0 | 总额 = 0(多空抵消) | 列表为空/None → 缺失 |

> **板块资金的特殊说明**：项目 `fetch_main_fund_flow()` 是**估算值**（IR-6），但 `get_sector_fund_flow()` 是**真实板块资金流**（新浪口径）。本设计用**真实**的 `get_sector_fund_flow()`，因此该维度**不带估算标签**。若未来改用个股估算流，则必须加标签。
>
> **为什么按「净流入总额」而不是「有无正流入」判定**（2026-10-21 实现阶段裁决）：「有正有负」在逻辑上**蕴含**「存在正流入」，若按"有无"判定，偏多与中性两档会互相排斥、无法同时成立——本设计的规则表与测试因此一度自相矛盾。改按**总额符号**判定后三档互斥且完备：总额 > 0 = 钱整体在流入（偏多）、< 0 = 整体在流出（偏空）、= 0 = 多空抵消（中性）。这与另外三个维度「看整体量级而非看有没有」的判据保持一致。
>
> **该维度的两条诚实性规则**（2026-10-21 复审发现，必须遵守）：
> 1. **浮点零和必须归一**：`[38.6, -12.4, -26.2]` 的和是 `3.55e-15` 而非精确 0。直接用 `total > 0` 判会误判成偏多，并渲染出「净流入合计 0.00 亿」这种自相矛盾的文案。故 `|total| < 1e-9` 归一为 0。
> 2. **全部板块净额都是 `None` 时判 `missing`，不是 `flat`**：那等于根本没有板块资金数据，若算成"有效"，会对外宣称「基于 4/4 维度规则推断」而实际缺一个维度——这是**谎报数据完整性**。

#### 4.3.3 结论合成

```
S = Σ 各维度得分（-4..+4）
N = 有效维度数（0..4）

if N == 0:              → stance = "unknown"，全部标 degraded
elif S >= 1 and N >= 2: → stance = "bullish"   # 偏多
elif S <= -1:           → stance = "bearish"   # 偏空
else:                   → stance = "neutral"   # 震荡
```

**为什么要 `N >= 2` 才能判偏多**：只靠单一维度就敢给方向 = 过度自信。有效维度不足 2 个时，最诚实的结论是「震荡/数据不足」。`bearish` 不设 `N >= 2` 的门槛是**不对称设计**，需在文档中显式说明理由：偏空判断（普跌/放量下跌/破位）通常是**单条强证据**即可成立（风险侧保守优于激进）。

#### 4.3.4 关键位（支撑 / 压力）

全部取自上证日K真实值，**不计算虚构点位**：

| 用途 | 取值 | 缺失处理 |
|---|---|---|
| 支撑 1 | `MA5`（若 `MA5 < close`） | MA5 ≥ close → 不作支撑 |
| 支撑 2 | 今日 `low` | 缺 → 该位不展示 |
| 压力 1 | 今日 `high` | 缺 → 不展示 |
| 压力 2 | `MA20`（若 `MA20 > close`） | MA20 ≤ close → 不作压力 |

另附**今日收盘价** `close` 与 **MA5/MA10/MA20**，供用户自己看位置关系。

#### 4.3.5 输出结构

```python
{
  "stance": "bullish" | "bearish" | "neutral" | "unknown",
  "stance_label": "偏多" | "偏空" | "震荡" | "数据不足",
  "score": int,               # S
  "dims_total": 4,
  "dims_effective": N,
  "dims": [
     {"key": "volume", "label": "量能", "score": 1, "state": "bull",
      "detail": "今日 1.32 亿手,较 5 日均量放大 12%"},
     ... 共 4 项，缺失项 score=0 且 state="missing"
  ],
  "key_levels": {
     "close": 3713.03, "ma5": 3705.2, "ma10": 3690.1, "ma20": 3680.5,
     "support": [3705.2, 3698.4],     # 升序
     "resistance": [3721.6, 3745.0],
  },
  "disclaimer": "基于 N/4 维度规则推断，非预测；仅作明日操作参考。",
  "degraded": bool,
  "degraded_reason": [...],
}
```

`dims[].detail` **必须是由真实数字拼出的句子**（模板拼装，非 LLM）。

### 4.4 决策 → 预案转换规则（`plan_item_builder`）★核心新增

#### 4.4.1 输入 / 输出

```python
def build_items(
    decision: dict,              # decision_service.build_decision() 的输出
    position: PositionView | None,  # 含 .shares / .avg_cost **属性**的对象；无持仓则 None
) -> list[dict]             # 明日预案项列表

def build_todos(decision: dict) -> list[dict]
    """从同一份 decision 里挑出 status=="now" 的动作 → 今日复盘的「未执行待办」"""
```

> `build_items` 与 `build_todos` 是**同一份 decision 的两个出口**，用两个函数而非一个返回元组，是为了各自职责单一、可独立单测。`build_todos` 与 `build_items` 共享「动作筛选」helper（见 §4.4.2），保证同一动作不会同时出现在两边。

#### 4.4.2 转换表（`actions[]` 的三种状态分三路）

| 决策输出 | 去向 | 转换后的文案形态 |
|---|---|---|
| `actions[]` 中 `status == "now"` | **不进明日预案** → 进「今日复盘·未执行待办」 | 「条件已满足（X），今日未处理」 |
| `actions[]` 中 `status == "armed"` | **明日预案主力** | 「明日若回踩 X 元（条件：…）→ 做 Y」 |
| `actions[]` 中 `status == "blocked"` | **明日预案·解锁条件** | 「需先：<缺的那条依据>，满足后按 X 执行」 |
| `stop_loss` | 明日预案（**仅持仓票**） | 「明日跌破 X 元 → 止损离场」 |
| `t_plan` | 明日预案（**仅持仓票**） | 「上沿 X 减 / 下沿 Y 接（底仓 N 股）」 |
| `do_not[]` | 明日预案·别动 | 「明日别动：…」 |

**为什么 `now` 不进明日预案**：`now` 的语义是「此刻条件已满足，此刻就该做」。它若写进明日预案，就是一条**已经过期的建议**——这正是股民复盘里最常见的自欺（"我有个计划"但其实条件早就到了你没做）。所以它必须被**显式推到复盘段的待办清单**，逼用户面对。

**持仓视图契约（全项目统一为「属性形状」，2026-10-21 跨任务裁决）**：`build_items` 的 `position` 与 `position_status.resolve_position_status` 的 `position` **统一要求含 `.shares` / `.avg_cost` 属性的对象**，不用 dict。理由：`resolve_position_status` 的契约已写进 docstring 并通过评审，且被既有代码（`api/diagnose.py`）使用，改它成本高；而 `plan_item_builder` 是新代码，改它零成本。接线层（`battle_plan_service`）造一个 `PositionView` 对象同时传给两者——**避免出现 dict/对象两套契约**。

**`armed` 是明日预案的主体**，因为它的语义天然是「条件还差一步，明日大概率会到」。

**`blocked` 转为「解锁条件」**，因为 `blocked` 的 basis 里明确写了缺什么（如「量能仅 0.9 倍，未达 1.5 倍确认标准」）——这就是明天的观察点。

> **口径修正（2026-10-21 T3 评审发现）**：不是所有 blocked 动作的 basis 都能用 `basis[1:]` 推导缺失条件。
> 真实反例：L4 补仓摊薄 blocked 时，basis 是两条**事实**（「持仓 600 股 @ 成本 15.58 元」「补 100 股后均价 9.87 元」），
> 真正的缺失条件在 `reasons` 里（下跌通道 / 无企稳信号 / 大盘偏冷）。
> 若照 `basis[1:]` 拼，解锁依据会变成「补 100 股后均价 9.87 元未满足则不解锁」——那不是条件，是事实，用户读到的是**假前提**。
> 故决策层必须显式产出 `action["missing"]`（缺失条件列表），转换层优先读它，读不到才退回 `basis[1:]`。

#### 4.4.3 失效条件 `invalid_if`（必须算出来，不能空着）

| item_kind | direction | `invalid_if` 规则 | 示例 |
|---|---|---|---|
| `entry` | buy | 「跌破 {trigger_price} × 0.97 则本条作废（不接下跌中的刀）」 | 触发价 9.92 → 「跌破 9.62 则作废」 |
| `entry`（blocked→unlock） | buy | 「{缺的那条依据}未满足则不解锁」 | 「量能未达 1.5 倍则不解锁」 |
| `exit` | sell | 「回落至 {trigger_price} × 1.03 以上未达成，明日不追高」 | 止盈价 12.03 → 「回落至 12.39 以上未达成则不追」 |
| `stop` | sell | 「收盘站回 {trigger_price} 上方则明日不看止损」 | 止损 9.62 → 「收盘站回 9.62 上方则不看止损」 |
| `t_plan` | sell | 「上沿未触及则不做减仓；下沿未触及则不做回补」 | — |
| `do_not` | none | 无（恒定成立） | — |

> 所有 `invalid_if` 里的数字都是**由 trigger_price 的显式四则运算得出**（`×0.97` / `×1.03`），符合「价格必须来自 indicators/报价/持仓或其显式四则运算」铁律。

#### 4.4.4 输出结构（每条预案项）

```python
{
  "stock_code": "001896.SZ", "stock_name": "豫能控股",
  "item_kind": "entry", "direction": "buy",
  "label": "支撑企稳建仓",
  "trigger_price": 9.62,
  "trigger_condition": "回踩 9.62 元不破且 MACD 绿柱缩短时,首仓建仓",
  "basis": ["企稳价 9.62 元(现价 9.920 +3.1%)", "stabilize.state=true"],
  "invalid_if": "跌破 9.63 则本条作废(不接下跌中的刀)",
  "status_now": "armed",
  "source": "decision.actions",   # 溯源用
}
```

#### 4.4.5 「明日」这一时间语义如何落到字面

预案项的措辞统一用「**明日**」而非「今天/现在」，以免与生成时点混淆。触发价一律为**明日**的观察价位；`trigger_condition` 保留决策引擎原文（它描述的是"满足什么条件"，与时点无关）。

### 4.5 兑现比对（`fulfillment_checker`）★闭环核心

#### 4.5.1 记法约定（避免日号混淆）

本节统一用 **R / R+1**：

- **R** = 被检查的日报日。R 日报的 `items` 是「R 收盘时为 **R+1** 定下的预案」。
- **R+1** = 兑现判定日（预案实际生效的那一天）。

例：10-21 收盘生成日报（其 items 面向 10-22）。到 10-22 收盘后复盘时，**R = 10-21，R+1 = 10-22**。

#### 4.5.2 输入

```python
def check_fulfillment(
    items: list[dict],          # R 日报的 items（含 trigger_price / direction / item_kind）
    target_klines: dict,        # {stock_code: [R+1 的日K]}，含 open/high/low/close
    transactions: list[dict],   # R+1 的交易流水 [{stock_code, action, share, price, trade_date}]
) -> list[dict]                # 每项补 fulfillment / fulfillment_note
```

**输入范围约束**：传入的 `target_klines` 与 `transactions` **必须只含目标日 R+1 的数据**。
模块本身不做日期过滤（纯函数、零 IO，日期筛选属于编排层职责），若上游喂进多日 K 线，
本模块会把多日极值混在一起当成单日极值 —— 这正是「假触及」的来源，由编排层负责裁剪。

#### 4.5.2.1 流水归属规则（一条流水最多被一条预案消费）

同一笔操作**只能证明一条预案被执行**。否则同票多条同向预案会互相白嫖同一笔流水，
把「T 回补的那笔买入」也算成「建仓预案已执行」—— 那种假阳性会污染复盘档案。

归属按以下顺序进行：

1. **T 子项硬匹配优先**（按价格区间，不按方向）：
   - `t_sell`：成交价 ≥ 上沿 × 0.98
   - `t_buyback`：成交价 ≤ 下沿 × 1.02
   - 命中即消费该流水，优先级高于所有普通预案。
2. **其余预案按方向匹配尚未被消费的流水**（**必须同一只票**）：
   - ⚠️ **候选集是「(预案, 流水) 对」的全局集合，不是「逐条预案各自挑一条」**。
     先枚举所有同票、方向兼容、且流水带价的 (预案, 流水) 候选对，
     按「成交价与触发价的绝对价差」**全局升序**排序，再依次配对；一条流水被配走后即被消费。
   - **不能逐条预案「先到先得」**（2026-10-22 最终评审发现的真实缺陷）：
     同票多条同向预案时，先遍历到的那条会抢走流水，哪怕另一条的触发价明显更接近成交价 ——
     结果是「用户实际照做的那条」被记成执行缺口，抢到的那条被记成「已执行但价位不符」。
     这不是显示瑕疵，是**往复盘档案写错事实**。
   - 候选流水与预案必然同票，所以「价差最小」用**绝对价差**即可（同票的触发价数量级相近）。
3. **成交价缺失的流水不能证明归属**：只有在没有任何带价候选时才兜底消费，并在 `fulfillment_note` 里披露「成交价缺失」。
4. **纪律类（`do_not` / `unlock`）不参与流水归属**：它的 `executed` 表示「当日有操作（违规）」，
   同一笔操作可以同时构成「别的预案的执行」和「纪律违规」—— 两个结论都成立，不该互相吞掉。

**配对顺序（全局三段，不是「逐条预案各走一遍」）**：
1. **第一段 · T 子项硬匹配**：先在 (T 子项, 带价流水) 之间做区间命中配对 —— T 子项优先于所有普通预案；
2. **第二段 · 普通预案全局择优**：剩余的 (预案, 流水) 候选对按绝对价差**全局升序**贪心配对，
   一条流水被配走即消费，不再参与后续配对；
3. **第三段 · 无价流水兜底**：前两段配完仍有流水无归属的，才轮到「成交价缺失」的流水按方向兜底（并披露）。

**偏离披露**：成交价与触发价偏离超过 **3%** 时，在 `fulfillment_note` 里追加成交价与触发价。
「已执行」不等于「按计划价位执行」—— 追高买、提前卖都要看得见。

**浮点容差**：阈值比较（价格区间、偏离比例）统一加 `1e-9` 容差，
避免 `9.2 × 1.02 = 9.383999999999999` 这类表示误差漏判「恰好按计划价位成交」。

#### 4.5.3 判定规则

**第一步：是否真的执行了**（最高优先级）
- 在 R+1 的流水里找到该票的对应方向操作 → `executed`。
  - buy 类（entry）：`action` 为买入方向
  - sell 类（exit/stop/t_plan 减仓）：`action` 为卖出方向
  - **注意**：T 操作的「减」与「接」方向相反，**不按方向匹配**，而是按**价格区间匹配**（见下）。
  - **归属**：一笔流水只归属一条预案，规则见 §4.5.2.1。

**第二步：价格是否触及**
- sell 类（`direction == "sell"`）：`high >= trigger_price` → `touched`
- buy 类（`direction == "buy"`）：`low <= trigger_price` → `touched`
- `direction == "none"`（do_not / unlock）→ `n_a`（不参与统计）

**第三步：都没中**
- 有 trigger_price 但 R+1 当日最高/最低都没碰到 → `missed`

**第三步之二：无数据 → `no_data`（不是 `missed`）**
- 若该票在 R+1 **没有拿到日K**（当日停牌 / 数据源未出 / 节假日），且**当日也没有该票的流水**，
  则我们**根本无从判定**它触没触发 → 判 `no_data`，note 写「目标日无行情数据，未判定」。
- ⚠️ **不能判 `missed`**：`missed` 的语义是「当天没碰到价位」，
  而 `no_data` 的真相是「我们没拿到那天的行情」。两者混同 = **用无知冒充事实**，
  直接违反本模块的诚实性底线（也会把复盘档案永久写脏）。
- `no_data` **不计入统计**（与 `n_a` 一样），且**不写回** R 日报的 items（保持 `pending`），
  等数据补齐后可重新判定 —— 不可让「无数据」冻结成「未兑现」。
- 若当日**有流水**，则流水是充分证据 → 按「第一步」判 `executed`，**不受日K缺失影响**。

**T 操作特例**：`t_plan` 同时含上沿（减）与下沿（接）。拆成两条子项分别判定：
- 上沿触发：R+1 `high >= 上沿` → 该子项 touched
- 下沿触发：R+1 `low <= 下沿` → 该子项 touched
- 若两子项均未触及 → 各自 `missed`
- 若 R+1 流水有该票卖出且卖价 ≥ 上沿 × 0.98 → 减仓子项 `executed`；有买入且买价 ≤ 下沿 × 1.02 → 回补子项 `executed`

**第四步：纪律问题（额外标记）**
- 若该票在 R 日报中标记为「别动/do_not」或「unlock 未解锁」，而 R+1 流水里有该票的买卖操作 → `fulfillment = "executed"` **且** `fulfillment_note` 前缀「⚠️ 纪律问题：昨日标记别动/未解锁，今日仍有操作」。

#### 4.5.4 复盘段的统计口径

| 状态 | 含义 | 复盘里的评价 |
|---|---|---|
| `executed` | 触发了且真的做了 | ✅ 按计划执行 |
| `touched` | 触发了但没做 | ⚠️ 执行缺口（价格到了，你没动） |
| `missed` | 一天都没碰到 | ➖ 不评价对错（本来就没到） |
| `n_a` | 无触发价（别动/解锁类） | 不计入统计 |
| `no_data` | 目标日**没有该票的行情数据** | 不计入统计；**不写回**（保持 pending，等数据补齐再判） |
| `executed` + 纪律标记 | 计划说别动却动了 | ❌ 纪律问题 |

**统计数字**：复盘段展示「R 日报为 R+1 定下的 N 条预案：触及 X · 执行 Y · 未触发 Z」+ 一句话评价（按最严重项给：纪律问题 > 执行缺口 > 数据不足 > 正常）。

> **「数据不足」优先于「按计划执行」**：有项没数据时不能说「按计划执行」——
> 「没判定」不是「做对了」。同理 `no_data` 绝不可写回 items：写回去就等于把
> 「没拿到数据」永久定成「没兑现」，且会被幂等冻结机制锁死。

> **诚实性**：说「未触发」不评价对错，是刻意的。计划说「跌破 9.62 止损」，结果当天最低 9.70 没跌破——这不是「止损错了」，而是「不该触发」。把它算成错误会污染决策档案。

### 4.6 编排层（`battle_plan_service`）

#### 4.6.1 目标股票池

```python
def resolve_target_stocks() -> list[dict]:
    """持仓 ∪ ★关注，按 stock_code 去重。返回 [{stock_code, stock_name, in_position, is_favorite}]"""
```
- 持仓来源：`portfolio.service.get_all_positions()`（已是聚合结果，含 `avg_cost` / `shares` / `pnl_pct`）
- 关注来源：`watchlist` 表 `is_favorite = 1`
- **去重规则**：同一票既持仓又关注 → 合并为一条，`in_position=True, is_favorite=True`
- **上限**：超过 20 只时按「持仓优先 → 关注按加入时间倒序」截断，并在 `meta_json` 记录 `truncated` 与实际数量（诚实披露，不静默截断）

#### 4.6.2 生成流程

```python
async def build_plan(plan_date: date) -> dict:
    # 1) 取数（并发，单票失败不影响整体）
    #    - 每票：klines(190) + ta_service.compute_indicators + quote + 持仓
    #    - 市场：上证日K(30) + fetch_market_sentiment + get_sector_fund_flow
    # 2) outlook = build_outlook(index_klines, sentiment, sector_flows)
    # 3) items = [build_items(build_decision(ctx), pos) for 每票]
    #    todos = [build_todos(build_decision(ctx)) for 每票]   # 同一份 decision 的另一个出口
    # 4) 兑现比对：R = **最近一份早于 plan_date 的日报**(数据驱动),R+1 = 该日报的 meta.target_date
    #    → 读 R 日报的 items(它们面向 R+1),用 R+1 的日K + 流水判定
    #    → check_fulfillment(R_items, R+1_klines, R+1_transactions)
    #    ⚠️ R **不能**用「plan_date 减一天」:周一的减一是周日 → 必然找不到,
    #       每个长假后的第一个交易日同理;且「上一份日报」天然就是上一交易日那份。
    # 5) 落库：upsert battle_plans(D) + 替换 battle_plan_items(D)
    #    同时把兑现结果回填到 R 日报的 items(**no_data 不回填**)
    # 6) 返回完整日报
```

**降级原则**（继承项目既有约定）：
- 单票取数失败 → 该票不出现在 items，`meta.degraded` 记「002185.SZ 数据不可用」，**不编造该票预案**
- 大盘数据部分缺失 → 对应维度 `state="missing"`，`dims_effective` 相应减少
- 全部大盘数据缺失 → `stance="unknown"`，卡面显示「明日预期：数据不足」
- **流水读取失败** → 兑现比对只判触及不判执行，`meta.degraded_reason` 记「流水不可用」，
  note 标注「流水不可用，未核对执行」—— **不得**写成「当日无对应操作」（那是我们没看到，不是没有）
- **目标日无该票行情数据** → 该条判 `no_data`，不计入统计、不写回 items

#### 4.6.3 幂等与覆盖

- `battle_plans.plan_date` 唯一索引 → 同一天重复生成走 UPSERT。
- `battle_plan_items` 每次生成**整体替换**（先删该 plan_id 的旧行再插）。
- **例外**：D 日报的 items 若已有**可信判定**（`fulfillment ∈ {executed, touched, missed}`），
  重新生成 D 日报时**保留原 items 不动**（防止把已判定的兑现状态冲掉），只更新 `outlook` / `review` / `meta`。
  实现方式：生成前检查该 plan 是否已有 items 且存在**可信判定** → 跳过 items 重建。
- ⚠️ **`pending`（还没判）与 `no_data`（没数据，判不了）都不可信** → 不触发例外，items 照常重建。
  否则「无数据」会被冻结成永久的「未兑现」，且再也无法自愈（这是阶段 9 首版实现里最严重的一个缺陷）。

#### 4.6.4 目标交易日

「明日」= **下一个交易日**，不是「明天自然日」。
- 基准 = **生成日 D 本身**（不是「指数最后一根 K 线的日期」—— 盘中生成时那还是昨天，用它当基准会算出「明天 = 今天」，把 D/D+1 契约塌成今日）。
- 取法：D 之后的第一个工作日（跳过周末）。无真实交易日历（项目内 `kline_service._last_trading_day()` 也只跳周末，没有法定节假日表），
  因此一律用「工作日」近似，并**在 meta 中标注 `target_date_estimated: true`**。

> 这一处是**诚实披露点**：若目标日只是工作日推算（可能撞上法定节假日导致顺延），必须在卡面标注「明日 = YYYY-MM-DD（按交易日历推算）」。

### 4.7 API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/battle-plan?date=YYYY-MM-DD` | 取指定日期的日报。`date` 缺省 = 今天。**该日未生成 → 返回 404 + `{detail: "该日作战计划尚未生成"}`**（不返回空壳，避免前端误显示「无内容」） |
| `POST` | `/api/battle-plan/generate` | 生成今天的日报（幂等）。body 可选 `{date}`。返回完整日报 |
| `GET` | `/api/battle-plan/scope` | 返回目标股票池（持仓+关注去重结果），前端显示「本次覆盖 N 只」 |

**响应契约**（`snakeToCamel` 前的 snake_case）：

```jsonc
{
  "plan_date": "2026-10-21",
  "target_date": "2026-10-22",
  "outlook": { /* §4.3.5 */ },
  "review": {
    "market": { "index_close": 3713.03, "change_pct": -0.6, "volume_note": "..." },
    "fulfillment": {
      "total": 7, "executed": 1, "touched": 2, "missed": 3, "na": 1, "no_data": 0,
      "verdict_label": "有执行缺口", "verdict_level": "warn",
      "items": [ { "stock_code": "...", "label": "...", "fulfillment": "touched", "note": "..." } ]
    },
    "pending_todos": [ { "stock_code": "...", "label": "...", "condition": "...", "price": 9.62 } ]
  },
  "items": [ { /* §4.4.4 */ } ],
  "meta": {
    "scope_count": 11, "scope": [...], "truncated": false,
    "degraded": false, "degraded_reason": [],
    "generated_at": "2026-10-21T15:12:33+08:00",
    "target_date_estimated": false
  }
}
```

**超时**：11 只票并发取数，前端请求须 `{timeout: 60000}`（与决策端点同级别；`api.ts` 默认 10000ms 会超时）。

### 4.8 LLM 的位置

**本设计不使用 LLM。** 全部文案由模板拼装，数字由规则算出。

理由：
1. 明日预期必须是**确定性、可复算、可回测**的——LLM 每次输出不同，明天就无法验证「昨天这个判断对不对」。
2. 项目铁律「LLM 只翻译不计算」——这里连翻译都不需要。
3. 零 LLM 意味着零延迟、零成本、零降级风险（无 API key 时功能完整）。

> 若未来要加「白话解读」层，只能在**既有确定性结论之上**做翻译，且**不得引入任何新数字**——与阶段 8 卡面文案的约束一致。

---

## 五、前端设计

### 5.1 页面结构 `/plan`

```
┌──────────────────────────────────────────────────────────────────────┐
│ 顶栏: 买股工具室 · 作战计划      2026-10-21(周三)  覆盖 11 只        │
│                                    [生成今日计划] [重新生成]           │
├────────────────────────────────────┬─────────────────────────────────┤
│ 左栏(主, flex:1)                   │ 右栏(360px)                     │
│                                    │                                 │
│ ┌ 明日操作预案 ─────────────────┐  │ ┌ 明日市场预期 ──────────────┐ │
│ │ ▸ 豫能控股 001896.SZ           │  │ │  倾向：震荡                 │ │
│ │   结论：亏损 -36.32% · 走势下跌通道 │ │  基于 3/4 维度规则推断，非预测 │ │
│ │   ┌ 止损 跌破 9.62 → 离场      │  │ │  量能  ▓▓▓░ 放大12%        │ │
│ │   │ 依据: 近20日低点 9.92×0.97  │  │ │  涨跌家数 ▓░░░ 上证-0.60%   │ │
│ │   │ 失效: 收盘站回9.62上方则不看 │  │ │  均线  ▓▓▓░ 站上MA5      │ │
│ │   └──────────────────────────┘  │ │ │  资金  ▓░░░ 主攻电子       │ │
│ │   ┌ 建仓 待触发                 │  │ │  关键位 支撑 3705/3698      │ │
│ │   │ 若回踩 9.62 → 首仓建仓      │  │ │          压力 3721/3745      │ │
│ │   │ 失效: 跌破 9.33 作废        │  │ └────────────────────────────┘ │
│ │   └──────────────────────────┘  │                                 │
│ │   ┌ 别动：下跌通道中不要抄底    │  │ ┌ 今日复盘 ─────────────────┐ │
│ │   └──────────────────────────┘  │ │ │  昨日预案 7 条：           │ │
│ └────────────────────────────────┘  │ │  触发2 · 执行1 · 未触发3    │ │
│                                    │ │ │  ⚠️ 存在执行缺口            │ │
│                                    │ │ │  今日待办 2 项              │ │
│                                    │ │ └────────────────────────────┘ │
└────────────────────────────────────┴─────────────────────────────────┘
```

### 5.2 布局与响应式

- **≥1280px**：两栏（左预案 + 右预期/复盘）
- **1024px**：两栏保持（按项目铁律「三栏保持到 1024px」的同源要求，本页两栏不缩为单栏），右栏收窄至 320px
- **820px 及以下**：单栏，顺序为「明日预期 → 明日预案 → 今日复盘」（**先把最重要的市场预期放最前**，因为窄屏首屏空间有限）
- **首屏不留大片虚空**：无数据时展示引导态（说明「当前覆盖 11 只，点生成按钮产出计划」+ 已有持仓/关注列表），不留空白页
- 横向滚动：四档宽度均须 `scrollWidth == clientWidth`

### 5.3 配色（沿用项目既有规范，不得自创）

| 元素 | 颜色 | 理由 |
|---|---|---|
| 买入动作 / 看多 / 涨 | **红** | A 股红涨绿跌 |
| 卖出动作 / 看空 / 跌 | **绿** | 同上 |
| 选中 / 焦点 | 青 `#22D3EE` | 项目既定：青只给选中/焦点 |
| 预警 / 未执行缺口 / 纪律问题 | 琥珀 `#F5A524` | 项目既定：琥珀只给预警 |
| 失效 / 已错过 | 灰 | 弱化 |

**不得**用绿色表示「盈利/安全」——在 A 股语境下绿=跌，盈利浮盈一律用红色（与盯盘台持仓页签一致：浮盈 +177.71% 是红色，浮亏 −36.32% 是绿色）。

### 5.4 组件划分

| 文件 | 职责 |
|---|---|
| `frontend/src/app/(app)/plan/page.tsx` | 页面壳：取数、状态、布局 |
| `frontend/src/components/plan/PlanPanel.tsx` | 主容器：三段编排与加载/空/错态 |
| `frontend/src/components/plan/OutlookCard.tsx` | 明日市场预期（基调 + 维度条 + 关键位） |
| `frontend/src/components/plan/PlanItemList.tsx` | 明日预案清单（逐票分组 + 条目） |
| `frontend/src/components/plan/ReviewCard.tsx` | 今日复盘（兑现统计 + 待办） |
| `frontend/src/lib/api/advanced.ts` | 追加 3 个 API 函数 + 类型 |

### 5.5 数据获取

- `GET /api/battle-plan?date=` → 今日日报；404 → 显示「该日计划尚未生成」+ 「生成今日计划」按钮（**不显示空白**）
- `POST /api/battle-plan/generate` → 生成（按钮进入 loading，显示进度提示「正在采集 11 只票的行情…」）
- 生成成功后自动刷新 GET
- 请求 `{timeout: 60000}`

### 5.6 首屏与空态

- **未生成**：展示目标股票池概览（11 只：持仓 5 / 关注 6）+ 说明 + 生成按钮。**不留大片虚空**。
- **生成中**：骨架屏 + 进度文案。
- **生成失败**：错误提示 + 重试按钮（失败原因要具体，如「大盘数据不可用」而非「未知错误」）。

---

## 六、错误处理与降级

| 故障 | 表现 | 降级策略 |
|---|---|---|
| 单票 K 线拉取失败 | 该票无预案 | `meta.degraded_reason` 记「002185.SZ K线不可用」，**其余票照常产出** |
| 单票指标计算失败 | 同上 | 同上 |
| 大盘 K 线不可用 | 明日预期「数据不足」 | `stance="unknown"`，4 维度全 missing，卡面显示「明日预期：数据不足，暂不给出方向」 |
| 涨跌家数不可用 | 该维度 missing | `dims_effective` 减 1 |
| 板块资金不可用 | 该维度 missing | 同上 |
| 持仓读取失败 | 股票池只剩关注票 | 复盘段的持仓部分标注「持仓读取失败」 |
| 流水读取失败 | 兑现比对只判触及不判执行 | `fulfillment` 只有 touched/missed，note 标注「流水不可用，未核对执行」 |
| 目标交易日推算不出 | `target_date` = D+1 自然日 | `meta.target_date_estimated = true`，卡面标注「（按工作日推算）」 |
| 决策引擎返回空 actions | 该票无操作预案 | 该票在清单里显示「当前无操作预案 · 明日仅观察」，**不整票隐藏** |

**贯穿原则**：缺数据 → 该项 `None` + 写入 `degraded` 标记，**绝不编数字、绝不静默隐藏整块内容**。

---

## 七、测试策略（TDD）

### 7.1 后端单测（纯函数，无 IO）

**`outlook_service`**（目标 ≥ 12 条）
- 四维度各自：偏多 / 中性 / 偏空 / 缺失 四种输入 → 断言 score、state、detail 文本
- 结论合成：`N=0` → unknown；`S=+1,N=1` → neutral（**N≥2 门槛**）；`S=+2,N=2` → bullish；`S=-1,N=1` → bearish（**不对称门槛**）
- 关键位：MA5 ≥ close 时不作支撑；缺 low/high 时该位不出现
- 边界：K线 5 根 / 10 根 / 30 根时的缺失判定

**`plan_item_builder`**（目标 ≥ 10 条）
- `now` / `armed` / `blocked` 三路分流正确
- `build_todos` 只收 `now`，且与 `build_items` **不重叠**（同一动作不会同时出现在两边）
- `invalid_if` 四类计算（含 ×0.97 / ×1.03 边界）
- 无持仓票不产生 stop / t_plan 项
- `do_not` 项 `direction="none"`、`trigger_price=None`
- 空 actions → 返回空列表（不报错）

**`fulfillment_checker`**（目标 ≥ 8 条）
- sell 类 `high >= trigger` → touched；`high < trigger` → missed
- buy 类 `low <= trigger` → touched
- 流水有对应操作 → executed（优先于 touched）
- `direction="none"` → n_a
- T 计划双子项独立判定
- 纪律问题标记（do_not + 今日有操作）

### 7.2 后端集成测试

**`battle_plan_service`**
- 目标股票池：持仓 ∪ 关注 去重（mock 两个来源）
- 超过 20 只时截断且 `truncated=true`
- 单票失败 → 其余票照常产出 + degraded 记录
- 同日重复生成 → 幂等（plan 行数不变）
- 已有非 pending fulfillment 的日报重新生成 → items 不被冲掉

### 7.3 前端

- `npm run typecheck` 零错误
- `npm run build` 通过（**必须先停 dev server**，二者共用 `.next`）
- tabbit / Playwright 实拍：**1510px / 1280px / 1024px / 820px** 四档
  - 1510px：两栏、预案条目完整、颜色合规（红买绿卖）
  - 1024px：两栏不塌
  - 820px：单栏，顺序为「预期 → 预案 → 复盘」
  - 四档均 `scrollWidth == clientWidth`（无横向滚动）
  - **控制台零 error**
- 空态实拍：未生成时**首屏无大片虚空**

### 7.4 全量回归

- 后端 `pytest` 全量 **0 failed**（当前基线 1121 passed）
- `ruff` 全过

---

## 八、本轮明确不做（YAGNI）

| 不做 | 理由 |
|---|---|
| 明日预期算法的**回测验证** | 价值高但工作量大（需历史 K 线逐日重放 + 基准定义）。**列为阶段 9.5**，本期先上，规则参数后续用回测校准 |
| 条件单 / 自动挂单 | 涉及真实交易风险，且与「明日预期」是两条独立链路 |
| 消息面 / 舆情进入明日预期 | 数据源不硬（iFind 事件源未接），会引入不可验证的输入 |
| 多账户 / 资金拆分 | 当前只有默认账户 1 |
| LLM 白话润色层 | 确定性优先；卡面文案模板拼装已足够 |
| 移动端 / PWA 适配 | 本期只做 Web 响应式 |
| 计划与模拟盘联动 | 模拟盘已有独立账本，联动属于另一条链路 |

---

## 九、影响文件清单

### 后端（新增）
```
backend/app/services/outlook_service.py
backend/app/services/plan_item_builder.py
backend/app/services/fulfillment_checker.py
backend/app/services/battle_plan_service.py
backend/app/repositories/battle_plan_repo.py
backend/app/api/battle_plan.py
backend/tests/test_outlook_service.py
backend/tests/test_plan_item_builder.py
backend/tests/test_fulfillment_checker.py
backend/tests/test_battle_plan_service.py
```

### 后端（修改）
```
backend/app/models/orm.py                     # +2 表（BattlePlan / BattlePlanItem）
backend/migrations/versions/<new_rev>_add_battle_plan_tables.py   # 新增迁移，down_revision="f6a7b8c9d0e1"
backend/app/main.py                           # +路由注册 battle_plan_router
```

### 前端（新增）
```
frontend/src/app/(app)/plan/page.tsx
frontend/src/components/plan/PlanPanel.tsx
frontend/src/components/plan/OutlookCard.tsx
frontend/src/components/plan/PlanItemList.tsx
frontend/src/components/plan/ReviewCard.tsx
```

### 前端（修改）
```
frontend/src/lib/api/advanced.ts     # +3 API + 类型
frontend/src/lib/types.ts            # +计划相关类型
frontend/src/components/shell/       # 侧边栏加「作战计划」入口
```

### 文档
```
docs/roadmap.md                     # 阶段 9 登记
docs/design/trading-desk-v3-decision-card.md  # 与卡面文案的约束对齐（口径一致性）
```

---

## 十、与项目既有铁律的一致性自查

| 铁律 | 本设计的遵守方式 |
|---|---|
| 全部数据真实，零 mock | 四个维度全部取自真实接口（上证日K / sentiment / sector flow / 持仓 / 流水）；缺数据降级为 `missing` + `degraded`，不填假值 |
| LLM 只翻译不计算 | **本设计完全不用 LLM**；所有数字来自规则与显式四则运算 |
| 决策层纯函数、零 IO、零 LLM | `outlook_service` / `plan_item_builder` / `fulfillment_checker` 均为纯函数，只接受已取好的数据 |
| 价格必须来自 indicators/报价/持仓或其显式四则运算 | 触发价直接取决策引擎 `action["price"]`；`invalid_if` 的 ×0.97 / ×1.03 为显式四则运算 |
| 统一用 `effective_price(ctx)` | 转换层不自行取价，触发价一律继承决策引擎已算好的值 |
| 缺数据 → `None` + 写 `degraded` | 每个降级点均已列在 §6 |
| 回测闸门先定、事后不得下调 | 明日预期规则的参数（1.10 / 0.90 / 60% / 40% / MA5 / MA10）**先定死**；未来回测校准时**只能改参数、不能事后调门槛来美化结论**（与阶段 8 同纪律） |
| 红=买/看多/涨，绿=卖/看空/跌 | §5.3 已明确，浮盈用红、浮亏用绿 |
| 首屏不留大片虚空 | §5.6 已明确空态/加载/错误三态 |
| 不承诺收益 | 明日预期文案只写「倾向」+ 必带「非预测」标注；兑现未触发不评价对错 |

---

## 十一、验收标准

1. `GET /api/battle-plan` 返回结构符合 §4.7 契约，**目标股票池为持仓 5 + 关注 6 去重后的实际只数**
2. 每条预案项都有 `trigger_price`（或 `None` 且有说明）、`trigger_condition`、`basis`（非空）、`invalid_if`（非空，除 `do_not`）
3. `now` 状态的决策项**不出现在**明日预案，出现在今日复盘待办
4. 明日预期 `dims` 恰好 4 项，每项有 `state` 与 `detail`；`dims_effective` 与实际非 missing 项数一致
5. 明日预期文案含「非预测」标注；stance 为 `unknown` 时**不给出方向**
6. D 日报生成后，D+1 生成日报时 D 日报的 items 被回填 `fulfillment`，且 D+1 的 `review.fulfillment` 统计与 D 日报 items 状态一致
7. 后端全量 `pytest` 0 failed；`ruff` 全过
8. 前端 `typecheck` 零错误、`build` 通过
9. tabbit 实拍 1510/1280/1024/820 四档：布局正确、颜色合规、无横向滚动、控制台零 error
10. 未生成时的首屏**无大片虚空**
11. `docs/roadmap.md` 登记阶段 9
