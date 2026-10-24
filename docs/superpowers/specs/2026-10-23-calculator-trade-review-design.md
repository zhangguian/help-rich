# 计算器决策化 + 委托流水录入增强 — 设计文档

- 日期：2026-10-23
- 状态：已批准（实施中）
- 关联实施计划：canonical Plan（2026-10-23 批次）
- 上游设计：`docs/superpowers/specs/2026-10-21-stock-decision-engine-design.md`（决策引擎七问）

---

## 1. 背景与目标

现有计算器（`POST /api/calculator` + `CalculatorPanel`）只回答「这笔成交后持仓长什么样」和 21 档盈亏表，**不回答用户真正在问的三件事**：

1. 我这笔拟买卖**对不对**？
2. 现在**适合做 T 吗**？
3. 做 T 的**时机分别是什么**？

决策引擎（`backend/app/services/decision_service.py`）其实已经实现了这些判定（`judge_t_plan` / `judge_entry` / `judge_exit` / `judge_loss_plan` / `judge_do_not` / `build_decision`），但计算器**没有接**。本设计新增一个「拟操作 × 决策结论」的**比对层**，不重写任何决策算法。

同时扩展委托流水录入（`TransactionForm`），让用户在录入前就能看到对持仓的影响。

## 2. 已拍板的口径

| # | 决策 | 取值 |
|---|---|---|
| D1 | 002185 成本锚点 | 锚 2026-10-23 券商真值（1000 股 / 17021.46 / 均价 17.021）；历史流水冻结 |
| D2 | 缺失 5 笔流水 | 补录全部 5 笔（被基准吸收，不双算） |
| D3 | 交易费用字段 | **不加**。成本维持「不含费」口径 |
| D4 | 判定档位 | 三档 + 理由：✅符合条件 / ⚠️有条件可做 / ⛔不建议 |

## 3. 架构

```
┌─ 前端 ────────────────────────────────────────────────┐
│ CalculatorPanel                                       │
│   ├─ POST /api/calculator          (300ms debounce)   │
│   │     └─ before / after / pnl_grid(21 档)           │
│   └─ POST /api/calculator/review  (800ms debounce)   │
│         └─ verdict 三档 + reasons/blockers            │
│              + price_check / size_check               │
│              + t_assessment(做 T 时机)                │
│              + position_after / risk_flags            │
└───────────────────────────────────────────────────────┘
                          │
┌─ 后端 ────────────────────────────────────────────────┐
│ app/api/calculator.py        API 层(薄)               │
│   └─ app/modules/calculator/service.py   IO 编排层    │
│        ├─ fetch_klines(300) → compute_indicators      │
│        ├─ QuoteService().get_quotes                   │
│        ├─ portfolio.service.get_position              │
│        ├─ market_context_service.get_market_context   │
│        └─ decision_service.build_decision  (纯函数)   │
│             └─ app/services/trade_review_service.py   │
│                  (纯函数 · 零 IO · 零 LLM)             │
│                       └─ core/cost_engine             │
│                            (calculate_after_transaction)│
└───────────────────────────────────────────────────────┘
```

**铁律遵守**：判定层是纯函数（零 IO / 零 LLM / 零网络），所有价格来自 indicators / 实时报价 / 持仓 / 显式四则运算；缺数据 → `None` + `degraded`，绝不编数字。

## 4. 纯函数层 `app/services/trade_review_service.py`

### 4.1 常量

| 常量 | 值 | 含义 |
|---|---|---|
| `PRICE_TOLERANCE` | `0.02` | 拟成交价与建议价偏离 ≤2% = 价位合适 |
| `SELL_TRIM_RATIO` | `1/3` | 减仓建议：每次减 1/3 |
| `T_BASE_POSITION` | `{"≥70%": 0.70, "≥50%": 0.50}` | 底仓比例（来自 `t_plan.base_position_pct`） |

### 4.2 输入 / 输出

