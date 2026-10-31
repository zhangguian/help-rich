# 接口变更日志(API Changelog)

> 面向开发者。每次后端接口变更时追加一行。
> 与 `release-notes.md` 的区别:`release-notes` 面向用户(功能视角),本文件面向开发者(API 视角)。

## 变更模板

```
## YYYY-MM-DD | v0.1.x | 一句话变更主题

### Breaking(破坏性)
- 端点 X 字段 Y 从 int 改为 string(前端需同步)

### Added(新增)
- 新增端点 Z

### Changed(修改)
- 端点 X 字段 Y 默认值从 X 改为 Y

### Deprecated(弃用)
- 端点 X 将于 v0.2 移除

### Fixed(修复)
- 端点 X 在 Y 场景下返回错误码 Z 应为 W
```

---

## 历史记录

### 2026-10-29 | v0.13 | 秒级盯盘:行情 SSE 推送 + 热路径零缓存(ADR-0006)

#### Added(新增)
- **`GET /api/quotes/stream`(SSE)**:盘中行情推送。服务端单例轮询器(盘中 2s 一轮)拉
  「自选 ∪ 持仓」,经事件总线广播;首帧 `quote_snapshot`(含 `stale` / `updated_at`),
  后续 `quote_update` 增量,30s `:heartbeat` 保活;`?codes=` 可过滤。
- **`GET /api/quotes` 新增 `fresh` 查询参数**:`fresh=true` 走
  `QuoteService.get_quotes_fresh()` —— **跳过 5 分钟缓存**直取数据源(盯盘热路径)。
  降级路径(前端 SSE 断开)按 3s 轮询该端点。
- **`app/services/quote_poller.py`**:常驻轮询器 + 内存快照。
  连续失败退避 2→5→10→30s 封顶;无人订阅且无 REST 命中时降到 15s;非交易时段完全停拉。
- **`app/core/trading_time.py`**:盘中时段口径上提到 core(原在 `modules/alert/scheduler.py`),
  供告警扫描与行情轮询器共用同一份口径。

#### Changed(修改)
- **`QuoteService` 缓存分层**:新增 `get_quotes_fresh()`(跳过缓存)。
  `get_quote` / `get_quotes` 的 300s 缓存行为**完全不变**(研究/历史路径不受影响)。
- **价格提醒扫描改走 fresh 路径**:原先用 5 分钟缓存价判触达,最多会晚 5 分钟才响。
- **`modules/alert/scheduler.py` 复用进程级 `QuoteService` 单例**:此前每次 `new` 一个实例,
  httpx 连接池不复用、缓存各算各的。
- **错误码 `AKSHARE_FAILED` → `QUOTE_SOURCE_UNAVAILABLE`**:2026-10-29 评估 akshare 后
  **决定不引入**(东财系接口全部带 `ut` 令牌,在公司网络下被网关直接 RST),错误码按实际实现改名。

#### Fixed(修复)
- **首页报价不再只拉一次**:此前 `page.tsx` 的报价只在首屏取一次(之后价格不再更新);
  现在由 SSE 持续推送,端到端 ≤3s(3 秒快照档 / Level-1,**不是逐笔 Tick**)。
- **止损检查改实时价驱动**:此前用 `/positions` 的 5 分钟缓存价判定,盘中跌破止损线时
  弹窗可能晚数分钟;现主路径订阅实时价(SSE),15s 轮询降为兜底。

---

### 2026-10-27 | v0.12 | 盘中复盘面板:调度器容错 + 缺档明示 + 产出自动可见

#### Fixed(修复)
- **调度器单窗口失败不再杀死整个调度器**。
  盘中复盘依赖「当日作战计划」,而作战计划通常收盘后才生成 —— 所以 11:30 档**必然**抛
  「今日作战计划还没生成」。旧实现里这个异常直接冲出 `while` 循环 →
  **调度器当场死亡**(日志 `Task exception was never retrieved`)→
  当天后续所有窗口(含 14:00 那档)再也没人跑 → 当天两档复盘全空 →
  面板只剩「下一次盘中复盘 11:30,还有 1287 分钟」,用户完全看不到复盘内容。
  现在:① 单窗口失败只记日志并继续跑后面的窗口;② 失败的那档在**补跑有效期内**
  每 5 分钟重试;③ 下一档触发时先把之前没成功的档按时间序补上
  (例:14:00 触发时先把 11:30 补掉,再跑 14:00)。
- **推送失败不重试**。产出已经落库,重推 = 重复给用户发消息;
  只有**产出失败**才重试(那时什么也没发出去,重试安全)。
- **已经产出过的档不再重跑/重推**。调度器的「已跑」标记只存在内存里,
  后端一重启就忘了 —— 不查库的话,重启会把还在补跑窗口内的档**再产出一次、
  再推一次**(推送不可撤回,重复推就是重复打扰用户)。
  现在跑之前先查库:这档已在 → 直接跳过。**数据库才是「产出没有」的事实来源**。
- 盘中复盘面板**打开后轮询今日状态(30s)**,新档产出后自动切过去并重新取数。
  旧实现面板只取一次数据:面板先开着、档位后产出时,面板永远停在
  「下一次盘中复盘 11:30,还有 N 分钟」的空态 —— **复盘内容一次都露不出来**。
- 盘中复盘面板的复盘表格 **React key 补下标**:同一只票可以有多条同 label、
  触发价同为 `null` 的动作(如「明日别动」这类纪律类预案)。key 撞了 React 会警告,
  并**可能丢弃或重复渲染行** —— 表现就是表格里的预案少了几条。

