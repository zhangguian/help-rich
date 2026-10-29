# 作战计划 v2 · 沪深全市场滚动池 + 三栏工作台 设计文档

> 2026-10-25 · 承接 [每日作战计划（复盘 + 明日操作预期）设计文档](./2026-10-21-daily-battle-plan-design.md)
> 本文是**增量设计**：v1 已落地的复盘 / 预期 / 逐票预案三段内容口径**不变**，
> v2 只改两件事：**选股范围**（持仓 ∪ ★关注 → 沪深全市场主板滚动池）与**页面骨架**（两栏 → 三栏）。

---

## 一、问题陈述

### 1.1 现状的三个硬伤

| 硬伤 | 具体表现 | 后果 |
|---|---|---|
| **选股范围太窄** | 每天只覆盖「持仓 ∪ ★关注」（用户实况 17 只） | 用户看不到池外的机会；选股模块已建好却用不上 |
| **每天重新选** | 股票池与昨日预案无关，今天选什么完全由今天的钱包决定 | 「昨天盯的那只今天怎么样了」没有记忆，无法形成复利 |
| **视线来回跳** | 「今天盯哪些票」和「每只票要做什么」分散在长列表里 | 用户得先滚到中栏，再从 50+ 条预案里反推自己盯的是哪几只 |

### 1.2 用户诉求（原话）

> 作战计划 的页面优化一下，同时筛选的股票不极限于关注的股票，而是沪深的股票（排除北交所和创业板）。

### 1.3 v2 要交付的三件事

1. **滚动池**：沪深全市场主板里选出一小池（5 只）每天跟进，带记忆地留池 / 剔除 / 补位。
2. **「最新的操作要求是什么」**：每只票一行，写死下一步动作。
3. **三栏工作台**：左 = 股票锚点栏 + 今日复盘，中 = 逐票作战计划，右 = 明日市场预期。

---

## 二、已确认的产品口径（两轮问卷确认，不得再自行改动）

| # | 口径 | 结论 |
|---|---|---|
| P1 | 覆盖范围 | **自选（持仓 ∪ ★关注）全覆盖** + **全市场滚动池 5 只**，两段各自完整覆盖、不互相挤占 |
| P2 | 「达到预期」的定义 | `touched`（已触及）或 `executed`（已执行）都算 |
| P3 | 连续天数的累计 | **只有 `missed` 累计**；`no_data` / `n_a` / `pending` **不累计**（不因缺数据惩罚股票） |
| P4 | 复盘位置 | 放**左栏底部**（与锚点栏同一条视线） |
| P5 | 补位排序 | **复用选股模块的 4 因子打分**（主力净流入 / 量比 / 动能 / 板块强度） |
| P6 | 成交额下限 | **1 亿元** |
| P7 | universe | 沪深**主板**、非 ST、非次新、成交额 ≥ 1 亿（排除北交所 / 创业板 / 科创板） |

---

## 三、选股流水线（三级，逐级收窄）

```
全市场快照 5573
   │ 主板过滤（600/601/603/605/000/001/002/003，排除 300/301/688/689/8xx/4xx/920/B 股）
   ▼
主板 3193
   │ ST 前缀剔除（ST / *ST / SST，用前缀判定，不做子串匹配）
   ▼
非 ST 3053
   │ 成交额 ≥ 1 亿 + 次新股剔除（日 K 实际根数 < 60）
   ▼
候选 1941 ── Stage A 粗筛(快照级) ──▶ 80 只 ── Stage B 4 因子精排 ──▶ 池 5 只
```

### 3.1 为什么必须三级（而不是逐只跑决策引擎）

22 只票逐只跑决策引擎（K 线 + 市场环境 + 指标）实测 **8s+**，且 1941 只候选逐只跑**不可能在 60s 内**。
所以：**快照级粗筛 → 因子级精排 → 决策级**。只有进池的 5 只与自选 17 只才进决策引擎。

### 3.2 4 因子打分的口径（与选股页共用同一套权重）

`backend/app/modules/screener/service.py` 导出 `get_effective_weights(refresh)` 跨域出口，
池与选股页**共用同一份权重** —— 否则「选股页选出来的票」和「池里的票」会出现两套标准。