```python
@dataclass(frozen=True)
class ProposedTrade:
    action: Literal["buy", "sell"]
    shares: int
    price: float

def review_trade(ctx: DecisionContext, decision: dict,
                 proposed: ProposedTrade, position: Position | None) -> dict
```

输出结构：

```jsonc
{
  "verdict": "ok" | "conditional" | "not_recommended" | "unknown",
  "headline": "…",
  "reasons":   ["支持本次操作的依据"],
  "blockers":  ["反对本次操作的依据"],
  "price_check": {"suggested": 17.42, "your_price": 16.19, "verdict": "ok", "note": "…"},
  "size_check":  {"suggested_shares": 333, "your_shares": 200, "note": "…"},
  "t_assessment": {
    "suitable": false, "t_high": null, "t_low": null,
    "sell_trigger": "", "buyback_trigger": "",
    "your_price_in_range": null, "max_t_shares": null, "note": "…"
  },
  "position_after": {"shares": 800, "avg_cost": "17.021",
                     "total_cost": "13616.80", "realized_pnl": "-266.05"},
  "risk_flags": ["清仓"],
  "degraded": ["市场环境不可用"]
}
```

### 4.3 判定流程（规则固定、可单测）

1. **数据充分性**：`indicators.position.p20/p80` 缺失 或 K 线 < `MIN_KLINES_FOR_SIGNAL`(23) → `verdict="unknown"` + degraded。
2. **方向结论**：buy → `kind ∈ {entry, add}`；sell → `kind ∈ {exit, stop}`。
   - 有 `status=="now"` → `ok`
   - 有 `status=="armed"` → `conditional`
   - 有 `status=="blocked"` → `not_recommended`
   - 无相关动作：buy 且有 now 的 exit/stop → `not_recommended`；sell 且有 now 的 entry/add → `conditional`；否则 `conditional`。
3. **价位检查**：sell 优先取 `stop` 再取 `exit` 的建议价；buy 优先取 `add` 再取 `entry`。
   - buy：`your ≤ suggested × 1.02` 合格，否则 `conditional`（追高）
   - sell：`your ≥ suggested × 0.98` 合格，否则 `conditional`（价差没拿到）
   - 无建议价 → 跳过 + degraded
4. **数量检查**：
   - sell：命中 `stop` → 数量不限；否则 `your > 持仓 × 1/3` → `conditional`（分批减仓）；`your == 持仓` 且未触发止损 → `conditional`（清仓是重大决策）
   - buy：`your_price × your_shares > 持仓市值 × 0.5` → `conditional`（单笔加仓过大）
5. **冲突项**：`decision.do_not` 每条 → `blockers`；命中「下跌通道中不要抄底」且 buy → **强制 `not_recommended`**；其它命中且原为 `ok` → 降为 `conditional`。
6. **止损检查**：buy 且现价 < 止损价 → `not_recommended`；sell 且现价 < 止损价 → 加 `reasons`（符合止损纪律）。
7. **做 T 评估**（完全复用 `decision.t_plan`，不重算）：
   - `suitable=False` → 原文带出 `unsuitable_signals`
   - `suitable=True` → 带出 `t_high/t_low/sell_trigger/buyback_trigger`；
     `max_t_shares = floor(持仓 × (1 − 底仓比例))`；
     sell 且超出 `max_t_shares` → 提示「超出部分属于减仓/清仓，不是做 T」；
     sell 且 `your ≥ t_high × 0.98` → 「价位适合 T 的卖腿」；
     buy 且 `your ≤ t_low × 1.02` → 「价位适合 T 的买回腿」。
8. **风险标记**：清仓 / 单笔加仓过大 / 买入后均价升幅 > 10%。
9. **verdict 取最严**：`not_recommended > conditional > ok`。
10. **degraded 汇总**：`data_quality.degraded` + `market_env.degraded` + 本层缺失项。

### 4.4 不做的事