#### Added(新增)
- `GET /api/intraday-review/schedule` 响应新增 `missing_slots`:已到触发时刻、
  但**还没产出**的档位(如 `["11:30"]`)。
  没有这个字段时,前端在「今天一档都没产出」的情况下只能显示
  「下一次盘中复盘 11:30,还有 1287 分钟」—— 用户完全看不出 11:30
  **已经到点却没产出**,看起来像「跑过了只是没显示」。
  纯增量字段,旧客户端不受影响。

#### Changed(修改)
- 调度器 `due_windows()` **不再自己标记「已跑」** —— 标记只发生在**产出成功之后**。
  语义从「问一次就算跑过」改为「成功才算跑过」,失败的那档还能补跑。
  连带影响:同一时刻 `due_windows` 会同时返回**早档与当前档**(按时间序),
  这是「跨窗口补早档」的必要条件,不是回归。
- 补跑截止时刻(当天):`premarket` 9:29 / `intraday_am` 14:29 / `intraday_pm` 15:59 /
  `postmarket` 23:59。两档盘中刻意错开,让 14:00 那一轮既能补 11:30 也能跑 14:00。
- 盘中复盘面板的档位切换标签行**同时列出「待补」档**(如 `11:30 待补`)。
  只列已产出的档位时,今天只产出了 14:00 的话标签行根本不渲染(只有 1 档)——
  用户点不到缺的那档,也就看不到「为什么这一档是空的」。

#### Test(测试)
- 新增 `tests/test_workflow_scheduler_resilience.py`:失败可补跑 / 成功不重跑 /
  重试间隔 / 补跑截止 / 跨窗口补早档 / 推送失败不重试 / 已产出过则跳过 /
  状态按天清理 / **调度器主循环单窗口异常不退出**(回归 2026-10-27 事故)
- `tests/test_intraday_review_api.py` 新增 3 条 `missing_slots` 契约测试
- `tests/test_workflow_scheduler.py`、`tests/test_workflow_agent.py` 既有断言按新契约改写
  (语义变了,不是回归)
- 真机实测(tabbit):真实状态 10/10 + 「面板先开着、档位后产出」场景 12/12,console 零错

### 2026-10-25 | v0.11 | 作战计划 v2:沪深全市场滚动池 + 三栏工作台

#### Breaking(破坏性)
- `GET /api/battle-plan/scope`:**返回类型从 `list[dict]` 改为对象** `{watchlist, pool, universe}`
  - `watchlist`:持仓 ∪ ★关注(持仓优先,组内保源顺序),字段不变
  - `pool`:**当前**在池成员(读 `battle_plan_pool` 表,**不是**「今天会选出什么」),
    字段 `stock_code / stock_name / miss_streak / last_status / last_score / joined_on`
  - `universe`:全市场口径统计 `{total, main_board, non_st, after_filters, min_amount_yi}`,
    快照不可用 → `null`
  - ⚠️ 调用方只有一处(作战计划空态),同批改完,不留中间态。
- `GET /api/battle-plan/scope`:**不再回传 `shares` / `avg_cost`** —— 真实持仓成本不扩散到出参
  (与 `meta.scope` 口径一致)。

#### Added(新增)
- `GET /api/battle-plan` 与 `POST /api/battle-plan/generate` 的 `meta` 新增三个字段:
  - `pool`:全市场滚动池 `{limit, members[], dropped[], candidates_considered, universe}`
    - `members[]`:`stock_code / stock_name / score / reason / state(kept|added) / miss_streak / last_status / streak_note`
    - `dropped[]`:`stock_code / stock_name / miss_streak / reason`(被剔除的票,仍留在前端锚点栏以便回看)
  - `quotes`:`{stock_code: {price, change_pct}}` —— 左栏股票锚点栏要显示现价与涨跌幅
  - `timings`:`{fulfillment, select_stage, select_pool, decisions}` 各阶段耗时(秒)
- 新增表 `battle_plan_pool`(跨天实体:滚动池记忆,日报 items 会被次日覆盖,池不会)

#### Changed(修改)
- `POST /api/battle-plan/generate` 的覆盖口径:从「持仓 ∪ ★关注」扩到
  **自选全覆盖 + 沪深全市场主板滚动池 5 只**;上限 = `min(自选数 + 5, 30)`,
  截断优先级「先砍池尾 → 再砍 ★关注尾 → 持仓永不砍」
- `POST /api/battle-plan/generate` 编排顺序重排:**昨日兑现判定提前到最前**
  (滚动池要用「昨天有没有达到预期」,判定只算一次、池与复盘共用同一份结果)
- `GET /api/battle-plan?date=` 的 `review.fulfillment.items` 语义不变(仍是**逐条**兑现);
  股票级状态由前端 `lib/planDerive.ts` 按 `executed > touched > missed > no_data > n_a` 聚合

#### Fixed(修复)
- 「达到预期」的口径统一为 `touched | executed`;**只有 `missed` 累计连续天数**,
  `no_data / n_a / pending` 不累计(缺数据不惩罚股票)

### 2026-10-25 | v0.10 | 操作建议增强:六格 + 网格交易配置建议 + 口径统一

#### Added(新增)
- `GET /api/stock/{code}/decision-advice`:把决策事实包翻译成大白话
  (**按钮触发**,不在首屏自动烧 token;LLM 未配置/超时 → `source='rule'` 退回规则文案,仍 200;
  进程内当日缓存,key = 代码 + 日期 + headline 摘要)
- `GET /api/stock/{code}/decision` 响应新增(v0.10,**纯增量**,旧字段语义不变):
  - `suggestions`:操作建议六格(价位 / 止损 / 仓位 / 触发 / 时间 / 不动),**值可为 null**(= 数据不足,前端整格不渲染)
  - `grid_plan`:网格交易配置建议(区间 / 格数 / 步长 / 每格净收益 / 需资金 / 失效条件 / `mode` 加仓|底仓)
  - `advice`:规则白话兜底(零 LLM,`source` 恒为 `rule`)
  - `cost_anchor` / `time_window` / `cost_effect` / `instrument_rule` / `concentration`:五个补维度