### 3.3 板块因子必须同源（实测踩坑）

板块强度因子要与资金榜**同一套分类**。实测新浪 `fenlei=1` 其实是**概念板块**（`gn_*`），
`fenlei=2` 才是**申万行业**（`hangye_*`，一只票 1:1）。
若用 baostock 证监会行业（`J66货币金融服务`）去匹配新浪板块名 → **永不相交** → 主力净流入(60 分)与板块强度(25 分)恒为 0。

因此新增 `backend/app/data/sector_constituents.py`：按 `node=hangye_*` 拉申万行业成分股，
建立 `{stock_code → node}` 映射（per-node 缓存 30 分钟，并发 10）。

---

## 四、池的记忆模型

### 4.1 为什么要有独立的表

日报的 `items` 会被次日覆盖，池是**跨天实体**，必须单独存。

```python
# backend/app/models/orm.py
class BattlePlanPool(Base):
    stock_code: str          # unique + index
    stock_name: str | None
    active: bool             # 是否仍在池中
    joined_on: date           # 入池日
    miss_streak: int          # 连续未达预期天数
    last_evaluated_on: date   # 幂等键：同日重复生成不重复累计
    last_status: str | None   # 昨日股票级兑现状态
    last_score: float | None
    last_reason: str
```

### 4.2 状态机

```
                  ┌──────────────┐
     昨日 touched ─┤              ├─→ 留池(kept)
     昨日 executed ┤   在池成员   │
     昨日 no_data ─┤              ├─→ 留池,miss_streak 不变
     昨日 missed ─┤  miss_streak │
                  └──────┬───────┘
                         │ miss_streak 达到 3
                         ▼
                   剔除(dropped) ──→ 空出席位由 4 因子分最高的候选补位(added)
```

- **股票级状态**优先级：`executed > touched > missed > no_data > n_a`
  （一只票可能有多条预案；池关心的是「这只票昨天有没有达到预期」，不是「这一条预案」）。
- **补位不回补**：被剔的票当天不再补位回来（否则「剔除」没有意义）。
- **补位不与自选重复**：池选股时排除自选代码；`_merge_scope` 再做一次去重。

### 4.3 幂等

`last_evaluated_on` 作幂等键：同一天重复点「生成」不会重复累计 `miss_streak`。
判定本身在编排层**只算一次**（`evaluate_prev_fulfillment`），池与复盘**共用这一份结果**。

---

## 五、后端设计

### 5.1 新增模块 `app/modules/stock_pool/`

| 文件 | 职责 | IO |
|---|---|---|
| `pool_logic.py` | 纯函数层：universe 闸门、指标计算、`select_pool`、`aggregate_stock_status` | **零 IO** |
| `repository.py` | `battle_plan_pool` 表读写（按 `stock_code` upsert，**不动 `joined_on`**） | 有 |
| `service.py` | Stage A/B 编排 + `build_market_pool` / `get_current_pool` / `get_universe_stats` | 有 |

架构边界（`backend/tests/test_architecture_boundaries.py`）：`modules` 之间**只准 import 对方的 `service.py`**；
每个 `modules` 域必须有 `service.py`。`stock_pool/service.py` import `screener/service.py` 符合该约束。

### 5.2 编排顺序（`battle_plan_service.build_plan` 重排）

```
① 昨日兑现判定  ← 提前!滚动池要用「昨天有没有达到预期」
② 自选(持仓 ∪ ★关注)
③ 全市场滚动池(粗筛 → 精排 → 池记忆与补位)
④ 合并 scope(自选在前,池在后)
⑤ 行情 / 明日预期 / 逐票决策
⑥ 复盘(复用 ① 的结果,不重算)
⑦ 落库
```

### 5.3 覆盖上限

```python
MAX_SCOPE = 20          # 旧值(固定 20)—— 仅作绝对兜底
SCOPE_HARD_CAP = 30     # 总覆盖硬顶(自选极多时兜底,保护 60s 生成预算)
```