不做均线/量能再判定、不自己算 T 区间、不自己算止损价 —— 全部取自 `build_decision` 输出，避免与决策引擎打架。

## 5. IO 层 `app/modules/calculator/service.py`

- 装配 `DecisionContext`，样板照抄 `app/api/stock.py:107-191`（K 线 300 根 → `compute_indicators` → 报价 → 持仓 → 市场环境）。
- 降级：持仓读失败 → 按空仓 + degraded；行情失败 → 用 K 线最新收盘价；市场环境失败 → `MarketContext(degraded=["市场环境不可用"])`；**只有 K 线完全不可用才 502**。
- 缓存：TTL 60s，**只缓存慢的三件**（K 线 / 指标 / 市场环境）；**持仓与实时价每次现取**。

## 6. API

| 端点 | 用途 | 性能 |
|---|---|---|
| `POST /api/calculator` | 现状不变：before / after / 21 档 | 纯算术，300ms debounce |
| `POST /api/calculator/review` | 新增：三档判定 + T 评估 | 拉 K 线 + 大盘，800ms debounce |

`review` 复用 `CalculatorRequest` body（`stock_code` / `action` / `tx_shares` / `tx_price`）。卖出超额 → 422 `INSUFFICIENT_SHARES`（与 `/calculator` 同文案）。

## 7. 前端

### 7.1 语义色（只用语义 class，不碰行情色）

| 档位 | class | 色 |
|---|---|---|
| ✅ 符合条件 | `success` | 绿 |
| ⚠️ 有条件可做 | `warn` | 琥珀 `#F5A524` |
| ⛔ 不建议 | `danger` | 红 |
| ❓ 数据不足 | `warn` + 降级说明 | 琥珀 |

行情色 `up`(红) / `down`(绿) 只用于价格与涨跌；`accent`/`info`(青 `#22D3EE`) 只给选中/焦点。

### 7.2 组件

- **判定卡**：三档徽章 + `headline` + `reasons`(✅) / `blockers`(⛔) + `price_check` / `size_check`。
- **T 评估卡**：不适合 → 琥珀徽章 + `note` 原文；适合 → 绿徽章 + `t_high`/`t_low` + 两条触发条件 + 你的价在区间位置 + `max_t_shares`。
- **录入试算**（`TransactionForm`）：复用 `POST /api/calculator` 显示「录入后：xxx 股 @ 均价 / 已实现 ±xx」。
- **流水表**（`TransactionTable`）：新增「录入后持仓」列（`sharesAfter` / `totalCostAfter` / `realizedAfter`，`TransactionOut` 已含；旧流水为 NULL → 显示「—」）。

### 7.3 视觉流程

判定卡 / T 卡的布局与配色**先出独立 HTML 预览稿**（`docs/design/preview/trade-review-preview.html`，四态 + T 两态，真实数据），用户看过点头后才动源码。

### 7.4 前端落地口径（2026-10-23 实施记录）

落地文件：

| 文件 | 变更 |
|---|---|
| `frontend/src/components/calculator/TradeReviewCard.tsx` | 新增。`TradeReviewCard`（判定卡）+ `TAssessmentCard`（做 T 卡），纯展示无 hooks |
| `frontend/src/components/calculator/CalculatorPanel.tsx` | 接入 `POST /calculator/review`（800ms debounce / timeout 30s / `validateStatus` 不弹 toast），两张卡插在输入卡与实时结果卡之间 |
| `frontend/src/components/transaction/TransactionForm.tsx` | 录入前实时试算（复用 `POST /calculator`，600ms debounce）+ 基准语义提示（409 `TX_ABSORBED` / 422 `INSUFFICIENT_SHARES`） |
| `frontend/src/components/transaction/TransactionTable.tsx` | 新增「录入后持仓」列（`sharesAfter` / `totalCostAfter`，NULL → 「—」+ tooltip） |
| `frontend/src/lib/api.ts` | 新增 `apiErrorMessage()` / `apiErrorCode()`：后端业务错误藏在 `detail` 里，axios 的 `e.message` 只有 "Request failed with status code 422" |

