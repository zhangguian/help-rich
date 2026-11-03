# 买股工具室 · 路线图

> 创建日期：2026-10-17
> 依据：[PanWatch 对标分析](analysis/panwatch-benchmark.md) 的功能差距清单
> 当前版本：v0.5.0

---

## 一、为什么做这些

当前产品链路是：

```text
信号（screener 选股）──▶ AI 解读 ──▶ 复盘（replay / calibration）
                              │
                              ✗ 缺「验证」    ✗ 缺「触达与执行」
```

PanWatch 补上的正是中间两环：**回测/模拟盘（验证）** 与 **价格提醒 + IM 推送（触达）**。
补齐后形成闭环：

```text
信号 ──▶ 回测/模拟盘验证 ──▶ 提醒触达 ──▶ 手动/模拟执行 ──▶ 复盘校准 ──▶ 权重迭代
```

---

## 二、阶段总览

| 阶段 | 主题 | 产出 | 状态 |
| --- | --- | --- | --- |
| **0** | 工程地基 | 测试隔离、ruff、CI、README、架构守卫、数据治理 | ✅ 完成 |
| **1** | 提醒闭环 | 通知平台层 + 价格提醒引擎 | ✅ 完成 |
| **2** | 决策质量 | 选股权重可调 + 策略回测引擎 | ✅ 完成 |
| **3** | 执行验证 | 模拟盘（账本 + 净值曲线 + 绩效指标） | ✅ 完成 |
| **4** | 深度分析 | 多智能体辩论 + 三段式定时 Agent | ✅ 完成 |
| **5** | 产品完善 | 多账户、PWA、引导中心 | ✅ 完成 |
| **6** | 架构演进 | `modules/<domain>` ADR + 首批落地 | ✅ 首批(screener/portfolio) |
| **7** | 前端落地 | 阶段1–5 全部能力的 UI | ✅ 完成(见下) |
| **8** | 盯盘决策引擎 | 确定性决策卡(七问·零 LLM)+ 回测闸门 | ✅ 完成(见下) |
| **9** | 每日作战计划 | 今日复盘 + 明日市场预期 + 明日逐票预案(零 LLM 规则推断) | ✅ 完成(见下) |
| **10** | 盘中复盘 + 全局助手 + 性能 | 交易日历 / 11:30·14:00 盘中复盘(盯盘页可见) / 右下角悬浮球助手 / 前端性能 | ✅ 完成(见下) |
| **11** | 持仓侧流水录入 + 逐笔评分 | 持仓页行内录流水 + 时间节点 + 6 维 120 分评分 + 补评闭环 | ✅ 完成(见下) |
| **12** | 补T待接回清单 | 左栏第一位直列待接回票 + 不亏本接回线 + 一键录入接回 | ✅ 完成(见下) |
| **13** | 做T操作历史 + 接回后成本 | 持仓详情右栏做T台账(T前/T后成本价 + 做T盈亏 + 已实现) + 补T清单的接回后成本 | ✅ 完成(见下) |
| **14** | 成本口径改券商摊薄口径 | 成本链改追踪净投入(摊薄成本 = 券商持仓页成本价) + 用券商快照修正 5 只票基准 | ✅ 完成(见下) |
| **15** | 做T记录区分正T / 反T | 双向 FIFO 配对(正T 先买后卖 / 反T 先卖后买)+ 配对时间窗口 + 补T清单分「待接回 / 待卖出」两组 | ✅ 完成(见下) |
| **16** | 做T三档建议价 + 自动到价提醒 | 建议价分一/二/三档(每档带成本前→后,正反T方向相反)+ 每条挂单自动建到价提醒、挂单消失自动停用 | ✅ 完成(见下) |
| **17** | 提醒可见性:修渠道硬编码 + 应用内弹窗 | 到价提醒跟随全局已启用渠道(修掉只写日志的硬编码)+ 提醒触发经 SSE 推到网页内弹窗(不依赖系统通知)+ 通路自检端点 | ✅ 完成(见下) |
| **18** | 提前预警:提醒提前 1% | 每条挂单除到价提醒外再挂一条**预警提醒**(预警线 = 生效到价线朝基准线方向再退 1%)+ 清单页「预警线 · 还差」列 + 弹窗区分「准备 / 涨到跌到」 | ✅ 完成(见下) |
| **19** | Tailwind 死类名清理 + 静态门禁 | 修掉 172 处拼错的色键类名(输入框/徽章/hover 态原本**根本没有背景**)+ 补 RGB 通道变量让透明度修饰符可用 + `npm run check:classes` 门禁防复发 | ✅ 完成(见下) |

> 阶段 0–5 已把闭环打通到
> **「改了权重能回测 → 历史信号能复盘 → 命中条件能推送 → 不想真金白银就先模拟 → 多智能体出决策书 → 多个券商分开算」**。
> 阶段 6 首批完成 screener / portfolio 两个域迁移,market 域因引用面过广降级到批次 2。
> 阶段 7 补齐前端:此前所有新能力只有 API、没有入口,用户点不到。
> 阶段 8 补上「盯盘时到底该怎么办」这一层:确定性决策卡(零 LLM)+ 回测闸门,
> 并且把「这套规则到底有没有用」用回测数据回答了 —— 止盈有效、建仓只有胜率价值、止损暂不可判定。
> 阶段 9 补上「**明天怎么办**」这一层:把决策卡翻译成**明日逐票预案**
> (什么价位做什么、什么条件下作废),再用四维度规则推断给出**明日市场倾向** ——
> 全程零 LLM,是**纪律锚点不是预测器**。
> 阶段 10 补上「**盘中怎么办**」与「**随时能问**」:交易日历走真实日 K,
> 11:30 / 14:00 各做一次盘中复盘并**在盯盘页看得见**(顶栏胶囊 + 抽屉),
> AI 对话改成**右下角悬浮球**(全局、自动带当前选中票),
> 同时把「点击很卡」拆成可测的四档并逐项修(见 §阶段 10)。

---

## 阶段 7 · 前端落地 ✅

后端 124 个路由此前没有对应界面。本轮补齐 8 个路由 + 1 个设置页内嵌面板:

| 路由 | 组件 | 对应能力 |
| --- | --- | --- |
| `/screener/weights` | `components/screener/WeightsPanel.tsx` | 选股权重 UI 可调 |
| `/backtest` | `components/backtest/BacktestPanel.tsx` | 策略回测 + **权重校准对比** |
| `/price-alerts` | `components/alert/PriceAlertEditor.tsx` | 价格提醒(条件树编辑) |
| `/paper-trading` | `components/paper/PaperTradingPanel.tsx` | 模拟盘买卖与流水 |
| `/analysis` | `components/analysis/MultiAgentPanel.tsx` | 多智能体决策书 |
| `/brief` | `components/analysis/BriefPanel.tsx` | 盘前简报 / 盘中速览 |
| `/accounts` | `components/accounts/AccountsPanel.tsx` | 多账户管理 |
| `/onboarding` | `components/onboarding/OnboardingPanel.tsx` | 引导中心 |
| 设置页内嵌 | `components/settings/NotifySettings.tsx` | 通知渠道配置 |

API client 统一在 `frontend/src/lib/api/advanced.ts`,类型逐项对齐后端实际返回
(注意 axios 拦截器会把响应 snake_case 自动转 camelCase,请求体自动转 snake_case)。

### 三个前端设计取舍

1. **模拟盘不给价格输入框**。成交价必须由后端取实时行情;让用户手填就等于虚构
   成交价,模拟结果毫无参考价值。
2. **通知凭据只写不读**。列表接口只返回 `configured: true/false`,输入框永远留空。
   让用户看得见 Key,就等于任何 XSS 都能偷走它。
3. **回测两种模式在 UI 上强制区分**。「信号回测」标绿"无前视偏差";
   「权重校准」标红"含前视偏差"并给出原因说明,避免用户拿含偏差的结果做真实决策。
4. **简报的「生成」和「推送」是两个按钮**。推送真的会把消息发到手机上且不可撤回,
   合并成一个按钮等于用户点一下就打扰一次,所以生成在前、推送需二次确认。
   同时界面上直说「自动推送依赖后端进程常驻」——后端没开就不会补发,
   与其让用户以为配好了就一定会收到,不如把前提讲清楚。

### 本轮修掉的真实 Bug

`app/services/backtest/service.py` 的 `compare_weights` 有两处缺陷,导致
"权重校准"实际不可用:

- **复用同一批 picks**:循环里从未使用 `wdict`,各套权重回测结果完全相同,
  用户会误以为"权重对结果毫无影响"。
  已改为:用每套权重对当日候选 `score_stock` 重新打分并重排,取 Top N 再各自回测,
  并返回 `selected_codes` / `weights_sensitive`,各套选出相同股票时明确提示"不敏感"。