- 新增 `backend/app/services/decision_advice_service.py`(事实包 + 规则白话 + LLM 白话)
- 新增 `backend/app/services/decision_context_service.py`(**共享装配口**):
  决策卡与计算器 T 卡共用同一份新输入(费用档 / 账户现金 / 集中度 / 持有天数)→ 两处口径必然一致

#### Changed(修改)
- `GET /api/stock/{code}/analysis`:**提示词注入决策事实包**,并加硬规则「数字必须原样引用,冲突时以事实包为准」
  —— AI 解读的价位 / 止损 / 仓位与决策卡**同源**,不再两套说法;
  响应结构不变,`ai=null` 行为不变,**不增加网络 IO**(复用该端点已有的 klines / quote / position)
- `GET /api/stock/{code}/decision` 新增 4 项 IO 输入(全部本地 DB 查询,零网络):
  费用档(按品种选档,ETF 免印花税/过户费)、账户可用资金、持仓成本占比、持有自然日
- 费用口径新增 `fee_basis` 标记:`configured`(用户已启用费用设置)/ `default_estimate`(未启用,按费率档估算)
- `time_window` 新增 `source`(起点来源:`transactions` = 最早一笔流水 / `snapshot` = 快照导入日)
  与 `overdue_text`(超期文案);`note` 与六格「时间」格的措辞随来源变化 ——
  快照导入的票真实建仓日未知,只说「自纳入本系统起 N 天(建仓日未知)」,**不写「已持有 N 天」**

#### Fixed(修复)
- 「持有天数」原计划取 `Position.base_date` —— 该字段**从未落库**(只是导入接口入参),
  改为「最早流水日期 → 持仓行落库日」两级取数,并在文案里如实标注口径
- 网格每格资金与每格利润原被混为一谈(会让「所需资金」与「每格净收益」同时算错),
  已拆为 `capital_per_grid`(一手金额)与 `net_profit_per_grid`(毛收益 − 往返费用)
- 「持有天数」原只输出 `overdue` 布尔值(超期了但卡上看不出超期多少天),
  已补 `overdue_text`,并让六格「时间」格带上超期信号
- 快照导入的持仓原显示「已持有 0 天」(把"不知道真实建仓日"说成了"今天刚买"),
  已按起点来源改为「自纳入本系统起 0 天(建仓日未知)」

#### Test(测试)
- 新增 `tests/test_decision_grid.py`(网格 9 条判据)、`tests/test_decision_advice_service.py`、
  `tests/test_decision_context_service.py`;扩写 `tests/test_decision_service.py`(五维度 + 六格 + 零回归)
- `tests/test_decision_api.py`:`/decision` 零 LLM 守卫改为「LLM 字段一律不得出现 + `advice.source` 必须是 `rule`」,
  新增 `/decision-advice` 降级断言与「analysis 收到事实包」断言

### 2026-10-25 | v0.6 | 场内 ETF 品种识别 + 交易规则适配(费用 / T+0 / 无涨跌停)

#### Added(新增)
- `GET /api/stock/{code}/analysis` 新增三个字段:`industry`、`industry_source`、`industry_note`
  (节点缓存命中与未命中**两条路径都注入**;ETF → 「跟踪 {指数}」+ `source=etf_index`,股票 → baostock 行业名)
- `GET /api/stock/{code}/industry` 的 `source` 新增取值 `etf_index`;ETF 返回「跟踪 {指数}」+ `note`「场内 ETF · {类别}」
- 静态品种表 `backend/app/data/etf_instruments.json`(46 项,含 category / t0 / form 字段),
  判定层 `backend/app/core/instrument.py`(`resolve_instrument` / `fees_for_instrument` / `degraded_note`)

#### Changed(修改)
- `POST /api/calculator` 与 `POST /api/calculator/review`:费用按品种选档 —— 场内 ETF/LOF **免印花税、免过户费**,佣金沿用
- `POST /api/calculator/review`:`t_plus_one_note` 按品种分流;T+0 品种的**正T 上限只受资金约束**(不再受可动 T 仓 M 约束),反T 仍受 M 约束
- `GET /api/annual-report/{year}`:逐笔按品种选费用档
- 追高文案按品种分流:ETF 不再说「涨停」,改说「当日涨幅已达 X%,不追高(ETF 无涨跌停限制,涨幅可以更大)」
- AI 风险清单 / PM 严重风险按品种分流(ETF → 折溢价 / 跟踪误差 / 汇率 / T+0 规则差异)

#### Deprecated(弃用)
- 无。请求体与响应结构**均未变**,品种差异只体现在取值与文案上。

#### Fixed(修复)
- 行业归属兜底顺序调整为 baostock → **ETF 本地表** → 新浪 → 降级:命中 ETF 是纯本地判定,
  原顺序会让每个 ETF 请求白等一次新浪网络超时
- 前端 `stockCode.ts` 缺失 `['5','SH']` 前缀 → 认不出沪市 ETF(前后端市场推断不一致)

#### Test
- 新增 56 条(`test_instrument.py` 24 / `test_trade_review_service.py` +12 / `test_industry_service.py` +14 /
  `test_calculator_api.py` +5 / `test_decision_service.py` +1);全量 **1548 passed 零红**(基线 1492)
- 真机实测(tabbit):自选/持仓/个股页徽章渲染正确、零 console 错误;T+0 正T 上限 16,500 股(资金约束)
  vs T+1 上限 500 股(可动 T 仓约束);实测用临时持仓与账户资金测完已清理

---

### 2026-08-02 | v0.4.4 | MiniMax 迁移新平台 minimaxi.com(适配 Token Plan 订阅 Key)