实际上限 = `min(len(自选) + POOL_LIMIT, SCOPE_HARD_CAP)`。

> **为什么不再用固定 20**：用户自选实况 17 只，17 + 5 = 22 > 20，
> 沿用固定 20 会按「先砍池」把**全市场池整个挤掉** —— 正好违背「全市场永远有位置」这条产品意图。

**截断优先级**：先砍池尾 → 再砍 ★关注尾 → **持仓永不砍**。被截断时 `meta.truncated = true`，
页面上如实披露，不谎称「一只票都没砍掉」。

### 5.4 契约变更

**`GET /api/battle-plan/scope`（破坏性变更）**

```jsonc
// 旧: [{stock_code, stock_name, in_position, is_favorite}, ...]
// 新:
{
  "watchlist": [{ "stock_code": "...", "stock_name": "...", "in_position": true, "is_favorite": false }],
  "pool":      [{ "stock_code": "...", "miss_streak": 0, "last_status": null, "last_score": 135.0, "joined_on": "2026-10-25" }],
  "universe":  { "total": 5573, "main_board": 3193, "non_st": 3053, "after_filters": 1941, "min_amount_yi": 1.0 }
}
```

- `pool` 是**当前**在池成员（读表），不是「今天会选出什么」。
- 顺手堵掉 `shares` / `avg_cost` 泄漏（与 `meta.scope` 口径一致）。

**`meta` 新增字段**

```jsonc
"pool": {
  "limit": 5,
  "members": [{ "stock_code": "...", "score": 135.0, "reason": "...", "state": "kept|added",
                "miss_streak": 0, "last_status": null, "streak_note": "昨日未判定 → 不计入连续天数" }],
  "dropped": [{ "stock_code": "...", "miss_streak": 3, "reason": "连续 3 天未达预期,已剔除" }],
  "candidates_considered": 78,
  "universe": { ... }
},
"quotes": { "600519.SH": { "price": 1418.0, "change_pct": 1.24 } },
"timings": { "fulfillment": 0.14, "select_stage": 5.78, "select_pool": 0.02, "decisions": 8.02 }
```

> `quotes` 是 v2 前端落地时补的：左栏锚点栏要显示现价与涨跌幅，
> 这两个值原先只存在于编排层局部变量里，不进 `meta` 前端就拿不到。

---

## 六、前端三栏设计

### 6.1 栅格

复用 v0.8 交易台首页的同一套母体（**不另起一套宽度**）：

```
lg:grid-cols-[236px_minmax(0,1fr)_268px]
xl:grid-cols-[252px_minmax(0,1fr)_304px]
```

- 断点用 `lg`(1024)，不用 `xl`(1280) —— 沿用 spec §5.2 铁律「两栏保持到 1024px」。
- 窄屏(<1024)单栏顺序：**预期 → 锚点 → 预案 → 复盘**。
  实现手法：左栏容器在窄屏用 `display:contents`「透明」成两个独立 grid item，
  宽屏再变回纵向 flex 容器（与既有右栏写法同一手法）。
- 基础列必须写 `grid-cols-1`（= `minmax(0,1fr)`）——
  否则窄屏下隐式列按 `auto` 定尺，**内容 min-content 宽度会撑破栅格**。

### 6.2 「最新操作要求」是唯一事实源

规则（视觉稿 §05 口径）：

1. 取该票 `status_now === 'now'` 的第一条（条件已满足、待执行）；
2. 否则取 `status_now === 'armed'` 的第一条（待触发）；
3. 否则取第一条预案；
4. 都没有 → 「暂无待执行动作,仅观察」。

文案取 `trigger_condition` 的**首句**（逗号/句号切分），保留触发价与股数等关键信息。

> **左栏锚点行与中栏票头显示同一份文案。**
> 实现上二者都走 `frontend/src/lib/planDerive.ts` 的 `requirementOf(items)` —— **算一次,两处渲染**。
> 真机实测断言：19/19 只票两处文案**逐字一致**。

### 6.3 组件划分