- **`build_weights(wdict)` 类型不匹配**:`build_weights` 吃 DB 行
  (`[{"factor_name":..,"weight":..}]`),API 传的是扁平映射
  (`{"main_inflow":120}`),运行时报 `'str' object has no attribute 'get'`。
  新增 `app/modules/screener/scoring.py:weights_from_mapping()`,权重上限/未知 key/
  夹取逻辑与 DB 路径保持一致。

回归测试:`tests/test_backtest_compare_weights.py`(5 passed),其中
`test_different_weights_select_different_stocks` 直接锁死上述第一个 Bug。

### 本轮验证到什么程度(诚实说明)

| 项 | 状态 |
| --- | --- |
| 后端全量 | **855 passed / 0 failed**(8 errors 为沙箱禁止 pytest 在工作区外建 tmp_path,非项目缺陷) |
| 前端类型 | `tsc --noEmit` exit 0(全部新组件类型正确、import 全部可解析) |
| 前端构建 | ❌ **无法验证**。`next build` 与 `next dev` 在本沙箱下均报 `Error: spawn EPERM`(`fork()` 被拒),这是 DSH 沙箱对子进程的边界,不是代码问题。CI 中可正常构建。 |
| 页面渲染 | ❌ 未做运行时验证,原因同上 |

因此前端部分的结论是「类型与依赖图正确」,而不是「已在浏览器中跑通」。
首轮真实启动请重点看:各面板的空态、以及后端未起时的错误提示。

### 后续推进方向

- 阶段6 批次4:`market` 域。`quote_service` / `sector_fund_flow_service` 被 22 个文件引用,
  是整个后端的"心脏",需要单独排期、单独一轮测试;不宜与其他改动混做。
- `analysis` 与 `alert`/`workflow` 已迁完(批次3),`app/api/` 从 27 个文件降到 23 个。

> **移动端专用布局已明确不做。** PWA 目标收敛为:可安装(manifest)、
> 离线可用外壳(Service Worker)、断网有明确提示(`/offline`)、
> 窄屏导航自动折叠为图标条(NavRail 已实现)。
> 不为手机单独设计一套页面 —— 这是个人自用的本地工具,主要场景是桌面浏览器。
> 真正的移动端价值在**推送**(提醒直接到手机),而不是把网页搬到手机上。

---

## 阶段 8 · 盯盘决策引擎 ✅

针对「**什么时候买 / 什么时候卖 / 什么时候做 T / 亏了怎么办 / 赚了怎么办 /
这只票现在什么走势 / 市场什么情况**」这七问，落地了一张**确定性决策卡**：
**零 LLM**，全部数字由算法算出，LLM 只做可选的白话层，与卡片冲突时以卡片为准。

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 决策端点 | `GET /api/stock/{code}/decision` | 一次返回 verdict / 行动清单 / 做T / 走势 / 市场环境 / 别动清单 / 降级标记 |
| 判定器 | `backend/app/services/decision_service.py` | 纯函数、零 IO、零 LLM；价格一律取自 indicators/报价/持仓或其显式四则运算 |
| 市场环境 | `backend/app/services/market_context_service.py` | 大盘 / 行业 / 资金流 / 相对强弱，全链路降级不崩 |
| 回测闸门 | `backend/app/services/decision_backtest.py` | 门槛先定、事后不得下调；`python -m app.services.decision_backtest` 可复跑 |
| 前端 | `frontend/src/components/desk/DecisionCard.tsx` | 盯盘台右栏置顶，1024px 仍保持三栏 |

### 回测闸门结论（5/7 条通过，未全过）

样本：**60 只 × 120 个交易日 = 7200 个可回测日**（新浪日 K，2026-01-05 ~ 2026-10-20，0 只跳过），
现网规则下 entry 有效信号 **308 条**。完整报告：[`docs/analysis/decision-backtest-report.md`](analysis/decision-backtest-report.md)。

| 闸门 | 门槛 | 实测 | 结果 |
| --- | --- | --- | --- |
| 样本池股票数 | ≥ 30 只 | 60 | ✅ |
| 回测窗口 | ≥ 120 交易日/只 | 120 | ✅ |
| 有效 entry 信号数 | ≥ 100 条 | 308 | ✅ |
| entry 后 10 日胜率 | ≥ 53% | **53.90%**（基准 52.74%） | ✅ |
| entry 超额收益 | > 基准 + 1.0% | **−0.76%** | ❌ |
| exit 后 10 日回撤改善 | ≥ 1.0% | **+1.84%**（n=945） | ✅ |
| stop 后 5 日回撤改善 | ≥ 1.5% | +0.17%（n=30） | ❌ |

**怎么读这张表（不粉饰）**：

- **止盈（exit）通过闸门** —— 信号日之后 10 日的回撤确实比常态深 1.84pp，
  「该卖的时候卖」有可验证的择时价值。
- **建仓（entry）只有胜率价值，没有收益价值** —— 胜率稳定高于基准（+1.16 ~ +2.16pp，5 轮迭代全为正），
  但 10 日平均收益**始终低于**「随便哪天买并持有」，是典型的「赢小钱、亏大钱」。
  → 卡面因此只讲**条件、价位与依据数字**，不承诺收益、不把「条件已满足」说成「此时买入会赚钱」。
- **止损（stop）不下结论** —— 60 只池只有 30 条信号（30 只池更少、方向还不一致），
  既不判有效也不判无效，要判需要更大的样本池或更长的窗口。
- **两条 entry 闸门在本样本上互斥**：量比阈值在 [0, 2.0] 全区间扫过，
  **没有任何取值**能同时满足「信号 ≥ 100 条」和「超额 > +1.0%」。
  所以回测侧的「量比 ≥ 1.5 放量确认」**没有落到产品代码** ——
  该配置下信号数只有 53（按 §10.2「不足则结论无效」），
  却会把线上建仓触发率从 4.28% 压到 0.71%，属于拿未验证的收益换明显的可用性损失。
- **固有局限**：无条件基准**无法把「择时能力」与「市场状态」分离** ——
  样本期恰逢大盘回落（基准 10 日平均收益 −0.67%）。
  「未通过」= 在本样本池本样本期未通过，不等于规则在任何行情下都无价值。

### 本阶段修掉的真实 Bug（都是实跑抓出来的）

- **C2 超跌反弹的 `status` 只判了条件的一个合取项**：实测 `现价 14.35 < P20 15.19`
  却被标成「现在可做」，直接违反「now = 此刻条件已满足」。
- **C1/C2/C3 不看通道**，与「别动」清单自相矛盾：新增**下跌通道守卫**
  （`channel == down` 时建仓候选一律降级为「待触发」）。量化：entry 触发日 339 → 267 → 158，
  原来有四成建仓信号落在下跌通道里。
- **实时价缺失时真实持仓被判成「空仓」**：持有 700 股 @23.04 的用户被告知「首仓 30%，可以建仓」。
  改为按 `effective_price` 用 K 线最新收盘价兜底。
- **止损规则是死代码**：`support_price = min(closes[-20:]) × 0.98` 含当前根，
  导致 `stop_loss_price ≤ 当前收盘 × 0.9506`，而触发条件 `现价 < stop_loss_price`
  在收盘价口径下**数学上永不可能成立** —— 15900 个信号日命中 **0** 次。
  改为支撑窗口排除当前根后，命中 **3/600**。
- **项目级单位 bug**：板块资金流「元 → 亿」的换算漏了源头，UI 上金额整体差 1e8。

### 本阶段验证到什么程度

| 项 | 状态 |
| --- | --- |
| 后端全量 | **1119 passed / 0 failed** |
| 回测闸门单测 | `tests/test_decision_backtest.py` 16 条 + `tests/test_decision_backtest_invariants.py` 4 条（口径不变量）全绿 |
| 前端类型 / 构建 | `tsc --noEmit` 零错误；`next build` **27 路由全部生成** |
| 浏览器实测 | 1510px / 1024px 三栏保持；深浅主题跟随 token；控制台零 error；空仓票显示建仓参考、持仓票显示止盈/解套参考、做T 区块有内容 |
| 降级路径 | 删掉 `industry_map.json` 后仍返回，只在 `data_quality.degraded` 标注「未获得行业归属」，**不空白、不编数字** |

> 设计文档：`docs/superpowers/specs/2026-10-21-stock-decision-engine-design.md`
> 决策卡版面与交互：`docs/design/trading-desk-v3-decision-card.md`

---

## 阶段 9 · 每日作战计划 ✅

针对「**复盘困难、对明天一脸茫然、没有操作预期**」，落地 `/plan` 页面：
**今日复盘 + 明日市场预期 + 明日逐票操作预案**。