#### Changed(修改)
- **根因**:用户订阅的是 Token Plan,但应用里配的是按量计费 API Key。**订阅 Key 与按量 API Key 不可互换**(官方文档),订阅额度消费必须用「订阅 Key」(账户管理 / Token Plan 页面获取)。旧 Key 在旧平台 api.minimax.chat / 新平台 api.minimaxi.com / 国际版 api.minimax.io 全部 1008 / 402 / 401
- **`MiniMaxClient` 迁移**:
  - 端点 `api.minimax.chat/v1/text/chatcompletion_v2` → `api.minimaxi.com/v1/chat/completions`(OpenAI 兼容,与 DeepSeek/豆包同构)
  - 文本模型 `abab6.5s-chat` → `MiniMax-M2.5-highspeed`
  - 视觉模型 `abab-v-chat` → `MiniMax-M3`(支持图片输入,截图识别保留)
  - 请求体加 `reasoning_split: true`(M2.x thinking 不可关闭,思考进 `reasoning_content`,`content` 干净)
  - 新增 `strip_think()` 剥除 `<think>…</think>` 块(双保险,防止未来 thinking 行为变化污染 AI 解读 JSON 解析)
  - 错误处理保留 `base_resp` 检查(新平台实测仍返回该字段)
- `factory.py` / 测试断言模型名同步更新

#### Test
- 新增 1 条(think 标签剥离纯函数 + chat 集成);断言更新(端点/模型/reasoning_split);总 331 全绿
- 端到端实测:analysis 返回 bearish + 完整中文解读(引用真实 MA/斜率);chat 结合持仓成本返回 1392 字回答

### 2026-08-02 | v0.4.3 | analysis/chat 卡死修复:LLM 总时间预算 + MiniMax 余额不足识别

#### Fixed(修复)
- **请求无响应(挂起)**:`GET /api/stock/{code}/analysis` 的 LLM 调用无总时间预算,慢模型 + 退避重试可达 90s+。加 `asyncio.wait_for` 预算(analysis 25s / chat 40s),超时自动降级 `ai=null` / 503,接口保证快速返回
- **MiniMax 余额不足导致解析崩溃**:MiniMax 错误藏在 HTTP 200 body(`base_resp.status_code=1008 insufficient balance`),原解析 `data["choices"][0]` 抛 `'NoneType' object is not subscriptable`。修复:非零 `base_resp` → 明确 LLMError;`choices` 为空 → 明确 LLMError(不再 NoneType 崩溃)
- **chat 不再 500**:`ask_stock_question` 的 LLM 调用异常(余额不足/网络)原样冒泡 → FastAPI 500;现在统一转 `StockAdviceUnavailable` → 503 `LLM_UNAVAILABLE`

#### Test
- 新增 4 条:analysis 超时降级 / chat 超时 503 / chat LLM 报错 503 / MiniMax base_resp 余额不足 + choices 空;总 330 全绿

### 2026-08-02 | v0.4.2 | 技术指标 + AI 解读层(买股工具室核心)

#### Added(新增)
- `GET /api/stock/{code}/analysis`:技术指标 + AI 白话解读。返回 `{stock_code, indicators, ai}`:
  - `indicators`:均线(ma5/10/20/60 + ma_series 各 60 点)/ 量能(量比 ratio、放量缩量 state)/ 通道(线性回归斜率,窗口 60,阈值 ±0.0015)/ 支撑压力(MA20/MA60 + 近 20/60 日高低点)/ 企稳三段式(站上 MA20 + 回踩不破前低 + 末日量能放大)
  - `ai`:LLM 白话解读(看多看空中性 view + 趋势/量能/关键价位/操作建议/风险提示);LLM 未配置或失败 → `ai: null` 纯指标降级,页面永不空白
  - 错误码:代码格式非法 → 422 `INVALID_STOCK_CODE`;K 线数据源不可用 → 502 `DATA_SOURCE_UNAVAILABLE`
- `POST /api/stock/{code}/chat` body `{question}`:单轮 AI 问答(持仓成本自动从 positions 取,喂给 LLM);未配置 Key → 503 `LLM_NOT_CONFIGURED`
- `app.services.ta_service.compute_indicators`:纯确定性指标计算(输入 120 根日 K,零 LLM 参与)
- `app.services.stock_advice_service`:get_stock_analysis / ask_stock_question(pydantic schema 校验 + JSON 提取容错 markdown 代码块)

#### Test
- 新增 `tests/test_ta_service.py` 17 条 + `tests/test_stock_advice.py` 14 条(FakeLLM + fake httpx 拦截新浪);总 325 全绿

### 2026-08-02 | v0.3.0 | Day 8 A3 多 Provider 占比月度统计

#### Added(新增)
- `GET /api/provider-stats/monthly?year=2026`:12 个月 Provider / status 分布(空月补全)。每条 `{month, total, providers, statuses}`
- `GET /api/provider-stats/summary?year=2026`:年度汇总(柱状图友好)`{year, total, providers: [{provider, count, pct}]}`(按 count 降序)

#### Test
- 新增 `tests/test_provider_stats.py` 8 条:空年 / 单月单 provider / 多 provider / 多月+多 status / 跨年排除 / 默认年份 / 空汇总 / 占比正确

### 2026-08-02 | v0.4.1 | 一键清仓 API(P-stop-loss-v2)+ 板块资金异动 SSE

#### Added(新增)
- `POST /api/positions/{code}/clear` body `{price, note?}`:一键清仓(201,返回 `stock_code/shares/price/realized_pnl/trade_id/trade_date`)。自动创建一笔 sell 流水覆盖全部股数,触发 `recalc_position` 删除持仓行。`price <= 0` → 422;无持仓 → 404 `POSITION_NOT_FOUND`
- `GET /api/sector-fund-flow/events?fenlei=N`(可选):SSE 订阅板块资金异动(后台调度器每 60s 拉一次 fenlei=0 排行,异动 publish `sector_fund_flow_alert`)