**两处与视觉稿/既有约定的分歧（有意为之，改口径都是一行）**

1. **买入=绿 / 卖出=红**（`TradeReviewCard.tsx` 的 `ACT_CLS`）。
   视觉稿用的是 A 股直觉「买红卖绿」，但 App 既有约定是**买绿卖红**
   （`CalculatorPanel` 的方向单选、`TransactionTable` 的操作列都是这个）。
   判定卡与它们同屏，统一到既有约定更不容易看晕。
   要切回「买红卖绿」只改 `ACT_CLS` 一处。
2. **标题不重复**：后端 `headline` 自带档位前缀（「有条件可做 · …」），
   前端只在 `headline` **不以**档位开头时才补前缀（见 `TradeReviewCard` 的 `startsWith` 判断）。

**顺带修掉的精度 bug（本轮引入）**

`/calculator` 原来用 `Position.avg_cost`（3 位小数量化值）做链计算。
v0.5 把 `cost_price` 精度放宽到 6 位后，真实均价可能是 `17.02146`
（17021.46 / 1000），量化值 `17.021` 会让每次试算的 `total_cost` 漂移 0.46 元，
且与 `/calculator/review` 的 `position_after` 对不上。
已改为用**未量化**均价（`total_cost / shares`，与 `ChainState.avg_cost` 同源）：
买 100 @ 16.190 → 新均价 `16.946` / 持仓资金 `¥18,640.46`（原 `16.945` / `¥18,640.00`）。

**「录入后持仓」列的 NULL 语义**

`shares_after` 只对**基准之后**的流水有值。被基准吸收的历史流水
（002185 的 10-23 之前全部）必然是 NULL → 显示「—」。
所以当前主库里该列全是「—」是**正确**的，不是没渲染；
新增一笔流水后该行就会显示「1,100 股 @ 16.946」。

### 7.5 计算器布局优化(2026-10-24 实施)

用户看完首版落地后反馈「布局排版优化一下,现在不好查看」。定位到的 8 个成因与改法:

| # | 成因 | 改法 |
|---|---|---|
| 1 | 判定结论在第二屏中部 | 结论条提到弹窗最顶(打开即读) |
| 2 | 判定卡长、T 卡短 → 右列大片留白 | T 卡不再独占一列,与依据同列上下排 |
| 3 | 支持/反对纵向堆叠,理由一多就拉长页面 | 改左右两列并排 |
| 4 | 「成交后持仓」埋在卡底,要滚才看到 | 提到输入条下方,一行摘要 |
| 5 | 价位/数量检查挤在小格里折行 | 改一行两段,标签小字 + 值等宽 |
| 6 | 弹窗 `xl` 只有 896px,21 档热力图压成一团 | 新增 `2xl` 档(1280px) |
| 7 | 持仓列表内滚 + 弹窗外滚,两层滚动打架 | 列表限高 302px,只留一层滚动 |
| 8 | 理由正文 12px 发糊 | 正文 13px / 行高 1.5,11px 只给辅助信息 |

**新布局(五段式)**:① 结论条 → ② 预交易输入条 + 成交后摘要行 → ③ 双栏(持仓列表 296px | 做T判断 + 判定依据)→ ④ 检查条 → ⑤ ±10% 热力图。

**改动文件**

| 文件 | 改动 |
|---|---|
| `frontend/src/components/ui/LiquidModal.tsx` | 新增 `2xl` 尺寸档(`max-w-[1280px]`)。**没有改 `xl`** —— `xl` 被工作台「持仓体检」弹窗共用,加宽会误伤 |
| `frontend/src/app/(app)/page.tsx` / `components/settings/HistoryToolsCard.tsx` | 两处计算器弹窗 `size="xl"` → `size="2xl"` |
| `frontend/src/components/calculator/TradeReviewCard.tsx` | 拆成 `VerdictBar`(结论条)/ `TAssessmentCard`(做T)/ `WhyPanel`(依据两栏)/ `ReviewChecks`(检查条);T 卡加**区间外价格标记** |
| `frontend/src/components/calculator/CalculatorPanel.tsx` | 重排为五段式;`ResultGrid` 6 宫格移除,信息并入摘要行;方向 radio 改分段按钮;加 `data-testid` 便于真机断言 |
| `frontend/src/components/charts/PnlHeatmap.tsx` | **复用,未改** |