| 组件 | 职责 |
|---|---|
| `components/plan/PlanPanel.tsx` | 编排：三栏栅格、生成中分阶段、空态摊开选股口径 |
| `components/plan/StockAnchorRail.tsx` | **新增** · 左栏锚点栏：分组、徽章、最新操作要求、兑现状态、点击定位中栏 |
| `components/plan/PlanItemList.tsx` | 中栏逐票预案：票头徽章 + 最新操作要求 + 条目（虚线分隔，去掉双层边框） |
| `components/plan/ReviewCard.tsx` | 今日复盘（**移到左栏底部**）：结论条 + 计数表 + 待办 |
| `components/plan/OutlookCard.tsx` | 明日市场预期（右栏）：结论置顶 + 四维度 + 关键位 2×2 |
| `lib/planDerive.ts` | **新增** · 纯派生层：股票级兑现聚合、需求文案、分组组装 |
| `lib/planTypes.ts` | 池 / universe / quotes 类型 + 新 `/scope` 契约 |

### 6.4 徽章语义

| 徽章 | 变体 | 说明 |
|---|---|---|
| 持仓 | `negative`(红) | 与视觉稿一致 |
| ★关注 | `info`(青) | |
| 池 · 保留 / 新补位 | `pool`(紫 `#a78bfa`) | **新增色**：复用图表 MA10 的同一个紫，不另起一套色 |
| 4 因子分 | `neutral` | |
| 昨日已执行 / 已触及 | `positive`(绿) | 达到了预期 |
| 昨日未达预期 | `negative`(红) | |
| 昨日未判定 | `neutral`(灰) | 缺数据，不惩罚 |
| 连续 N 天 | `caution`(琥珀) | |

> 徽章样式新增 `outline`（描边）模式：一排小徽章用填色会糊成一片，描边能保住各自轮廓。
> 共享 `components/ui/Badge.tsx` 扩展，不新建一套徽章组件。

### 6.5 左栏吸顶固定（滚动时不能丢）

中栏是 19 张票卡的长列表（整页约 7900px）。页面一滚，左栏跟着滚走就等于
**丢了「今天盯哪些票」** —— 视线要来回拉回顶部才能确认自己在看哪只票。

做法：**`sticky` + 限高 + 栏内滚动**（三样都要）：

```tsx
lg:sticky lg:top-3 lg:max-h-[calc(100vh-1.5rem)] lg:overflow-y-auto
```

- 只加 `sticky` **不够**：左栏内容（22 只票 ≈ 2000px）比视口高，
  纯 sticky 的超高元素底部永远够不着 —— 它会一直贴在 top。
- 必须配 `max-h` + `overflow-y-auto`：左栏自己滚，票一只都不丢。
- 窄屏（<1024）不吸顶（`lg:` 前缀），单栏堆叠时没有「并行浏览」的场景。

右栏（明日市场预期）同样吸顶（本来就吸）。

### 6.6 点锚点定位中栏：只滚外层，不动左栏

⚠️ **不能用 `el.scrollIntoView()`** —— 它会连带滚动**所有**可滚动祖先，
包括左栏那个 `overflow-y-auto` 容器 → 用户点一只票，左栏的锚点列表反而被推走了
（点了票却把自己的清单滚没了）。

正确做法：只滚外层 `main`（应用外壳的滚动容器），左栏的内部滚动位置不动：

```ts
const offset = el.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop;
main.scrollTo({ top: Math.max(0, offset - 96), behavior: 'smooth' });
```

另外：**没有预案条目的票**（决策层拿不到数据 → 被跳过）点下去不能静默无响应 ——
锚点行自身高亮（左侧一道强调色边），让用户看得见自己点到了什么。

### 6.7 锚点栏**不自动折叠**

锚点栏的职责是「今天盯哪些票、每只票要做什么」。把票藏起来等于替用户做决定
（自动折叠过一次，22 只票只剩 9 只可见 —— 实测发现后改掉）。
改为：**默认全展开**，组头可点，折叠与否由用户自己决定。

---

## 七、降级与诚实性