核心定位是**纪律锚点，不是预测器** —— 全程零 LLM，
所有数字只来自 indicators / 报价 / 持仓或其显式四则运算。

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 页面 | `/plan` | 两栏：左=明日逐票预案，右=明日市场预期 + 今日复盘；断点用 `lg`(1024)，**两栏保持到 1024px**，窄屏单栏顺序「预期 → 预案 → 复盘」 |
| 明日预期 | `backend/app/services/outlook_service.py` | 四维度规则推断（量能 / 涨跌家数 / 均线 / 板块资金）+ 关键位；纯函数、零 IO、零 LLM |
| 预案转换 | `backend/app/services/plan_item_builder.py` | 决策 actions 的 now/armed/blocked 三路分流；now → 复盘待办 |
| 兑现比对 | `backend/app/services/fulfillment_checker.py` | 昨日预案 × 今日行情+流水 → 触及 / 已执行 / 未触发 / 不适用 / 数据不足 |
| 编排 | `backend/app/services/battle_plan_service.py` | 股票池=持仓 ∪ ★关注（**实测 11 只**：持仓 5 ∪ 关注 6，去重后 11；上限 ≤20）；唯一做 IO 的模块 |
| 端点 | `GET/POST /api/battle-plan` | 读取 / 生成 / scope |

### 设计约束（阶段 9 · 明日预期）

- **明日预期是纪律锚点，不是预测器**；只写「倾向」，必带「非预测」标注
- 偏多需 ≥2 个有效维度；偏空允许单维度（风险侧保守，刻意不对称）
- 规则参数先定死（1.10 / 0.90 / 60% / 40%）；未来回测校准只能改参数，不得事后调门槛
- 兑现「未触发」不评价对错（本来就没到，不是判断错）

### 兑现口径（5 态，`no_data` 是独立第三态）

| 状态 | 含义 |
| --- | --- |
| `executed` | 昨日预案的动作今天真的执行了（成交流水里查得到） |
| `touched` | 触发了价位但没成交（触达未执行） |
| `missed` | 触发了价位、该做没做（纪律问题） |
| `n_a` | 不适用（这条预案本就不在这只票的适用范围内） |
| `no_data` | 数据不足（既没触发记录也没流水，判不了） |

`summarize_fulfillment` 的 `total` = **所有预案条数**（含 `n_a` 与 `no_data`），
与 `executed + touched + missed` **故意不相等**；
前端必须把「不适用 N」「数据不足 N」显式列出，否则用户以为漏了几条。

### 已知边界（诚实披露，不是缺陷）

- `target_date` 按**工作日**推算（项目无真实交易日历）→ `meta.target_date_estimated` 恒为 `true`，
  页面显式写「明日按工作日推算为 …」。
- `battle_plan_service._load_transactions` 用 `list_all(limit=500)` 再按日期过滤，
  单日流水超 500 条会漏单（当前规模远不到 500）→ 详见卡面文档 §九 (h)。

### 本阶段验证到什么程度

| 项 | 状态 |
| --- | --- |
| 后端全量 | **1297 passed / 0 failed**（602.52s；= 修复 workflow 后的基线 1268 + 本轮回填新增 29 条） |
| ruff 门禁 | 本功能涉及 **13 个文件**全绿（`All checks passed!`）；全仓 224 条历史存量不在本阶段范围 |
| 真机生成 | `plan_date=2026-10-22` / `target_date=2026-10-23` / stance=**偏空**(score −2) / dims **4/4** / items **34** / scope **11** / degraded=**false** |
| 价格一致性 | 预案 `trigger_price` 与决策卡 `action.price` / `stop_loss.price` **逐位相同**（抽查 5 条 + 5 只持仓止损全对） |
| 浏览器实测 | 1510 / 1280 = `736px 360px` 两栏；**1024 = `590px 320px` 两栏**；820 = 单栏且顺序「预期 → 预案 → 复盘」；四档均无横向滚动、console 零 error |
| empty 态 | 拦 `GET /api/battle-plan` 成 404 实拍：渲染目标股票池 **11 只**（不是空壳），首屏无大片虚空 |
| 兑现回填 | 今日无昨日计划 → 如实显示「没有找到上一份作战计划，今日暂无兑现比对」，**不编造** |

> **一个遗留缺陷（本阶段未修，前端范围外）**：empty 态那次 404 会被 axios 全局拦截器
> 弹成红色 toast「请求失败 (HTTP 404)」—— 空态本身渲染正确，但用户会先看到一条报错。
> 修法在前端（`frontend/src/lib/api.ts` 的响应拦截器需支持「该请求不弹 toast」），
> 详见本轮交付报告。

---

## 阶段 0 · 工程地基 ✅ 进行中

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 修复 3 个阻断缺陷 | ✅ | `KlineCache` ORM 缺失、Alembic 链断裂、conftest 临时目录 ACL |
| 测试隔离 | ✅ | autouse fixture 清缓存 + 清库表；修复"过期定时炸弹"日期锚点 |
| 架构守卫测试 | ✅ | `tests/test_architecture_boundaries.py`（7 项，AST 静态分析） |
| 数据治理 | ✅ | `fund_flow` 保留策略（实测 234 万行 → 裁剪）+ 索引 + VACUUM |
| SQLite 加固 | ✅ | WAL / busy_timeout / synchronous=NORMAL / 连接池 |
| CORS / 后台任务 / 日志 | ✅ | 通配+credentials 冲突、create_task 未持引用、loguru 未接管标准库 |
| 版本单一来源 | ✅ | `app.__version__` |
| ruff 配置 | ✅ | `pyproject.toml` |
| CI workflow | ⬜ | pytest + ruff + 前端 typecheck/lint |
| Makefile | ⬜ | 统一命令入口 |

**当前测试基线**：

| 阶段 | 结果 |
| --- | --- |
| 接手时 | **0 个测试可运行**（27 个文件 collect 失败：conftest 临时目录 ACL） |
| 修完 3 个阻断缺陷 | 656 passed / 19 failed / 8 errors |
| 隔离修复（缓存+清表+日期锚点） | 680 passed / 2 failed / 8 errors |
| 补 Provider/限流/权重缓存清理 + 硬化全局状态用例 | **783 passed / 1 failed → 0 failed / 8 errors** |

剩余 **8 个 error** 是 pytest 自身 `tmp_path` 在受限沙箱下建目录被拒
（`test_quote_service`，8 项），**非项目缺陷**，CI 上正常。

### 顺手修掉的两个真实产品 Bug

| Bug | 影响 | 修法 |
| --- | --- | --- |
| `llm.model_name` 直接属性访问 | 任何未实现该属性的 LLM client 会让**评语已生成后的最后一步持久化 + SSE 推送**整段丢失 | `_resolve_model_name()` 多级兜底（services/diagnose_service.py） |
| 回测 `TradeFees.enabled` 默认 False | 沿用实盘"双口径展示"默认值会让**回测收益虚高约 0.13%/次** | `CostModel` 强制 `enabled=True`（backtest/cost_model.py） |

---

---

## 阶段 1 · 提醒闭环 ✅ 已完成

### 1.1 通知平台层 `app/services/notify/` ✅

```text
notify/
├── base.py          # Notifier 协议 + NotifyMessage/NotifyResult + 渠道枚举
├── channels.py      # Console / 钉钉 / 企业微信 / Bark / Webhook
├── dedupe.py        # 冷却去重 + 日限流(内存,线程安全)
├── config_service.py# 凭据加解密 + 渠道构造 + 连通性测试
└── service.py       # 编排:扇出、失败降级、限流入口
```

已实现要点：
- **通知永不阻断主流程**：单渠道失败只记 `last_error` + 日志，不抛给业务
- **凭据加密**：`config_encrypted` 用 Fernet 落库，前端只拿 `config_hint`（如域名片段）
- **去重指纹**：`sha1(条件树 + 价格分桶)`，价格在同一分桶内反复穿越阈值不会刷屏
- **架构合规**：`api/notify.py` 不直连 repository（由架构守卫测试强制）

### 1.2 价格提醒引擎 `app/services/price_alert/` ✅

```text
price_alert/
├── engine.py     # 条件树求值(纯函数):AND/OR 可嵌套 3 层
├── service.py    # CRUD / 扫描 / 触发推送
└── scheduler.py  # 60s 轮询,交易时段内运行
```

条件模型（4 指标 × 6 比较符 × AND/OR 嵌套）：

| 指标 | 说明 |
| --- | --- |
| `price` | 最新价 |
| `change_pct` | 涨跌幅 |
| `volume_ratio` | 量比 |
| `turnover` | 换手率 |