**实施中的取舍**

1. **热力图配色以项目组件为准**:视觉稿画的是「盈利绿」,但项目 `PnlHeatmap` 用 `up-rgb`(盈利红)/ `down-rgb`(亏损绿) 的 A 股口径。
   落地直接复用组件 → 视觉稿**不是**配色真相源。
2. **「已实现(毛)」不再单列**:原 `ResultGrid` 6 宫格里的毛/净两档,摘要行只给净额。
   费用模型当前默认关闭(毛=净),开启时净额已包含扣费。
3. **区间外价格用短标 `你的 17.00 ↑`**:视觉稿的长文案「(在区间上方)」与「T 高点(卖出)」标题区视觉拥挤。
   区间外的标记用**中性色**(不是 accent),避免被误读成「在区间内」。
4. **弹窗宽度不改变 `xl` 档**:共用方(持仓体检弹窗)不受影响。

**真机实测(tabbit,2026-10-24)**

| 场景 | 断言 | 结果 |
|---|---|---|
| A 000066 买入 200@11.780 | 结论条「⛔ 不建议」+ 反对 3/支持 0;T 卡「不适合」;摘要 `当前 200 股 @ 18.616 / 成交后 400 / 15.198 / ¥6,079.20`;热力图 21 格 | ✅ |
| B 002185 卖出 200@17.000 | 结论条「⚠ 有条件可做」;T 卡出区间条 15.290/16.860 + 两条时机 + 上限 500 股;区间外标记「你的 17.000 ↑」;摘要与 review 的 `position_after` 一致(¥13,617.17) | ✅ |
| D 卖出 5000 股 | 结论条位置显示「⚠ 这只票只剩 1000 股了,卖不出 5000 股」;**不出现半成品卡片**(T 卡/依据/检查条全部不渲染) | ✅ |
| 通用 | 无横向溢出(`scrollWidth == clientWidth`);A/B 场景 0 console error(D 场景的 2 条是刻意触发的 422 在浏览器网络层的记录,非前端异常);无 `undefined`/`NaN` | ✅ |

## 8. 测试与验收

- `backend/tests/test_trade_review_service.py` ≥18 条：三档各 ≥4、价位容差边界、减仓 1/3 边界、止损上下、do_not 冲突、T 适合/不适合/超上限/区间内外、降级、纯函数性断言。
- `backend/tests/test_calculator_api.py`：`/calculator/review` 契约、422、502。
- 后端全量 pytest 全绿（基线 1401）。
- 前端 `npm run typecheck` + `npm run build` 绿；tabbit 真机实测四态渲染、T 时机、录入试算、快照列，0 console error。

## 9. 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 其余 4 只 08-01~10-13 有 App 不知道的交易 → 只能锚券商真值，无法还原活链 | 升级路径：用户导出完整流水后可改成全活链 |
| R2 | D1 代价：002185 的 9 笔流水全部 409 不可编辑 | 用户明确选择 |
| R3 | 已实现盈亏非券商真值（-266.05 是 App 口径） | 持仓页可手填覆盖 |
| R4 | D3 导致成本与券商恒差 ~0.05% | 用户接受，写进 UI 说明 |
| R5 | review 端点首次调用 2~5s | 60s TTL 缓存 + loading 态 |
| R6 | 补录触发诊断评分 | 清理补录产生的 `trade_scores` |
| R7 | `cost_price` 精度 3→6 放宽了 API 契约 | 只放宽不收紧，前端正则同步 |
| R8 | 依赖 `decision_service` 输出结构 | 该文件不改，只读消费 |