#### Changed(修改)
- `aggregate_positions(transactions, strict=True, keep_zero=True)`:新增双开关
  - `strict=False`:跳过 sell > 持仓校验(用于 recalc 的 delta+flow 模式,允许 row 导入基准抵消纯流水 sell)
  - `keep_zero=False`:不过滤 shares <= 0(返回负股数让 recalc 算出 new_shares=0 走清零分支)
- `recalc_position` 调用 `aggregate_positions(strict=False, keep_zero=False)`;清仓判断由 `new_shares <= 0 and new_cost <= 0` 改为 `new_shares <= 0` 一律删行
- `sector_fund_flow_service`:新增异动检测纯函数 `_detect_alerts`(净额绝对变化 ≥ 1 亿 / 领涨股切换 / 新进榜)+ `start_sector_scheduler` 后台 60s 拉取 + publish
- `main.py` lifespan 启动 2 个调度器(单只 + 板块)

#### Test
- 新增 `tests/test_clear_position.py` 6 条:清仓生成 sell 流水 / 亏损清仓 / 默认 note / 无持仓 404 / 纯 6 位规范化 / price 校验
- 新增 `tests/test_sina_data.py::TestSectorFundFlowAlerts` 7 条

#### Added(新增)
- `GET /api/sector-fund-flow/events?fenlei=N`(可选):SSE 订阅板块资金异动。后台调度器每 60s 拉一次 fenlei=0 排行,异动(净额绝对变化 ≥ 1 亿 / 领涨股切换 / 新进榜)publish `sector_fund_flow_alert`,客户端按 fenlei 过滤(不传 = 全部)
- `app.services.sector_fund_flow_service.start_sector_scheduler(interval_sec=60)`:后台调度,异动检测纯函数 `_detect_alerts`(可单测)
- `main.py` lifespan 启动 `start_sina_scheduler` + `start_sector_scheduler` 两个调度器

#### Changed(修改)
- `sector_fund_flow_service` 新增异动检测工具函数 `_detect_alerts / _to_snapshot / reset_snapshots`(纯函数)

#### Test
- 新增 `tests/test_sina_data.py::TestSectorFundFlowAlerts` 7 条:无变化无 alert / delta 超阈值触发 / 新进榜 / 小净额不触发 / 领涨股切换 / fenlei 透传 / 自定义阈值

### 2026-08-02 | v0.4.0 | 持仓主数据化(持仓可导入 / 流水自动同步)+ 产品更名

#### Breaking(破坏性)
- `GET /api/positions` 语义变更:不再从流水实时聚合,改读 `positions` 主数据表(流水录入自动同步,导入/手动调整的持仓也可见)
- `POST /api/screenshot/{id}/confirm`(screenshot_type=position/holdings):不再返回 422 `HOLDINGS_NOT_PERSISTED`,改为逐行写入持仓主数据(缺 code/shares → 422 `MISSING_FIELD`;缺成本价 → 422 `MISSING_PRICE`)
- `GET /api/annual-report/{year}` 新增 `no_transactions` 字段(默认 false;无流水时 true,前端提示"可直接导入持仓")
- 产品名:盘后诊股室 → 买股工具室(副标题 → 个人股票投资辅助工具)

#### Added(新增)
- `POST /api/positions`:手动录入 / 覆盖单只持仓(201,body `{stock_code, shares, cost_price, stock_name?}`,覆盖语义,已实现盈亏保留流水部分)
- `DELETE /api/positions/{code}`:删除单只持仓(204,联动删除该股全部流水 + 评分,防 recalc 复活)
- `GET /api/holdings-health`:持仓体检(真实持仓表 + 实时行情 + calc_risk;组合市值/浮盈/盈亏率/风险 + 单只 status profit|loss|flat|high_concentration|unknown + concentration_pct;行情失败降级成本价并标记 price_available=false / quotes_unavailable)
- `positions` 表 + Alembic 迁移 `b4c2d1e6f7a8`(含从流水聚合 backfill 初始持仓)

#### Changed(修改)
- 流水变动自动同步持仓:POST/PATCH/DELETE /api/transactions 后重算该股持仓(`capture_delta` 变更前捕获导入基准 → `recalc_position` 变更后应用;卖出超额校验改读持仓主数据)
- 诊断上下文:position_before = 导入基准(delta) + 交易前流水聚合;集中度维度读真实持仓表

#### Test
- 新增 `tests/test_positions_v040.py` 17 条:流水同步/卖出减仓/清仓删行/超额拒绝/导入基准保留/CRUD/删除联动/截图导入端到端/年账单 flag/体检;总 273 全绿

### 2026-08-01 | v0.3.3 | 板块资金排行 + 7×24 快讯(新浪 guide §7 / §9.2)

#### Added
- 新增 `GET /api/sector-fund-flow?fenlei=0|1|2|3&num=20&sort=netamount|netbuy|change`:新浪板块资金流排行(`MoneyFlow.ssl_bkzj_bk`,实测 200)。返回 `{fenlei, fenlei_label, count, items[]}`,item 含 `name/change_pct/inamount_yi/outamount_yi/netamount_yi/turnover_yi/top_stock`;非法 fenlei/num/sort → 400 `INVALID_*`;数据源不可用 → 502 `DATA_SOURCE_UNAVAILABLE`
- 新增 `GET /api/news/sina?page=1&page_size=20`:新浪 7×24 快讯(`zhibo.sina.com.cn/api/zhibo/feed`,实测 200,兼容 JSONP / 纯 JSON 两种返回)。返回 `{page, count, items[]}`,item 含 `id/rich_text/type/create_time/tag`;参数越界 → 400;数据源不可用 → 502 `DATA_SOURCE_UNAVAILABLE`