风控：冷却窗口（默认 30min）、每日上限（默认 5 次）、到期时间、失效自动跳过。
非法条件在**创建时就 422 拒绝**（`validate()`），不等到运行时报错。

### 1.3 数据表 ✅

`notify_channel_config` / `price_alert` / `price_alert_trigger`（迁移 `b2c3d4e5f607`）。

**API**（8 个端点）：`/api/notify/channels*`、`/api/price-alerts*`

---

## 阶段 2 · 决策质量 ✅ 已完成

### 2.1 选股权重 UI 可调 ⭐ 性价比最高 ✅

**改造前**：50 行 `SCREENER_*` 常量写死在 `core/config.py`，改权重必须改代码重启。
**改造后**：`screener_weight` 表 + `services/scoring_weights.py`。

关键设计 —— **向后兼容是硬约束**：

```python
score_stock(features)              # 历史行为,逐位一致
score_stock(features, weights)     # 新行为
```

传默认权重时评分结果与历史**完全相同**（有单测锁定：`test_default_weights_gives_identical_result`）。
用户调整权重后，各因子分按 `raw / default_max * new_weight` 等比例缩放，保持相对强弱。

| 因子 | 默认满分 | 说明 |
| --- | --- | --- |
| `main_inflow` | 60 | 板块资金流入强度 |
| `volume_ratio` | 40 | 放量程度 |
| `momentum` | 30 | 当日涨幅 + 连涨天数 |
| `sector_strength` | 25 | 板块资金榜排名 |
| `event` | 15 | 事件热度 |

- 支持单项停用（`enabled=false` 视为 0 分，保留配置值）
- 校验：范围 [0, 200]、至少启用一个因子
- 进程内缓存 + 改权重主动失效
- `GET/PUT /api/screener/weights`、`POST /api/screener/weights/reset`

### 2.2 策略回测引擎 `app/services/backtest/` ✅

```text
backtest/
├── engine.py     # 日线事件驱动(纯逻辑):T+1、100 股整手、持仓上限
├── cost_model.py # 复用 core/cost_engine 真实 A 股费率 + 滑点
├── metrics.py    # 12 项绩效指标(纯函数)
└── service.py    # 信号回测 + 权重对比
```

**A 股规则已实现**：T+1 卖出（当日买入不可当日卖）、100 股整手向下取整、
资金不足自动缩量或放弃、缺价沿用最后已知价（停牌）。

绩效指标：总收益、年化、最大回撤（含峰/谷下标）、年化波动率、夏普、
胜率、盈亏比。

**诚实性设计** —— 两种模式明确区分是否含前视偏差：

| 模式 | 前视偏差 | 用途 |
| --- | --- | --- |
| `POST /api/backtest/signal` | ❌ 无 | 把历史每日 picks 当 buy 信号，衡量选股逻辑真实表现 |
| `POST /api/backtest/compare-weights` | ⚠️ `has_lookahead_bias: true` | 仅用于理解权重敏感度，**不可当作真实收益** |

原因是选股只保存了"某日选出哪些股票"，没有保存每日全市场因子矩阵；
用今日权重重算历史会产生前视偏差，回测好看但不可信。因此不做那条路。

---

## 阶段 3 · 模拟盘 `app/services/paper_trading/` ✅ 已完成

让用户**零风险**验证选股 → 提醒 → 执行链路。

| 文件 | 职责 |
| --- | --- |
| `models/orm.py` | `paper_account` / `paper_order` / `paper_position` / `paper_equity_snapshot` |
| `repositories/paper_trading_repo.py` | 账户/持仓/订单/净值快照 CRUD |
| `services/paper_trading/service.py` | 下单、持仓均价摊薄、已实现盈亏、净值曲线 |
| `services/paper_trading/scheduler.py` | 收盘后（15:35）自动记净值快照 |
| `api/paper_trading.py` | 8 个端点 |

### 隔离设计（最重要的部分）

模拟盘**物理隔离**于真实持仓：独立 `paper_*` 表，代码层由两条架构守卫测试硬拦：

- `test_paper_trading_never_imports_real_position_modules`
- `test_paper_tables_are_separate_from_real_tables`

原因：模拟盘会被调度器自动写流水，一旦与真实 `transactions`/`positions` 混表，
事后几乎无法分辨哪条是"真买的"、哪条是"模拟的"。

### 关键规则

- **费用口径与实盘一致**：`TradeFees(enabled=True)`，复用 `core/cost_engine`
- **价格取真实行情，不让用户手填**：否则"模拟"就变成了"虚构"
- 100 股整手校验、现金/持仓不足抛明确错误、买入费摊入持仓均价
- 绩效指标复用 `backtest/metrics.py`，与回测同口径

**API**：`/api/paper-trading/{accounts, :id/summary, :id/buy, :id/sell, :id/orders, :id/equity-curve, :id/snapshot}`

---

## 阶段 4 · 多智能体深度分析 `app/services/multi_agent/` ✅ 已完成

```text
technical / fund_flow / news / fundamental  ─┐(并发)
                                             ├─▶ bull ─┐
                                             └─▶ bear ─┴─▶ risk ─▶ pm ─▶ 决策书
```

| 文件 | 职责 |
| --- | --- |
| `contracts.py` | 角色/立场/动作枚举 + `AgentOpinion` / `DecisionReport` |
| `prompts.py` | Prompt 构建(prompt 里写死"绝不允许自己计算数字") |
| `service.py` | 并发编排 + 逐级降级 |
| `api/multi_agent.py` | `GET /api/multi-agent/{code}`、`/meta/roles` |

### 三条设计取舍

1. **LLM 只推理,不计算**。所有指标由 `ta_service.compute_indicators` 等确定性算法算出,
   作为"事实"喂给 Agent。LLM 幻觉污染不到数字。
2. **4 个分析师并发**,总耗时 ≈ 最慢的一个而非 4 个之和。
3. **全程降级,绝不 500**。单 Agent 超时(45s)/返回非 JSON/未配 Key,
   都退化为 `degraded=True`;PM 若给出非法动作(如"梭哈")一律回落 `hold`。

配套 `app/services/workflow_agent/`:盘前 08:30 / 盘中 11:30、14:50 两段定时简报,
推送复用阶段 1 通知层。时间窗幂等(同一时段当天只跑一次)。

---

## 阶段 5 · 多账户 / PWA / 引导中心 ✅ 已完成

### 多账户 `app/modules/portfolio/`

- `account` 表;`positions` / `transactions` 新增 `account_id`
- **存量无感**:`positions.stock_code` 的全局唯一改为 `(account_id, stock_code)` 组合唯一,
  7 条存量持仓 + 7 条流水由迁移 `e5f60718293a` 回填到 `account_id=1`
- 不传 `account_id` 的存量调用方一律落到默认账户,**前端零改动**
- 迁移在**数据库副本**上验证过(数据行数不变、同票可跨账户并存、同账户内仍拒重复)

SQLite 无法直接 DROP UNIQUE(`sqlite_autoindex` 是系统索引),
必须用 `batch_alter_table(copy_from=<显式表定义>)` 重建表;
直接用 `batch_alter_table` 会 reflect 出旧 UNIQUE 并保留下来。

### PWA

`manifest.webmanifest` + `sw.js` + 图标 + `/offline` 页。
**Service Worker 绝不缓存 `/api/**`** —— 行情缓存会让用户看到昨天的价格却以为是今天的,
这是投资工具最不能接受的错误。

### 引导中心 `app/services/onboarding_service.py`

进度**由系统实时判定**(数据库就绪 / 行情通不通 / 模型配没配 / 有没有持仓),
不用前端 localStorage 标记,避免清单与真实状态脱节。

---

## 阶段 6 · `modules/<domain>` 迁移

规划见 [`docs/adr/ADR-0001-modules-domain-layout.md`](adr/ADR-0001-modules-domain-layout.md)。
首批已落地 `screener`、`portfolio` 两个域,并新增 3 条 modules 专属架构守卫。

### 4.1 多智能体分析（TradingAgents 式）

```text
技术分析 Agent ┐
情绪/资金 Agent ├─▶ 看多 Agent ─┐
新闻/公告 Agent ┘               ├─▶ 风控审查 ─▶ PM 决策书
基本面 Agent ───────────────────┘
```

- 产出**可展示的推理链**，而不只是结论（这是 PanWatch 的核心卖点）
- 复用现有 `llm/` 工厂，做 provider failover 与 token 计量
- 保留现有"LLM 只翻译不计算"原则：确定性指标由算法算，Agent 只做推理与辩论

### 4.2 三段式定时 Agent