---

# 附录 A：做 T 方向判定(正T / 反T)— 2026-10-24

## A.1 需求

原判定只回答「适不适合做 T」，不回答「做哪种 T、做多少股」。
本次补齐三件事：

1. **正T / 反T 两个方向都写出来**，并指出**更适合哪一种**。
2. **正T 给股数上限**（反T 本来就有）。
3. **账户资金可填写** —— 正T 的买入腿要先掏钱，没有资金就算不出股数。

## A.2 术语（写死，不许含糊）

| 方向 | key | 含义 | 持股数 | 隔夜风险 |
|---|---|---|---|---|
| 反T | `reverse` | 先卖后买（高抛低吸） | 不变 | 无新增 |
| 正T | `forward` | 先买后卖（低吸高抛） | 不变 | 无新增 |

**A 股 T+1 的关键约束**：当天买入的股票当天不能卖出。
所以**正T 的卖出腿只能用预留的老底仓承接** —— 这也正是「两方向股数上限同源」的原因。

## A.3 两个方向的差别只有两点

| | 反T(先卖后买) | 正T(先买后卖) |
|---|---|---|
| 资金占用 | 卖出所得即可覆盖买回（区间上沿 > 下沿） | **买入腿要先掏钱** → 受「可用资金 ÷ 买价」限制 |
| 顺序 | 先卖（不用等） | 先买 |

**股数上限公式**：

```
可动 T 仓   = floor(持股 × (1 - 底仓比例))     # 底仓比例取自 t_plan.base_position_pct
反T 上限     = 可动 T 仓                        # 不受资金约束
正T 上限     = min(可动 T 仓, floor(可用资金 ÷ 买价))
```

**买价取值**：用户拟的是买入 → 用用户拟价；否则用 T 区间下沿 `t_low`（计划低吸位）。

**整手约束**：A 股买入腿至少 1 手 → 上限向下取整到 100 的倍数。

## A.4 推荐口径

两方向都可用时：

```
现价 > P80                     → 反T（高位先卖）
现价 >= t_high                 → 反T
现价 <= t_low                  → 正T（低位先买）
区间内位置比例 >= 50%          → 反T，否则正T
```

位置比例 = `(现价 - t_low) / (t_high - t_low)`。
只有一方可用 → 推荐那一方；都不可用 → 不推荐。

## A.5 数据落点：账户可用资金

| 层 | 落点 |
|---|---|
| 表 | `account.cash_available`（VARCHAR，存字符串保精度） |
| 迁移 | `d9e0f1a2b3c4_account_cash_available` |
| 仓储 | `account_repository.get_cash_available / set_cash_available` |
| 用例 | `account_service.get_cash_available / set_cash_available` |
| 跨域入口 | `modules/portfolio/service.get_cash_available / set_cash_available` |
| API | `GET /api/accounts/{id}/cash`、`PUT /api/accounts/{id}/cash` |

**为什么落在 `account` 表而不是新建单行表**：
「资金」天然是**账户级**属性（不是全局设置，也不是某只票的属性）；
已有多账户模型（阶段5 `account` 表），挂在账户上天然支持多账户隔离；
新建单行表会与多账户模型打架 —— 多出来的账户就没有资金字段。

**NULL 语义 = 未填写**（不是 0）。判定层据此给 `max_shares = None` 并在
`prerequisite` 写明「未填写账户可用资金」。「没填」与「没钱」对用户是
两个完全不同的结论，不能混。

## A.6 契约

### 请求 `POST /api/calculator/review`

`cash_available` 是**可选覆盖值**，用 Pydantic v2 的 `model_fields_set` 区分三种情况：

| 请求体 | 含义 |
|---|---|
| 字段未传 | 用账户已保存的可用资金 |
| 传 `null` | 明确「没有可用资金」 |
| 传数字 | 本次试算用这个值（不落库） |