#### Changed
- `app/data/sina.py` 新增 `fetch_sector_fund_flow_rank()` / `fetch_sina_news()`(复用 `SINA_HEADERS`,`trust_env=False` 直连,JSONP 剥壳正则 `\((.*)\)\s*;?\s*$`)

#### Test
- 新增 `tests/test_sina_data.py` 9 条:板块资金解析 / 非数组报错 / 快讯 JSONP + 纯 JSON / 非法 JSONP 报错 / 端点 200 / 400 / 502

### 2026-08-01 | v0.3.2 | 完全删除 mock 数据 + 接真实数据源(guide)

#### Changed
- **K 线**:`kline_service.fetch_klines` 完全删除 `_mock_klines()`;改接 guide §3.2 新浪 `https://quotes.sina.cn/cn/api/jsonp_v2.php/.../CN_MarketDataService.getKLineData`(实测 ✅ 200);返回失败抛 `KLineSourceUnavailable`;`GET /api/kline/{code}` 数据源不可用时返 502 `DATA_SOURCE_UNAVAILABLE`(无 mock 兜底)
- **资金流**:`fund_flow_service` 完全删除 `_random_event()`;改接 guide §7 新浪 `https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_ssggzj`(排行,实测 ✅ 200);后台 `start_sina_scheduler` 每 60s 拉 SH/SZ/BJ 三市场前 50 名;`generate_one` 查指定股 → 数据源不可用或不在排行返 `FundFlowSourceUnavailable`(502)

#### Removed
- **`_mock_klines()` 随机游走** + **`_random_event()` 资金流分类权重** + **`start_mock_generator` 假数据后台任务**——全部删除,生产代码 0 mock

#### Test 改用 httpx.MockTransport(测试基础设施,**非生产 mock**)
- 23 条新测试(11 K 线 + 12 资金流)用 fake `httpx.AsyncClient` 拦截,验证 endpoint shape + 解析 + 错误处理

#### 端到端实测
- K 线 `GET /api/kline/600519.SH?limit=3` → 200,3 根日 K 真实数据(2026-07-30 ~ 2026-08-01,价格区间 1505-1582)
- 资金流 `POST /api/fund-flow/600519.SH/generate` → 502 `DATA_SOURCE_UNAVAILABLE`(茅台今日不在新浪前 80 名资金流,真实场景友好提示)

### 2026-08-01 | v0.3.1 | 风险敞口报告 + A2 真实数据源 blocked 标记

#### Added
- **风险敞口 API**(C1):`risk_service.calc_risk()` + 1 端点:
  - `GET /api/risk-report` 返回:总持仓 / 总市值 / 单股集中度 / HHI 指数 / 板块分散 / 风险评分(0~100,三档 低/中/高)+ 智能警告(集中度 > 30% / HHI > 2500 / 同板块 / 持仓过少)
  - 风险评分权重:单股最大占比 40% + HHI 30% + 持仓数 15% + 板块数 15%
- **风险报告页面** `/risk-report`:4 宫格 + 警告区 + 单股集中度横向条形图 + 板块分布,首页 [🛡 风险报告] 入口

#### Blocked(v0.2.5+ 跟进)
- **A2 资金流真实数据源**:东财 `push2.eastmoney.com` 在公司网络被防火墙 RST(直接 + akshare 包装 + qgqpBId cookie 都无法连通,curl 000),网易 `money.163.com` 502,新浪/腾讯无资金流分类字段。**所有免费数据源 blocked by 公司网络**;真实接入需付费 API(雪球 Pro / 同花顺 iFinD / Wind)或公司网络放行东财 IP 段。当前继续用 v0.2.1 mock 流式推送
- **K 线接真实数据源**:同上(底层走东财 blocked)。当前用 mock 随机游走(虽然新浪 money.finance.sina.com.cn K 线 API 通,可作为低成本替换)

### 2026-08-01 | v0.3.3 | 智能调仓建议(A4)

#### Added
- **调仓建议 API**(A4):`rebalance_service.calculate_rebalance()` + 1 端点:
  - `GET /api/rebalance-suggestion` 返回:总市值 + 建议列表 + 整体 summary
  - 4 种建议类型:`reduce`(单股 > 30%) / `add`(持仓 < 3) / `diversify`(同板块 ≥ 3) / `alert`(top1 > 50%)
  - 优先级 high/medium/low;建议减仓比例 suggested_pct
- **调仓建议页面** `/rebalance`:4 宫格(总市值/建议数)+ 整体 summary + 建议列表(类型/优先级/标题/原因/建议%);首页 [🎯 调仓建议] 入口

#### 设计说明
- **MVP 纯结构判断**:不依赖实时价(Position 模型没 current_price 字段),用持仓总成本作市值估算
- v0.3 接入实时价后扩展"浮盈"判断
- 真实交易 API(止损/加仓执行)按规划 v0.3+ 接入

#### Test
- 9 条新测试覆盖:空持仓 / 减仓 / 整仓偏重 / 持仓过少 / 板块集中 / 健康状态 / summary 计数

#### 端到端实测
- 4 只股票(600519.SH 茅台 700 股 + 3 只 100/200 股)→ total 1087400,茅台单股 96.6% → 1 reduce(high)+ 1 alert(medium),summary "共 2 条建议(1 高)(1 中)"

### 2026-08-01 | v0.2.0 | 截图字段语义统一(holdings 处理)

#### Fixed
- **`POST /api/screenshot/{id}/confirm`**:`holdings` / `position` 类型不再静默忽略(原 bug),改为显式拒绝 + `422 HOLDINGS_NOT_PERSISTED`(持仓是视图,不入库;请通过 `/api/transactions` 录入每笔流水)。前端 ScreenshotPreview 收到此 code → toast 警告 + 按钮置灰"持仓不入库"
- **`POST /api/screenshot/{id}/confirm`** 端点新增 `ScreenshotError` catch,改回 `422` 友好提示(此前会冒到 500)