| 时段 | 任务 |
| --- | --- |
| 盘前（08:30） | 隔夜消息汇总、持仓风险提示、今日关注清单 |
| 盘中（11:30 / 14:00） | 盘中复盘（市场意见 + 逐票操作建议），异动扫描并入补充段 |
| 盘后（15:30，已有） | 选股跑批、复盘生成 |

---

## 阶段 5 · 产品完善

| 功能 | 要点 |
| --- | --- |
| **多账户** | `accounts` 表 + 持仓/流水加 `account_id` + 跨账户汇总视图；迁移需写数据迁移脚本 |
| **PWA** | `manifest.webmanifest` + service worker（Next.js 成本低），支持添加到主屏 |
| **引导中心** | 分路线引导（自选 → 行情 → AI → 提醒 → 模拟盘），进度持久化 |

---

## 阶段 6 · 架构演进（长期）

对齐 PanWatch 的模块化单体，**渐进式**而非大爆炸：

```text
backend/app/
├── modules/<domain>/     # 业务能力：portfolio / market / screener / alert ...
│   ├── api.py
│   ├── service.py
│   ├── repository.py
│   └── schemas.py
└── platform/             # 技术能力：persistence / marketdata / ai / notify
```

迁移顺序（按自洽度）：`screener` → `alert` → `portfolio` → `market`

规则：
1. **新增代码一律进 `modules/<domain>/`**，不再进 `services/`
2. 每迁一个域，同步更新架构守卫测试与 ADR
3. 存量 `services/` 冻结，只减不增

---

## 阶段 10 · 盘中复盘 + 全局助手 + 性能 ✅

> 设计与口径：[`docs/design/trading-desk-v4-assistant-intraday.md`](design/trading-desk-v4-assistant-intraday.md)
> 性能基线与复测：[`docs/analysis/frontend-perf-baseline.md`](analysis/frontend-perf-baseline.md)

### 10.1 盘中复盘（11:30 / 14:00，盯盘页看得见）

| 项 | 做法 |
| --- | --- |
| 交易日历 | 真源 = **上证指数 `000001.SH` 真实日 K 日期集合**；拉不到回落 `weekday()<5` 并显式带 `estimated=true` + warning（**不静默假装准确**） |
| 决策层 | `services/intraday_advice.py` 纯函数，零 IO 零 LLM；四态 `未到价 / 已到价待执行 / 不适用 / 数据不足`，`_EPS=1e-9`，**不重算价格** |
| 市场意见 | **复用作战计划四维度预期**（盘前推断），标注「盘前四维度推断 · 非盘中重算」，**不做盘中重算** |
| 缺今日作战计划 | **响亮失败 422**，不产半成品建议 |
| 落库 | `intraday_review` 表，唯一键 `(trade_date, slot)` → 同日同档幂等覆盖 |
| 可见性 | 盯盘页顶栏胶囊（已产出 / 未产出倒计时 / 非交易日）→ 右侧抽屉（市场意见 + 逐票操作建议 + 异动扫描补充段） |

### 10.2 右下角悬浮球助手

- **全局**：挂在 `AppShell`，任何页面可唤起；自动带「当前选中的那只票」
- **事实包**：选中票 / 持仓 / ★关注 / 今日作战计划 / 今日盘中复盘 / 指数快照，**每段独立兜底**，失败段标 `unavailable`
- **铁律**：所有数字必须来自事实包，**逐字引用**（实测抓到 LLM 把止损价 `11.625` 四舍五入成 `11.62` → prompt 钉死并加测试）
- 32 张表情走静态资源（不进 bundle），静态帧 + CSS 切换过渡

### 10.3 前端性能

四档口径（点击反馈 / 十字光标 / 轮询落地 / 悬浮球 idle）全部实测，数字与**测量环境的坑**都记在
[`docs/analysis/frontend-perf-baseline.md`](analysis/frontend-perf-baseline.md)。

本轮修掉的真问题：

| 项 | 根因 | 结果 |
| --- | --- | --- |
| 切票 **710ms** 主线程阻塞 | 44 行自选是内联 `motion.li` 且没有 memo → 切票全量重渲染 | 行抽成 `memo` 组件 + 回调引用稳定 → **0 条长任务** |
| 每秒整页重渲染 | 自动刷新倒计时住在 `Workbench` state 里 | 挪进独立 zustand store → 每秒只重渲染顶栏那个小按钮 |

顺带修掉：Service Worker 缓存 RSC 载荷导致发版白屏、46 张表情 SVG 缺 `xmlns` 全挂、`fetchMarketHeader` 注释与实现不符。

---

## 阶段 11 · 持仓侧流水录入 + 逐笔评分 ✅

针对「**记完流水不知道自己做得对不对**」，把「录入 → 打分」这条闭环**搬进持仓页**：

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 录入入口 | `frontend/src/components/positions/PositionTransactionModal.tsx` | 持仓卡片行内「📝 录入流水」→ 弹窗内填表 + 该股流水表（带评分列 / 评分详情） |
| 时间节点 | `transactions.trade_time`（新列，可空） | 录入带「交易时间」；同一交易日的多笔按 `(trade_date, trade_time, id)` 计入成本链；时间未知 = NULL，不编造 |
| 第 6 维评分 | `backend/app/core/scorer.py` `TIMING` | 「交易时机」= 日内价格位置（低吸 / 追高）+ 时段适配（躲开开盘半小时与尾盘追单）；**6 维 × 20 = 满分 120** |
| 交易当日口径 | `backend/app/services/diagnose_service.py` `_index_change_pct_for` | 「市场环境」维改用**交易当日**的大盘涨跌幅 —— 此前用「当下」的指数给历史流水判顺势/逆势，等于编数字 |
| 补评闭环 | `POST /api/diagnose/backfill` + `backend/scripts/backfill_trade_scores.py` | 补齐漏评的流水；口径升级后 `--force` 全量重算（旧分不可比） |
| 漏评路径修复 | `api_positions.py`（一键清仓）、`screenshot_service.py`（截图导入） | 这两条写入路径此前**不触发评分** → 导入/清仓出来的流水永远没有分数 |

### 已知边界（诚实披露）

- **板块热度恒为 0**（历史板块排行不可回溯）→ 实际满分上限 **100/120**，徽章「优秀」档（≥96）当前可达区间 96~100。
- 存量流水的 `trade_time` 全为 NULL（未知），迁移只加可空列、**不回填**。
- 「交易时机」的阈值是产品默认值，集中在 `core/scorer.py` 常量表，改阈值不改结构。

---

## 阶段 12 · 补T待接回清单 ✅

针对「**卖出了却忘了什么时候接回**」，把「待补T的票」提到左栏**第一位**：

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 清单口径 | `backend/app/modules/portfolio/api_t_reminders.py` | 每只标的取**最近一个有流水的交易日**，当天 FIFO 抵消后剩下的净卖出 = 待接回股数；加权均价 = **不亏本接回线** |
| 左栏置顶 | `frontend/src/components/treminder/TReminderRailCard.tsx` | Logo 正下方、全部导航组**之上**：直接列出「代码 + 待接回股数 + ≤接回价」，不用点进去；折叠态降级为 🔁 图标 + 数字徽标 |
| 专用页 | `/t-reminders`（`TReminderPanel.tsx`） | 完整表格：待接回 / 不亏本线 / 现价 / 接回判断 / 持仓 / 最近卖出 / 到价提醒是否已建 |
| 一键接回 | `TransactionForm` 新增 `initialAction` / `initialShares` / `initialPrice` | 点「录入接回」→ 弹窗预填代码、方向=买入、股数=待接回股数、价格=不亏本线；提交后清单自动刷新 |
| 自动消失 | FIFO 抵消 | 当天卖出后又买回（做T完成）→ 净卖出归零 → 这一条从清单里**自动消失**，不用手动清理 |

**为什么只看最近一个交易日**：卖出后没接回可能是「减仓」而不是「做T」，历史卖出不该一直挂在提醒里。

**已知边界**

- 到价提醒**没有到期日字段**，补T提醒会一直挂着直到价格触发或手动删。
- 通知渠道默认只有「终端日志」开启 → 提醒只写后端日志，**推不到手机**（需在「设置 → 通知设置」配钉钉/企微/Bark/Webhook）。

---

## 阶段 13 · 做T操作历史 + 接回后成本 ✅