| 场景 | 表现 |
|---|---|
| 板块成分股不可用 | 板块两个因子记 0 分 + 降级条写明「影响了什么」；池记忆**不受影响**（昨日兑现不依赖板块数据） |
| 快照不可用 | `universe` 为 null → 空态写「全市场快照暂不可用」，不编数字 |
| 某只票决策失败 | 该票**仍出现在锚点栏**（不整块隐藏），需求显示「暂无待执行动作,仅观察」 |
| 无行情数据 | 兑现判为 `no_data` → **不累计连续天数**，锚点栏徽章「昨日未判定」 |

**不编数字**是硬约束：缺数据一律置灰占位 + 如实说明。

---

## 八、影响文件清单

### 后端（新增）
- `backend/app/modules/stock_pool/{pool_logic,repository,service}.py`
- `backend/app/data/sector_constituents.py`
- `backend/migrations/versions/e2f3a4b5c6d7_add_battle_plan_pool_table.py`
- `backend/tests/test_stock_pool_service.py`

### 后端（修改）
- `backend/app/core/stock_code.py`（`is_main_board`）
- `backend/app/core/config.py`（`POOL_*` 常量）
- `backend/app/models/orm.py`（`BattlePlanPool`）
- `backend/app/services/battle_plan_service.py`（编排重排 / `_merge_scope` / `meta.pool` / `meta.quotes`）
- `backend/app/api/battle_plan.py`（`/scope` 对象契约）
- `backend/app/modules/screener/service.py`（`get_effective_weights` 跨域出口）

### 前端（新增 / 修改）
- 新增：`components/plan/StockAnchorRail.tsx`、`lib/planDerive.ts`
- 修改：`components/plan/{PlanPanel,PlanItemList,ReviewCard,OutlookCard}.tsx`、
  `lib/planTypes.ts`、`lib/api/advanced.ts`、`components/ui/Badge.tsx`、
  `components/shell/PageShell.tsx`（新增 `wide`）、`app/(app)/plan/page.tsx`、
  `styles/tokens.css` + `tailwind.config.ts`（池紫）

### 文档
- 本文件
- `docs/superpowers/specs/2026-10-21-daily-battle-plan-design.md`（增量章节）
- `docs/api-contract/api-changelog.md`
- `docs/design/preview/plan-v2-layout.html`（视觉稿）

---

## 九、验收标准

### 后端
- [x] `/scope` 返回 `{watchlist, pool, universe}`，不回传 `shares` / `avg_cost`
- [x] `POST /generate` 真实跑通：22 只覆盖、56 条 items、`truncated=false`、`degraded=false`、11.6s
- [x] 池真实选出 5 只，入选理由含板块资金与量比因子
- [x] 昨日无行情 → `na=25 / no_data=11`，`no_data` **不写回**、不累计
- [x] 全量 pytest 绿、ruff 本轮文件无新增

### 前端
- [x] 1440 / 1024 三栏，820 单栏；四档均**无横向溢出**
- [x] 锚点栏 22 只全展示，每只一行「最新操作要求」，池徽章 5 个，每只都有现价涨跌幅
- [x] 左栏锚点行与中栏票头的需求文案**逐字一致**（19/19）
- [x] 点锚点 → 中栏定位 + 高亮；**无预案的票点下去也有反馈**（不静默无响应）
- [x] 点锚点**不搅动左栏自己的滚动位置**（`scrollIntoView` 会滚所有祖先，已改为只滚外层）
- [x] 左栏吸顶：滚动 2600px 后仍钉在顶部（railTop 167 → 12），内容超高时栏内可滚
- [x] 820 单栏顺序 = 预期 → 锚点 → 预案 → 复盘
- [x] 空态摊开真实口径（5573 → 3193 → 3053 → 1941）与当前池 5 只；**「还在统计」与「统计不出来」分开说**
- [x] 生成中分阶段报进度，阶段里的只数取真实 universe，不编数字
- [x] console / pageerror **零错**
- [x] `tsc --noEmit` 绿、`next build` 绿

### 后端回归
- [x] 全量 pytest **1719 passed / 0 failed**
- [x] ruff：本轮改动文件**零新增**（`screener/service.py` 那 7 条在 HEAD 版本一模一样存在）