### 响应 `t_directions`

```jsonc
{
  "reverse": {
    "key": "reverse", "label": "反T · 先卖后买",
    "applicable": true,
    "reason_code": "ok",          // ok / no_cash / cash_too_little / no_position
                                  // / not_suitable / no_t_range / base_too_large
                                  // / no_base_ratio / unknown
    "prerequisite": "需有老底仓可卖:可动 500 股(底仓保留 ≥50%),卖出所得即可覆盖买回",
    "max_shares": 500, "max_amount": "8430.00",
    "steps": [{ "role": "sell", "text": "冲高至 16.86 元附近卖出 500 股(老仓)" },
              { "role": "buyback", "text": "回落至 15.29 元附近买回 500 股" }],
    "status_text": "可做 500 股:冲高 16.86 元卖 500 股,回落 15.29 元买回 500 股(持股数不变)"
  },
  "forward": { /* 同构;role ∈ buy / sell */ },
  "recommended": "reverse",       // reverse / forward / null
  "recommend_reason": "现价 16.19 元位于 T 区间 15.29~16.86 元的57% 位置,偏上沿,先卖后买更稳妥",
  "your_leg": "reverse.sell",     // reverse.sell / reverse.buyback / forward.buy / forward.sell / null
  "t_plus_one_note": "A 股 T+1:当天买入的股票当天不能卖出。正T 的卖出腿只能用预留的老底仓承接;反T 持股数不变,买回的部分当天也不能再卖。"
}
```

> **字段名不得含「数字段」**：前端 `camelKey` 规则是 `key.replace(/_([a-z])/g, ...)`,
> `t_plus_1_note` 会变成 `tPlus_1Note`（`_1` **不转**大写）——
> 若 TS 里写成 `tPlus1Note` 就永远拿不到值：**类型全绿、运行期 undefined**。
> 所以后端字段名用 `t_plus_one_note`。契约测试 `test_review_t_directions_keys_are_camelcase_safe`
> 会正则拦掉任何含 `_\d` 的字段名。

**`reason_code` 的用途**：前端要区分「缺资金 → 引导去填」与「真不适用 → 只灰显」。
没有这个字段，前端只能靠文案匹配（脆）。

**`applicable=false` 的方向照常显示**（灰显 + 说明原因），不隐藏 —— 用户需要知道
「有另一个方向存在，只是当前不满足条件」。

**`your_leg`** 把用户拟的这笔标到具体方向的具体腿：
`reverse.sell` / `reverse.buyback` / `forward.buy` / `forward.sell` / `null`。

## A.7 实现位置

| 文件 | 改动 |
|---|---|
| `app/services/trade_review_service.py` | 新增 `_build_t_directions()` / `_floor_lot()` / `_empty_t_directions()`；`review_trade()` 新增 `cash_available` 参数，返回值新增 `t_directions` |
| `app/modules/calculator/service.py` | 新增 `CASH_UNSET` 哨兵；`review_proposed_trade()` 读账户资金并下发 |
| `app/api/calculator.py` | 新增 `ReviewRequest` / `ReviewTDirection` / `ReviewTStep` / `ReviewTDirections` |
| `app/api/accounts.py` | 新增 `GET/PUT /accounts/{id}/cash` |
| `app/models/orm.py` | `Account.cash_available` |
| `migrations/versions/d9e0f1a2b3c4_*.py` | 加列（幂等） |

**不动 `decision_service` / `t_plan`** —— 判定层只消费它们的输出，不重写算法。

## A.8 前端落地口径

| 位置 | 改动 |
|---|---|
| `frontend/src/lib/types.ts` | 新增 `ReviewTDirection` / `ReviewTStep` / `ReviewTDirections` / `AccountCash`；`TradeReviewResponse` 加 `tDirections` |
| `frontend/src/components/calculator/TradeReviewCard.tsx` | `TAssessmentCard` 重写为「推荐条 + 两行对照 + 资金输入」；新增 `DirectionRow` / `CashInput`；删除旧的 `Trigger` / `MetaChip` |
| `frontend/src/components/calculator/CalculatorPanel.tsx` | 打开弹窗时读账户资金；输入停顿 600ms 自动保存；review 请求带上 `cashAvailable` |