针对「**做过的T记不住账**」，把每一次做T的**T前/T后成本价**与**赚亏金额**摆出来：

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 做T配对 | `backend/app/modules/portfolio/api_t_history.py` | 做T = **先卖出、后买回**；按链全序 FIFO 配对（买入扣最早的卖出），不限时限（当天卖、次日接回算同一次）；链尾未抵消的卖出 = **待接回** |
| 两个盈亏口径 | 同上 | `t_pnl` =(卖价−买价)×股数（做T差价盈亏）；`realized_pnl` =(卖价−T前成本)×股数（卖出确认的已实现） |
| 成本价 | `service.load_chain_context` + 成本链重放 | `cost_before` = 卖出那一刻的加权成本；`cost_after` = 买回之后的加权成本。基准吸收的早期导入流水没有逐笔成本 → 显示「—」，不编数字 |
| 持仓详情右栏 | `frontend/src/components/positions/THistoryPanel.tsx` | 持仓卡片「📊 K 线」弹窗改成**左 K线 / 右做T历史**两栏；顶部汇总「已接回 N 次 · 累计做T盈亏 · 待接回 N 次」，下方表格逐笔列日期/股数/卖出→买回/成本前→后/做T盈亏/已实现 |
| 接回后成本 | `api_t_reminders.py` + `TReminderPanel.tsx` | 补T清单新增「成本 接回前→后」列：按建议接回价接回后成本线会降到多少 —— 这次T能把成本拉低多少，一眼可见 |

**为什么两个盈亏都要**：差价盈亏答「这次T做得好不好」，已实现答「这笔卖出相对成本赚没赚」——
两个口径回答的是不同问题，只给一个必然被误读。

**已知边界**

- 基准吸收段的做T只有价差、没有成本（早期导入流水缺逐笔成本快照）→ 成本列显示「—」。
- 到价提醒仍按**不亏本线**触发（回到卖出价就响），挂单用**建议接回价**；两者分工写在页面口径说明里。

---

## 阶段 14 · 成本口径改券商摊薄口径 ✅

针对「**昨天录入流水后,成本和持仓对不上**」——逐只比对券商持仓截图后定位根因并修掉。

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 口径改摊薄 | `backend/app/modules/portfolio/service.py` | 成本链内部改为**追踪净投入**(摊薄总额):买入 += 成交价×股数,卖出 −= 成交价×股数(按成交价回收)。摊薄成本 = 净投入 ÷ 股数 = 券商持仓页的「成本价」 |
| 根因修复 | 同上 + `api_positions.py` | v0.10 展示用 `(total_cost − realized_pnl) ÷ shares` 反推摊薄成本,而基准里带的正是券商给的**累计已实现** → 已实现被**二次扣减**(豫能控股 15.704 vs 券商 18.940)。改成直接追踪净投入后恒等 |
| 计算器同步 | `app/core/cost_engine.py` | 试算同步摊薄口径:卖出后摊薄成本会变(`delta_cost` 不再恒为 0),与链内一致 |
| 基准修正 | `backend/scripts/fix_base_to_broker.py` | 用券商快照推基准:`S0 = 券商股数 − ΔS`、`D0 = 券商摊薄总额 − ΔD`(ΔS/ΔD 取活链净股数/净现金流),基准已实现**独立**存放不再二次扣减;脚本带 `--dry-run`、幂等、可审计 |
| 前端口径 | `PositionSummaryTable` / `PositionsList` / `DecisionColumn` / `ClearPositionModal` / `StopLossModal` / `TReminderPanel` / `THistoryPanel` / `glossary` | 「加权成本」→「摊薄成本」;补T「接回后成本」与做T历史「成本 前→后」都走摊薄成本线 |

**为什么必须换口径而不是改展示公式**：摊薄成本**只在卖出后才会偏离**（低价卖 → 摊薄成本抬高），
这是券商的既定行为；要与券商长期对齐，内部就得直接记净投入，少一层反推就少一处错位。

**验收（2026-11-03，券商截图 11 只）**：修正基准 + 全量重放后，**11 只摊薄成本与券商分毫不差**
（含华天科技股数 1000 → 1100、集成电路ETF嘉实基准 813.00 → 810.00 的修正）。

**已知边界**

- 「加权成本」这个概念从系统里**整体消失**：券商只给摊薄成本，保留两套会让「成本」有歧义。
- 净投入为负（卖出价高于成本、已把投入全收回来）时摊薄总额按 0 记，避免出现负的「持仓资金」。

---

## 阶段 15 · 做T记录区分正T / 反T ✅

针对「**半导体设备应该还有一个正T要接回的**」——录入当天流水后，
系统只认「先卖后买」一种做T，买进还没卖出的那一腿被**整段丢弃**，
用户手上明明还有正T在等着，系统却看不见。

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 双向 FIFO 配对内核 | 新增 `backend/app/modules/portfolio/t_pairing.py` | 做T分两个方向:**反T**(先卖出后买回,高抛低吸)、**正T**(先买入后卖出,低吸高抛)。后一笔流水优先闭合最早的开腿;链尾没闭合的开腿 = 挂单。做T历史与补T清单共用这一份判定 |
| 配对时间窗口 | 同上 `T_PAIR_WINDOW_DAYS = 3` | 开腿与收腿相隔超过 3 天就不是做T(是加仓/割肉)。超窗口的开腿**冻结**,不再吃掉后面的动作。没有窗口时「十月的买入」会配掉「今天的卖出」,真正的当日做T反而散架 |
| 做T历史分方向 | `api_t_history.py` + `THistoryPanel.tsx` | 每条记录加 `direction`(reverse / forward);未闭合的显示「待接回」/「待卖出」;差价盈亏统一为 (卖价 − 买价)×股数 —— 两个方向都是低买高卖赚差价 |
| 补T清单分两组 | `api_t_reminders.py` + `TReminderPanel.tsx` + `TReminderRailCard.tsx` | 「待接回(反T)」与「待卖出(正T)」两组,各带建议价与一键录入;正T的建议卖出价与反T的建议接回价对称(基准线 × 1.01 / × 0.99,三档见阶段 16) |
| 清单口径改全链 | 同上 | 从「只看最近一个交易日」改成**全链未闭合** —— 卖 200 只接回 100,剩下 100 股不会凭空消失。窗口以链上最后一天为基准,确定性,不随「今天」漂移 |

**为什么必须加时间窗口**：做T是**短周期**动作(当天卖、次日接回)。
2026-11-03 中钨高新真实流水就是反例:10-13 买、11-02 卖、11-02 买、11-03 买 ——
没有窗口时 11-02 的卖会先配 10-13 的买,当天做的那笔T散架,今日真正的加仓反被当成接回腿。

**验收（2026-11-03，录入当天 7 笔流水后）**：清单 = **4 只** ——
豫能控股 100 股待接回(反T,11-02 卖 200 只接回 100 只)、
中钨高新 100 股 / 华天科技 100 股 / 半导体设备ETF 200 股待卖出(正T,均为 11-03 买入)。

**已知边界**

- 「卖出后长期不接回」在窗口内也会挂着(可能是减仓不是做T)—— `open_date` 给出挂单起始日便于判断。
- 到价提醒由系统**自动建在建议价上**(见阶段 16);正T组的提醒阈值是 `price >= X`,与反T相反。

---

## 阶段 16 · 做T三档建议价 + 自动到价提醒 ✅

针对「**建议价应该多显示卖出/买入价格,分一、二、三档,并显示对应的成本前后**」+
「**并且要自动建立到价提醒**」——原来只给一个建议价(0.5%),
既看不出「做到什么价才划算」,也容易接回/卖出错过时机。

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 三档建议价内核 | 新增 `backend/app/modules/portfolio/t_pricing.py` | 每条挂单给三档:**一档 1% / 二档 2% / 三档 3%**,每档都带「按这档成交之后的摊薄成本前→后」。一档贴线最容易成交,三档幅度最大但可能要等行情 |
| 方向相反 | 同上 `tier_factor()` | 反T 三档价格**往下**(越等接回越便宜),正T 三档**往上**(越等卖得越贵)。不能一味价高 —— 一味价高在反T 上就是「接回比卖出还贵,做出来是亏的」 |
| 到价提醒自动管理 | 新增 `backend/app/modules/portfolio/t_alerts.py` | 每条挂单**保证有一条到价提醒**:反T `price <= 一档价`、正T `price >= 一档价`(方向必须跟T方向一致,反了就是「涨了提醒接回」) |
| 幂等同步 | 同上 `sync_auto_alerts()` | 在 `GET /api/t-reminders/pending` 里同步:缺提醒就建、挂单消失就**停用**(不是删除,保留触发历史)、基准线变了就**就地**把提醒改到新的一档价(同一条 id,不新建) |
| 自动提醒的标记 | 同上 `AUTO_ALERT_PREFIX = "[做T]"` | `PriceAlert` 没有 source/metadata 字段,只能用 name 前缀标记。**只对带前缀的提醒做自动停用** —— 用户手工建的提醒一律不碰 |
| 档位由用户定 | 同上 `_tier_of()` / `_realign()` | 三档摆在那里就是为了让人选:用户把自动提醒改到二档/三档,**系统认**(不拉回一档);只有价格不落在当前任一档上时(基准变了 / 改成了自定义价)才就地拉回一档 |
| 三档展示 | `TReminderPanel.tsx` | 清单的「建议价 + 成本前→后」两列合并成一列「三档建议价 · 成本前→后」,一行一档;录入弹窗也把三档全列出来(一档预填进表单) |
| 提醒状态展示 | 同上 + `TReminderRailCard.tsx` | 「到价提醒」列显示 `≤8.771(1档)`,用户另建的提醒显示为「另有手工 ≤8.860」 |