#### Changed
- **前端 `ScreenshotPastePanel`**:示例改三选一(流水 / 持仓 / 自选股),覆盖截图识别主要场景
- **前端 `ScreenshotPreview`**:通用化列渲染,遍历 `items[0]` 的 keys 自动生成表头 + 中文标签映射;整数/金额/百分比各自格式化(`shares` 右对齐 + `font-mono`,`price` 加 `¥`,`profit_ratio` 显示正负号)

### 2026-08-01 | v0.1.9 | 数据备份 / 状态三件套 / 反思卡(P7.3/P7.5/P7.9)

#### Added
- 新增 3 个管理端点(backend):
  - `GET /api/admin/export`:导出 7 表 JSON(LLM Key 加密字段自动排除;截图大字段 ocr_text/raw_response 节省体积);带 `Content-Disposition: attachment` 头触发下载
  - `POST /api/admin/import`(body `{payload, mode: "replace"}`):清空 7 表后全量还原;ISO 日期字符串自动转 date/datetime;缺失 fields 自动过滤
  - `POST /api/admin/backup`:写一次 JSON 到 `backups/pre-{ts}.json`(文件备份归档)
- 新增前端组件:
  - `ExportImportCard`(P7.3):导出下载 + 导入二次确认弹窗(防止误清库)
  - `ReflectionCard`(P7.5):22:00 后 + 当日有交易时显示"今日反思"卡(笔数/已实现盈亏/提示语);localStorage 持久化 dismiss
  - `SkeletonState / ErrorState / StaleState`(P7.2):统一三件套(骨架屏/错误重试/15min 数据陈旧提示)
- 设置页加 ExportImportCard;首页挂 ReflectionCard

#### Test
- 7 条 admin 端点测试 + round-trip(导出 → 删库 → 导入 → 一致性)PASS

### 2026-08-01 | v0.1.8 | 前端 MVP 收尾(Day 5/6/7 前端)

#### Added
- `/settings` 设置页(P7.3):
  - LLM Provider 卡(P7.11):3 个 provider 单选切换,激活高亮,未配置灰显
  - LLM Key 卡(P7.12):密码框 + 显示/隐藏 + [测试连接] + 状态色
  - 截图识别入口卡(P8.9)
- `/transactions` 升级(P4.5~P4.10):
  - ScoreBadge(5 档色 + 滚动数字动效)
  - ScoreDetail 弹窗:三态(pending 骨架屏 / success 完整 / failed 重试)
  - 评语反馈按钮(👍 有用 / 👎 没用 → PUT /api/diagnose/{id}/feedback)
  - 脱敏 tooltip 展开实际传给 LLM 的 6 项字段
  - 重新评分按钮(A/B 重生成,P7.11 关联)
- 首页持仓卡(P5.3):[+ 设止损] / [🛡 ¥价格][⚡ 模拟触达][🗑 删除]
- StopLossAlert 全屏提醒(P5.4):必选其一(止损离场/再扛一下/静音)+ Web Notification + vibrate + 蜂鸣
- 截图上传向导(P8.6~P8.10):上传/粘贴双模式 + Dropzone + 预览表格 + 置信度标记 + 确认入库/重试
- OnboardingHint(P7.1):3 步骤引导(localStorage 持久化关闭)
- 通用 Modal 组件(maskClosable/escToClose 控制)

#### Changed
- SSE 客户端封装(P4.6):失败 3 次降级 5s 轮询 + online 事件回切 + localStorage 持久化 + 心跳过滤
- 首页新增 [⚙ 设置] 入口链接

#### Fixed
- `scorer._interval_score` 期望 dict 但 diagnose_service 传 ORM 对象,导致 8 笔评分 BackgroundTasks 静默失败;修:recent 双轨(ORM 给 recent_summary + dict 给 score_trade)

### 2026-08-01 | v0.1.7 | 止损 + 评语反馈 + 年账单(P4.9/P5.1/P5.2/P6.1)

#### Added
- 新增止损 4 端点:
  - `POST /api/stop-losses`(body `{stock_code, stop_loss_price, enabled, notify_*}`):设置/更新(stock_code 规范化,同 code 覆盖);价格 ≤ 0 → 422
  - `GET /api/stop-losses`:止损列表
  - `DELETE /api/stop-losses/{code}`:删除;未设置 → 404
  - `POST /api/stop-losses/{code}/triggered`:标记今日触发,**幂等**(同日重复返回 200 + `duplicate=true`);未设置 → 404
- 新增 `PUT /api/diagnose/{trade_id}/feedback`(body `{feedback: "useful" | "useless" | null}`):评语价值反馈;非法值 → 422,交易不存在 → 404
- 新增 `GET /api/annual-report/{year}`:年账单聚合(realized_profit / realized_loss / net_pnl / closed_count / win_rate / top5_profit / top5_loss);年份越界 → 400;**v0.2 接口预留,前端砍**
- 新增 `trade_scores.feedback` / `stop_losses` 表

#### Changed
- 所有止损写路径用 `safe_write` 包(backend-arch §4.6.1 写锁表第 4 行修复)

### 2026-08-01 | v0.1.6 | 截图识别后端(P8.1~P8.5)