**视觉口径**（与视觉稿一致，按项目 token 落地）：

- 推荐方向：`accent`（青）描边 + 标题用 accent 色 + 「更适合」标签
- 不适用方向：整行 `opacity-70` + 虚线「当前不可用」标签 + 「为什么不能做 · <原因>」
- 缺资金：**琥珀**提示条（`warn`）+ 「⚠ 未填写账户可用资金」+ 「缺资金」标签
- 你拟的这笔：● 实心圆点 + 红色 `up` 小徽章「你拟的这笔」（`up` 是**价格语境**的方向标，与判定徽章不冲突）
- 股数上限算不出来 → 显示「—」，**不显示 0**（0 会被读成「一股都不能做」）

**「卖出时机 / 买回时机」两格已删除** —— 被两行对照的 steps 按方向重组覆盖
（反T 的两步 = 卖 + 买回；正T 的两步 = 买 + 卖）。后端 `t_assessment` 字段保留不变。

**账户资金的三个语义**（务必分清）：

| 场景 | 请求 | 效果 |
|---|---|---|
| 用户没填 | `cashAvailable: null` | 正T 灰显 + 缺资金 + 上限「—」 |
| 用户填了 | `cashAvailable: <数字>` | 正T 给出股数上限（受资金卡） |
| 用户清空 | `cashAvailable: null` + PUT `null` | 回到「未填写」（不是 0） |

## A.9 实施记录

- 后端全量 **1487 passed**（基线 1450，新增 37 条：判定 24 + API 契约 7 + 账户资金 API 6）。
- 架构守卫 `test_architecture_boundaries.py` 全绿 —— 跨域只走 `modules.<other>.service`，无新增基线违规。
- 前端 `tsc --noEmit` 绿、`next build` 绿。
- **tabbit 真机实测**（1510×1100 视口）：
  - 002185 卖 200@17.000，无资金 → 正T 灰显 +「缺资金」+「上限 —」+ 琥珀提示条；反T 上限 500 股 ¥8,430
  - 同上，填 20000 → 正T 上限 500 股 ¥7,645；推荐理由从「正T 不可用」切换为价位位置判断
  - 同上，填 3000 → 正T 被资金卡到 **100 股** ¥1,529（3000 ÷ 15.29 ≈ 196 → 整手 100）
  - **重开弹窗 → 资金读回 3000.00**（持久化生效）
  - 002185 买 100@15.300 → `your_leg` 正确映射为买回腿；正T 买价取用户拟价 15.30（¥7,650）
  - 卖 5000 → 422 文案「这只票只剩 1000 股了,卖不出 5000 股」，不出半成品卡
  - 全场景：无横向溢出（scrollWidth == clientWidth）、无 `undefined`/`NaN`、0 console error
- 视觉稿：`docs/design/preview/t-directions-preview.html`（真实数据 + 1 个明确标注的派生示意场景）。

## A.10 风险

| # | 风险 | 缓解 |
|---|---|---|
| R9 | 正T 的股数依赖用户填写的资金，填错就给出错误上限 | 输入框旁明写「影响正T 的股数上限」；填错由用户自己承担，判定层不猜 |
| R10 | 可动 T 仓比例来自 `t_plan.base_position_pct`（≥50%/≥70%），换策略会变 | 口径写死在本文件，改动必须同步改文档 |
| R11 | 「底仓可动量」是**持仓内部**划分，与「当日可卖股数」不是一回事（后者未建 T+1 模型） | 两方向都只用老底仓卖出，方向上自洽；真正的 T+1 约束留待 `shares_available_at` 建模后细化 |