**为什么幅度从 0.5% 改成 1% / 2% / 3%**:0.5% 只够覆盖双边手续费 ——
接回 10 万块才省 500 块,忙活一趟基本白做,还得一直盯着盘面。1% 起才有「做T的收益」这回事。

**为什么自动提醒落在一档**:一档是**行动信号**(该动手了,别错过);
二/三档是「愿意多等一会儿换更好价」的选择,系统不替用户擅自决定等多久。
新建时落在一档;**用户改到二档/三档,系统认**(三档摆出来就是为了让人选),
只有价格掉出整个阶梯时才拉回一档。

**验收（2026-11-03）**:清单 4 只,三档全部正确且方向相反 ——

| 标的 | 方向 | 基准线 | 一档 | 二档 | 三档 |
| --- | --- | --- | --- | --- | --- |
| 豫能控股 | 反T 待接回 | 8.860 | 8.771 ↓ | 8.683 | 8.594 |
| 中钨高新 | 正T 待卖出 | 35.980 | 36.340 ↑ | 36.700 | 37.059 |
| 华天科技 | 正T 待卖出 | 14.350 | 14.494 ↑ | 14.637 | 14.781 |
| 半导体设备ETF | 正T 待卖出 | 0.442 | 0.446 ↑ | 0.451 | 0.455 |

自动建了 4 条提醒(反T 用 `<=`、正T 用 `>=`),用户原有的 4 条手工提醒一条没动。

**已知边界**

- 通知渠道目前只有 console 开着 → 提醒**推不到手机**,自动提醒只写后端日志。要真正收到推送得先在「通知设置」里开一个渠道。(v0.20 已修:渠道跟随全局启用项,且新增不依赖系统通知的应用内弹窗 —— 见阶段 17)
- 自动提醒**新建**时落在一档;改到二/三档会被认,改到阶梯外的自定义价会被拉回一档。
- 三档的「成本前→后」用的是**当前持仓的摊薄总额**;正T若卖在摊薄成本线下方,成本线会**抬高**(摊薄口径的既定行为),这不是 bug。

---

## 阶段 17 · 提醒可见性:修渠道硬编码 + 应用内弹窗 ✅

针对「**怎么我在电脑上看不到消息弹出框?**」—— 用户在「通知设置」里把桌面通知打开、
点「测试」也显示发送成功,但**真到价了屏幕上什么都没有**。

| 层 | 问题 | 修法 |
| --- | --- | --- |
| 1 · 代码 | `PriceAlertService._channels_for()` 的**注释**写着「跟随全局已启用的渠道」,实现却硬编码 `return ["console"]` | 改成真去读 `notify_service.enabled_channels()`;读不到 / 全禁用时兜底 console(宁可只有日志也不要什么都不发) |
| 2 · 口径 | `enabled_channels()` 只读数据库行,而「通知设置」面板把**无数据库行的 console** 也算启用 → 两处口径打架 | `enabled_channels()` 改为遍历 `NotifyChannel` 枚举,与面板完全一致 |
| 3 · 平台 | Windows 11 26200:WinRT Toast 因**非打包进程没有 package identity** 被拒(`0x80073D54`);降级到 Win32 托盘气泡后 `ShowBalloonTip` **返回成功但屏幕上什么都没画出来**(抓屏证实右下角托盘区域无气泡) | **换一条不依赖系统通知的路**:提醒触发 → 事件总线 → SSE → 网页内弹窗 |
| 4 · 时机 | 调度器只在**工作日 9:15–11:35 / 12:55–15:10** 跑,非交易时段不评估 | 不改(避免无谓请求);改用**自检端点**当场验证通路 |

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 事件广播 | `backend/app/modules/alert/service.py` | 提醒**真的响了**(命中且通过冷却/日限流)→ `event_bus.publish("price_alert_fired")`。被限流的那次**不广播** —— 用户什么都没收到,再弹一次等于骗人 |
| 实时推送 | `GET /api/price-alerts/stream`(SSE) | 建连首帧补发最近 10 分钟真响过的(补断线期间漏掉的);后续帧实时推。前端靠 `trigger_id` 去重 |
| 降级轮询 | `GET /api/price-alerts/recent-fired` | SSE 连不上时前端退回来轮询它,别让用户漏掉提醒。只含 `status = "matched"` |
| 通路自检 | `POST /api/price-alerts/test-popup` | 广播一条**合成**事件,**零副作用**(不碰规则、不记流水、不消耗额度)。不然用户只能干等,分不清是「没到价」还是「弹窗坏了」 |
| 应用内弹窗 | `PriceAlertPopup.tsx` + `usePriceAlertStream.ts` + `usePriceAlertStore.ts` | 右下角醒目卡片:方向徽章 + 标的 + 条件 + 现价 + 「看待办 / 知道了」。**不自动消失**(价格提醒错过就是错过,只能手动关) |
| 全站可见 | `AppShell.tsx` | 挂在应用外壳上 —— 用户在盯盘页、在做T清单页,弹窗都冒得出来 |
| 配色 | 同上 | 涨跌红绿:`跌到`(条件含 `<=`)绿,`涨到`(含 `>=`)红 —— 说的是**行情方向**,不是好坏 |
| 浏览器系统通知 | `LocalNotifyCard.tsx` + `alertNotify.ts` | 浏览器自带 package identity,`new Notification()` 在 Win11 上能弹真正的通知中心卡片。**必须用户点一下才授权**,绝不自动弹权限框 |
| 应用内提示音 | 同上 | 两声短促提示音(880Hz → 1175Hz),配合弹窗,不用一直盯着屏幕。默认关;浏览器要求 AudioContext 在用户手势里启动,已挂一次性手势解锁 |

**验收（2026-11-04,实机）**

- 渠道修复:`enabled_channels = ['console', 'desktop']`;真实触发 `scan()` → `fired=1`,
  触发流水 `results = [{console, ok}, {desktop, ok, detail:"OK:BALLOON"}]` —— 修复前只有 console。
- 托盘气泡:**抓屏证伪**。气泡显示期间(t=1.2s / 4.5s)抓物理分辨率全屏与右下角托盘区域,
  **没有任何气泡像素** —— 这条路在 Win11 26200 上彻底失效,不是等待时间问题。
- 应用内弹窗:浏览器实拍确认 —— 右下角两条醒目卡片(合成自检一条 + 真实触发一条),
  背景不透明、文字清晰、方向徽章与涨跌色正确。

**已知边界**

- 应用内弹窗**要求页面开着**。页面关掉就收不到 —— 想在页面关着时也收到,得靠
  浏览器系统通知(需授权)或手机推送(Bark / 钉钉 / 企微,需配凭据)。
- 托盘气泡这条路在本机不渲染,所以「桌面通知」渠道开着也只是多写一份日志;
  真正管用的是应用内弹窗。
- 弹窗最多同时堆 4 条(更早的挤掉,别糊屏)。

---

## 阶段 18 · 提前预警:提醒提前 1% ✅

针对「**提醒应该提前提醒,而不是等到价格到了才提醒,这样才有操作空间**」。

到价提醒是「价格到了才响」—— 但**到了再响,操作空间已经没了**。挂单是「到了一档价就动手」,
而实际操作需要**提前把单子准备好**。

**口径**(用户问卷选定):**预警线 = 生效到价线朝基准线方向再退 1%**,数值上 ≈ 基准线。

| 方向 | 生效到价线(一档) | 预警线 | 含义 |
|---|---|---|---|
| 反T(待接回) | 基准线 × 0.99 | 到价线 × 1.01 | 价格涨回基准线附近 → 该准备接回 |
| 正T(待卖出) | 基准线 × 1.01 | 到价线 × 0.99 | 价格跌回基准线附近 → 该准备卖出 |

