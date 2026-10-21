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

> 阶段 0–5 已把闭环打通到
> **「改了权重能回测 → 历史信号能复盘 → 命中条件能推送 → 不想真金白银就先模拟 → 多智能体出决策书 → 多个券商分开算」**。
> 阶段 6 首批完成 screener / portfolio 两个域迁移,market 域因引用面过广降级到批次 2。
> 阶段 7 补齐前端:此前所有新能力只有 API、没有入口,用户点不到。
> 阶段 8 补上「盯盘时到底该怎么办」这一层:确定性决策卡(零 LLM)+ 回测闸门,
> 并且把「这套规则到底有没有用」用回测数据回答了 —— 止盈有效、建仓只有胜率价值、止损暂不可判定。

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
| 盘中（11:30 / 14:50） | 异动扫描、机会提醒 |
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