#### Added
- 新增 5 个截图识别端点:
  - `POST /api/screenshot/upload`(multipart):上传截图,OCR(PaddleOCR 本地)+ 规则/LLM 解析,返回待确认 items;非 jpg/png/webp → 415,>5MB → 413,OCR 失败/无 Key → 422(提示降级)
  - `POST /api/screenshot/parse-paste`(body `{raw_json}`):降级路径,粘贴外网模型 JSON;非法 JSON → 422 `INVALID_JSON`
  - `GET /api/screenshot/pending`:待确认列表
  - `POST /api/screenshot/{id}/confirm`(body `{items, screenshot_type}`):确认后入库 transactions / watchlist;已确认 → 409,空 items → 422
  - `POST /api/screenshot/{id}/reject`:取消,删除原图
- 新增 `screenshot_records` 表(pending / confirmed / rejected 状态机)
- 新增 `GET /api/llm/providers` + `GET/POST /api/llm/settings`(v0.1.5 已列,本轮文档对齐)

#### Changed
- `POST /api/llm/test` 升级为真实 API 调用(仅 Key 格式校验的旧行为移除)

#### Fixed
- watchlist 仓储按主键 `id` 查 `stock_code` 的 bug(与 trade_scores 同源,`contains`/`add`/`remove` 全部修正)——此前自选股判定恒 False

### 2026-08-01 | v0.1.5 | Provider 设置 API 升级(P4.2e/f)

#### Added
- 新增 `GET /api/llm/providers`:可用 provider 列表(名称/模型/配置状态,设置页下拉用)
- 新增 `GET /api/llm/settings`:获取当前激活 provider
- 新增 `POST /api/llm/settings`(body `{active_provider}`):切换激活 provider;未知 provider 返回 400 `INVALID_PROVIDER`

#### Changed
- `POST /api/llm/test`:从 Key 格式校验(假延迟 100ms)升级为**真实 API 调用**(`chat("你是连接测试助手", "回复 OK")`,重试 1 次);失败返回具体错误信息(401 等)

### 2026-08-01 | v0.1.4 | 多 Provider 落地(P4.2b/c/d)

#### Added
- MiniMax(abab6.5s-chat)与豆包(doubao-pro-32k)接入 ProviderFactory;`GET /api/llm/keys` 状态列表现返回 3 个 provider(deepseek / minimax / doubao);设置任意 provider 的 Key 并切换激活后,诊断评语由对应模型生成
- `trade_scores.ai_provider / ai_model` 现在写入**实际激活**的 provider(此前硬编码 deepseek)

#### Changed
- DeepSeek / MiniMax / 豆包统一继承 `OpenAICompatClient` 共享实现(消息体与响应解析完全 OpenAI 兼容,仅 URL/模型名/错误前缀不同)

### 2026-08-01 | v0.1.3 | 诊断服务上线(P4.4)

#### Added
- 新增 `POST /api/diagnose/{trade_id}`:触发诊断(立即返回 `pending`,评分 + AI 评语后台异步执行,经 SSE 推送)
- 新增 `GET /api/diagnose/{trade_id}`:查询诊断状态与结果(`pending` / `success` / `no_key` / `failed`,含 `score` / `breakdown` / `ai_comment`)
- `POST /api/transactions`:录入成功后自动异步触发诊断(后台任务,不阻塞响应)
- 新增 SSE 事件 `trade.scored`(评分完成)与 `trade.failed`(缺 Key 或 LLM 调用失败,`reason` 说明);`trade.commented`(评语完成)事件已预留(v0.1.0 已注册,本轮实际推送)

#### Changed
- `trade_scores` 表读写修正:主键为自增 `id`,`trade_id` 为唯一键;此前所有仓储查询误用 `id` 当 `trade_id` 查(评分永远查不到)

### 2026-08-01 | v0.1.2 | 计算器接受多种代码格式(P3.6 联调)

#### Changed
- `POST /api/calculator`:`stock_code` 从纯 6 位数字(min_length/max_length/pattern 强约束)放宽为接受 `600519` / `600519.SH` / `sh600519`,由 schema validator 统一规范化为带后缀格式后查持仓(修复:之前用纯 6 位查询永远匹配不到持仓,`before.shares` 恒为 0)

#### Fixed
- 修复 stock_code 与持仓代码格式不一致导致计算器无法读取当前持仓的问题

### 2026-08-01 | v0.1.1 | 行情接入 + stock_code 规范化为带后缀

#### Added
- 新增 `GET /api/quotes/{code}` + `GET /api/quotes?codes=...`(实时行情,新浪主+腾讯备+5min 缓存)

#### Changed
- `POST /api/transactions` / `POST /api/watchlist`:`stock_code` 从纯 6 位数字放宽为接受 `600519` / `600519.SH` / `sh600519`,入库统一为带后缀格式(600519.SH)
- `GET /api/positions`:新增 `current_price` / `prev_close` / `today_pnl` / `floating_pnl`;行情失败时这些字段为 `null`(不再 503)
- `GET /api/transactions`:`stock_code` 筛选参数同样接受两种格式

#### Deprecated
- `today_pnl_pct` / `floating_pnl_pct` 字段(v0.1.0 文档提及但从未实现,已从契约移除)

### 2026-08-01 | v0.1.0 | MVP 初始版

#### Added
- 16 个端点全部新增(详见 `api-contract.md`)
- v2.1:加 `GET /api/llm/keys` + `PUT /api/llm/keys` + `POST /api/llm/test`
- v2.0:加截图识别 5 个端点
- v1.7:加 SSE `GET /api/events/sse`
- v1.5:加 `POST /api/diagnose/{trade_id}/regenerate`

#### 设计原则(贯穿 MVP)
- 所有金额字段用 **字符串** 传输(精度保护)
- snake_case → camelCase 在 axios 拦截器自动转换
- 错误格式统一:`{ code, message, detail }`
- 5 类鉴权缺失(MVP 单机)

#### 已知限制
- 无鉴权(MVP 单机自用)
- 无分页元数据标准化(`{ items, total }` 是临时方案)
- 错误码未来可能细分(目前 16 类够用)