预警线与到价线**方向相反**(到价线等价格过来,预警线提前站在价格来的路上),
且基于**生效到价线**而非固定基准线 —— 用户把到价提醒改到二档,预警线跟着按二档算,**永远早一步**。

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 预警线计算 | `backend/app/modules/portfolio/t_pricing.py` | `PRE_ALERT_OFFSET = 0.01` + `build_pre_alert()` → 预警线 / `distance_pct`(绝对值)/ `reached` / `in_pre_zone` |
| 预警提醒生命周期 | `backend/app/modules/portfolio/t_alerts.py` | 建 / 就地改价(跟到价线走) / 挂单消失后停用(不删) |
| 一次性 + 重新武装 | `alert/service.py` + `alert/scheduler.py` | 命中即停用(不删,留触发历史);价格**离开**预警区后由**后端调度器**重新武装 —— 判据是「当前价不再满足预警条件」,不需要知道方向。⚠️ 不能只挂在清单页同步里:页面关着就不同步 → 预警响一次就哑了,与「页面关着也能收到」直接冲突 |
| 标记方式 | 同上 | `name` 前缀 `[做T·预警]`(与 `[做T]` 不重叠)+ 条件树**顶层** `kind="pre_alert"` / `once=true` |
| 引擎只透传 | `backend/app/modules/alert/engine.py` | `notification_meta()` 读条件树顶层的 `kind`/`once`,引擎不认识只透传 —— alert 模块保持通用,不硬编码 portfolio 的字符串前缀 |
| 清单页新列 | `TReminderPanel.tsx` | 「预警线 · 还差」:还差 X% / 已进入准备区 / 已越过 X% / 已预警 |
| 弹窗两种徽章 | `PriceAlertPopup.tsx` | 琥珀色 `warn`「准备」 vs 涨跌色「涨到/跌到」 —— 预警用中性色,**不占用行情红绿语义色** |

**验收(2026-11-04,live API + 浏览器实拍)**

```
REVERSE 001896.SZ 触发=8.771 预警=8.859 距离=0.67%  inZone=True   reached=False
FORWARD 000657.SZ 触发=36.34 预警=35.977 距离=1.91%  inZone=False
FORWARD 002185.SZ 触发=14.494 预警=14.349 距离=4.42% inZone=False
FORWARD 561980.SH 触发=0.446 预警=0.442  距离=2.29%  inZone=False
pre_created=4
```

- 浏览器实拍:清单页「预警线 · 还差」列正确显示,豫能控股显示「已进入准备区 · 还差 0.67%」。
- 弹窗实拍:琥珀色「准备」徽章 + 「快到了 —— 先把单子准备好」。
- 门禁:`test_t_pre_alert.py` 18 passed;`test_t_reminders` 等提醒相关回归 129 passed。

**已知边界**

- 预警是**提前信号,不是成交保证** —— 提醒响了不等于价格一定到。
- 只覆盖做T挂单**自动建**的预警;用户手工建的提醒没有预警线(不给别人的提醒擅自加规则)。
- 预警提醒命中后停用,由**后端调度器**在价格离开预警区后**重新武装** —— 不需要开着页面。
  (v0.20 补:原先只挂在清单页同步里,页面关着就永远不再武装。)

---

## 阶段 19 · Tailwind 死类名清理 + 静态门禁 ✅

**问题**:Tailwind 里类名拼错(`bg-bg-elev` 实际键名是 `bg-elevated`)**不报错、不警告**,
只是那条规则压根不生成 → **样式静默丢失**。项目里这种死类名有 172 处引用、涉及 44 个文件。

**表现**:输入框、徽章、hover 态**全都没有背景** —— 暗色底上缺背景的卡片跟深色底几乎融在一起,
截图都看不出来,往往要等很久才被当成「设计如此」。

| 原死类名 | 真实键名 | 修法 |
| --- | --- | --- |
| `bg-bg-elev` | `bg-elevated` | → `bg-bg-elevated` |
| `bg-bg-elev/30`、`/40` | 需支持透明度 | → `bg-surface-2/30`、`bg-surface-2/40`(`surface-2` 是 RGB 通道形式) |
| `bg-bg-subtle/60` | 同上 | → `bg-surface-3/60` |
| `bg-surface` | `bg-surface` | → `bg-bg-surface`(色键本身带 `bg-` 前缀,类名要写两遍) |
| `bg-accent-subtle/30|40|60` | `accent-subtle` 自带 12% 透明 | → `bg-accent-subtle`(叠 `/N` 一定失效) |
| `bg-accent-bg/40` | 无此键 | → `bg-accent-subtle` |
| `bg-warn-bg/30|40` | `warn-bg` 自带 14% 透明 | → `bg-warn-bg` |
| `bg-warning/10`、`text-warning`、`border-warning/*` | `warn` | → 全部换成 `warn` 系 |
| `border-border-base`、`divide-border-base` | `border-def` | → `border-border-def` / `divide-border-def` |
| `border-accent-primary` | `accent` | → `border-accent` |
| `divide-bd-subtle` | `bg-subtle` | → `divide-bg-subtle` |
| `border-l-dashed` | 非合法 utility | → `[border-left-style:dashed]`(只影响左边框) |
| `border-orange`、`text-orange` | Tailwind 无 `orange` 裸色 | → `border-[color:var(--chart-ma5)]`(复用既有图表橙,主题自适应) |
| `ring-bg-pri` | 无此键 | → `ring-text-pri` |

**配套改动**

| 项 | 位置 | 说明 |
| --- | --- | --- |
| RGB 通道变量 | `src/styles/tokens.css` | 补 `--bg-base-rgb`(深/浅两套),让 `bg-bg-base/80` 这类半透明可用 |
| 色键改通道形式 | `frontend/tailwind.config.ts` | `bg-base` 从 `var(--bg-base)` 改成 `rgb(var(--bg-base-rgb) / <alpha-value>)` —— `var()` 形式叠 `/N` 会被判非法 |
| content globs 补漏 | 同上 | 补 `src/lib` / `src/stores` / `src/hooks` —— 运行时拼出来的类名(如 `format.ts` 的涨跌色)只在这些目录里,漏扫 = 真实运行时没样式 |
| **静态门禁** | `frontend/scripts/check-tailwind-classes.mjs` | `npm run check:classes`:生成全量 CSS 作基准 → 扫源码类名 → 查不到的类名一律报错退出(非零退出码) |

**验收(2026-11-04)**

- 门禁:死类名 **36 → 0**(其中 13 个是配置文件里的色键名本身,属误报,已从扫描范围排除)。
- **门禁本身有效**:注入探针 `bg-bg-deadtest` / `border-border-deadtest` → 门禁 exit 1 并精确报出这两条;
  移除探针后 exit 0。
- 浏览器实拍三个页面(补T清单 / 价格提醒 / 盯盘主界面):输入框、徽章、卡片背景、hover 态、
  分割线全部恢复;主界面涨红跌绿正确。
- `tsc --noEmit` exit 0。

**踩过的坑(别重试)**

- 用 Python `read_text/write_text` 回写会把 LF 文件**全量改成 CRLF** → 整文件 diff 噪音。
  本仓库 `core.autocrlf=false` 且无 `.gitattributes` = **存 LF**;回写必须走二进制。
- `git show HEAD:<path>` 的路径是**相对仓库根**,不是相对 cwd —— 传相对 `frontend/` 的路径会静默失败,
  导致「基线换行符判定」全部失准。
- Tailwind CLI 必须在 `frontend/` 目录下跑(content globs 相对 cwd 解析);
  Node 24 起不能直接 spawn `.cmd` 包装,要走 `node node_modules/tailwindcss/lib/cli.js`。
- Tailwind 在 CSS 里写的是 `.text-text-ter\/40`(**反斜杠 + 斜杠**),用正则 `\/` 只匹配斜杠、
  吃不掉那个反斜杠 → 误判成「缺失」。要用字面量查找,别用正则。
- 类名替换必须带词边界:`bg-bg-elev` 会命中 `bg-bg-elevated`,`text-orange` 会命中 `text-orange-500`。

---

## 三、不做的事

| 项 | 原因 |
| --- | --- |
| 迁 Vite（弃 Next.js） | 无 SSR 收益需求，换栈成本高 |
| 引入 pnpm workspace 多包 | 13.6k LOC 后端拆多包收益低于成本 |
| 中英双语 i18n | 面向国内用户，纯负担 |
| 多用户鉴权 / PAT / MCP | 本地单机工具，不需要 |

---

## 四、版本节奏

| 版本 | 阶段 | 内容 |
| --- | --- | --- |
| v0.5.0 | 0 | 工程地基（测试基线、架构守卫、数据治理、CI、文档） |
| v0.6.0 | 1 | 通知渠道 + 价格提醒 |
| v0.7.0 | 2 | 选股权重可调 + 回测引擎 |
| v0.8.0 | 3 | 模拟盘 |
| v0.9.0 | 4 | 多智能体分析 |
| v1.0.0 | 5-6 | 多账户 / PWA / 架构迁移收尾 |
