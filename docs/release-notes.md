# Release Notes v2.7(2026-09-22)

## 🎯 v2.7 新增:iFinD 驱动现有模块优化（事件因子 / 基本面兜底 / 消息面提示）

> 三项改动全部基于 iFinD（thsifind）数据接口,**接现有模块不开新功能**。screener 总分上限从 155 升至 170；ReflectionCard 22:00 弹窗增加消息面上下文。失败语义统一：**A/C 静默不阻断，B 失败不展示 Top N**。详见 [ADR-0008](./dev-log/ADR-0008-ifind-screener-reflection-optimization.md)。

### 新增功能

- **改动 A：screener 加事件因子加权** — 第 5 因子 `event_score`（0/8/15 三档）。通过 iFinD `search_trending_news` 拉取 24 小时热门事件驱动资讯，归一出 `{event_keywords, stock_codes}`，候选股命中关键词 → 加分。失败时自动降级为 4 因子版（log WARNING），当日仍出 Top N。
- **改动 B：screener Top N 基本面兜底过滤** — 排序出 Top 20 后，对每只票调 iFinD `search_securities` 做单股基本面硬门槛（PE / 营收 / 行业地位等），过滤失败 → 不展示 Top N（fail-fast）。前端每张卡片显示基本面过滤状态 badge（passed / kicked）。
- **改动 C：ReflectionCard 22:00 加消息面提示行** — 盘后弹窗顶部追加"📰 今日 X 条公告 / Y 条新闻" + "「最新头条标题」"摘要 + 跳转"→ 查看完整复盘上下文"链接。通过 iFinD `search_news` + `search_notice` 拉取，**当日 1 次缓存**，失败静默不打扰。

### 改动

- **screener 总分上限** 155 → **170**（增加 `event_score` 满分 15）
- **screener_runs 失败语义**：A 失败降级 4 因子版，C 改动静默，B 失败不展示 Top N
- **ScreenerPick 新增列** `fundamental_filter_status`（'passed' / 'kicked' / NULL）
- **ReflectionCard 失败静默** — 不打扰 22:00 体验（设计意图）

### 新增 API 端点（1 个）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/reflection-context?date=YYYY-MM-DD` | 当日消息面摘要（公告数 / 新闻数 / 头条标题），带当日缓存 |

### 数据模型

- **新表 `event_factor_cache`**（trade_date PK）— 当日 1 次缓存热门事件驱动资讯归一结果
- **新表 `reflection_context_cache`**（fetch_date PK）— 当日 1 次缓存消息面摘要
- **screener_picks 新增列** `fundamental_filter_status`（'passed' / 'kicked' / NULL）
- **3 个 Alembic 迁移**：`event_factor_cache` / `screener_picks扩列` / `reflection_context_cache`

### 新增文件

- 后端 8 个：`ifind_events.py` / `ifind_fundamentals.py` / `ifind_news.py` + `event_factor_service.py` / `event_factor_cache_repo.py` / `reflection_context_service.py` / `reflection_context_cache_repo.py` / `api/reflection_context.py`
- 前端 1 个：`lib/api/reflection-context.ts`
- 测试 8 个：`test_ifind_scripts.py` / `test_ifind_fundamentals.py` / `test_ifind_news.py` / `test_event_factor_service.py` / `test_reflection_context_cache_repo.py` / `test_reflection_context_service.py` / `test_reflection_context_api.py` / `test_screener_pick_fundamental_status.py` + conftest mock_thsifind fixture

### 决策记录

参见 [ADR-0008](./dev-log/ADR-0008-ifind-screener-reflection-optimization.md) + spec [`docs/superpowers/specs/2026-09-22-ifind-screener-reflection-optimization-design.md`](./superpowers/specs/2026-09-22-ifind-screener-reflection-optimization-design.md)。

### 后续路线

- ADR-0009：复盘接 ifind（spec §1.2 的反向方案，之前 brainstorming 已被用户暂时搁置）
- screener 加更多因子（行业地位 + 北向资金）
- ReflectionCard 加可点击跳转个股完整复盘

---

# Release Notes v2.6.1(2026-08-09)

## 🎯 v2.6.1 新增:观察池(Watchlist)— 标选 + 周/月胜率

> 经济学家注:发现 → 标记 → 跟踪 → 验证胜率 → 优化策略。补足选股闭环的后三个环节。

### 核心功能

- **从选股页标记 Top 20 候选** — 每张卡片右上 ⭐ 按钮,点击即加入观察池(乐观更新 UI)
- **逐日 K 线记录** — 标记后首次访问观察池时拉 KlineCache 60 日,逐日 upsert `pct_from_marked`(相对标记日的累计涨跌幅)
- **按周/月分桶胜率表** — ISO 周 + 自然月 两种粒度;每桶展示:股数 / 平均涨跌幅 / hit 数 / miss 数 / 胜率
- **主页新 tab「⭐ 观察池」** — 与「📈 选股」并列;点击进入周/月胜率表
- **🔄 刷新每日走势按钮** — 手动触发 refresh=true,后台重新拉 K 线入库

### 数据流

```
选股页 Top 卡片点 ⭐
  → POST /api/screener/watchlist (幂等)
  → 后端拿标记日 close + change_pct → 落 screener_watchlist (UNIQUE stock_code)
  → 后台异步 upsert screener_watchlist_daily (拉 60 日 K 线,过滤 marked_at 之后,算 pct_from_marked)

观察池页
  → GET /api/screener/watchlist
  → 拉所有 active 标选股 + daily records
  → 按 (label, watchlist_id) 分桶:
     - 周:ISO 周(YYYY-Www,周一~周日)
     - 月:自然月(YYYY-MM)
  → 每桶聚合:股数 / 平均涨跌 / hit 数 / miss 数 / 胜率
```

### 新增 API 端点(3 个)

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/screener/watchlist` | 加入观察池(幂等:已存在返 already_existed) |
| DELETE | `/api/screener/watchlist/{stock_code}` | 取消标记(物理删除 daily records) |
| GET | `/api/screener/watchlist?refresh=true` | 观察池周/月胜率表(可选刷新每日走势) |

`GET /api/screener/latest` picks 现带 `is_watched` 字段,前端 ⭐ 按钮据此亮/灭。

### 数据模型

- `screener_watchlist` — 标选主表(UNIQUE stock_code)
- `screener_watchlist_daily` — 标选后逐日 K 线记录(UNIQUE watchlist_id + trade_date)

### 决策记录

参见 [ADR-0007](./dev-log/ADR-0007-screener-watchlist.md)。

### 后续路线

- v2.7:N 天后胜率(复用 P1 view winrate 模式)
- v2.7:定时任务每天 16:00 自动 refresh
- v2.8:行业分组胜率

---

# Release Notes v2.6(2026-08-09)

## 🎯 v2.6 新增:盘后选股(screener)模块

> 经济学家注:小白散户的最大痛点之一是"该买哪只"。本项目已有"看一只"的深度,但缺"看一片"的工具。新模块填补这一空缺。

### 核心功能

- **每日 15:30 后台自动跑批**:扫描沪深 300 + 中证 500(约 800 只),按资金驱动评分取 Top 20
- **资金驱动评分 v1.0**(满分 155):
  - 主力净流入代理(板块口径) 0~60
  - 量比三档 0~40
  - 涨幅 + 连涨 0~30
  - 板块资金榜排名 0~25
- **过滤门槛**:成交额 ≥ 1 亿、近 5 日跌幅不超 -15%、综合分 ≥ 30
- **触发规则 chip**:每只候选股展示"主力净流入≥1.0亿""量比≥2.0"等具体命中条件
- **LLM 评选**(用户主动按钮):从 Top 20 选 5 只"明日重点关注",每只 2 句话亮点 + 1 句话风险 + action 标签(可关注/轻仓/观望)
- **幂等保护**:同一 run_id 重复 LLM 请求直接返缓存,不重复烧 API

### 数据流

```
每日 15:30 (工作日)
  ↓ APScheduler
  screener_service.run_daily_pick(target_date)
  ├─ 拉候选池(沪深300 + 中证500 去重)
  ├─ 并发拉行情(32 协程) + K线(16 协程)
  ├─ 拉板块资金榜(行业 Top 20)
  ├─ 计算 StockFeatures + score_stock() 纯函数评分
  ├─ 排序 → Top 20 落 screener_runs + screener_picks
  ↓
GET /api/screener/latest → 列表展示
  ↓ 用户点按钮
POST /api/screener/latest/llm-pick → 调 LLM → 落 screener_llm_picks
```

### 新增 API 端点(5 个)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/screener/latest` | 最新一批 Top 20 |
| GET | `/api/screener/runs?days=10` | 历史 N 天批次 |
| GET | `/api/screener/pool` | 看候选池大小 |
| POST | `/api/screener/latest/llm-pick?force=true` | 用户主动触发 LLM 评选(幂等) |
| POST | `/api/screener/trigger-now` | 手动立刻重跑(需 `SCREENER_ALLOW_TRIGGER=1`) |

### 新增文件

- 后端 8 个(模型 + 迁移 + repo + service + scoring + LLM 集成 + API + 初始化脚本)
- 前端 2 个(`lib/screener.ts` + `app/screener/page.tsx`)
- 测试 39 个(`test_scoring.py` 22 + `test_screener.py` 17)

### 数据初始化

```bash
# 初始化沪深 300 + 中证 500 成分股(首次部署)
python -m scripts.init_index_constituents                # 在线 + 增量
python -m scripts.init_index_constituents --seed-only     # 仅种子(offline 兜底)
```

### 决策记录

参见 [ADR-0006](./dev-log/ADR-0006-screener-stock-picker.md)。

### 后续路线

- v2.7:个股资金流数据源探活 + 替换板块代理
- v2.8:回测接口 `GET /api/screener/backtest?days=90`
- v0.3:用户自定义选股条件编辑器(产品决策 D11 推迟)

---

# Release Notes v0.4.2(2026-08-02)

## 🎯 v0.4 产品转型:从"记账工具"到"买股看股工具"

> 用户拍板修正产品定位:核心是**帮小白股民看自选/持仓涨跌、分析 K 线、看多看空、放量缩量、通道、企稳点、给出操作建议**;记账向功能降级保留。

- 首页重写为 **三区盯盘工作台**:左盯盘列表(自选+持仓)→ 中 K 线(日/周/月/60分)→ 右上操作提示 + 右下 AI 对话,点击即三区联动
- **UI 全面升级 Liquid Glass**:纯黑 void 单主题、玻璃面板(blur 40px + inset 顶光)、emerald 霓虹交互强调、Plus Jakarta Sans + JetBrains Mono 自托管字体、全站动效铁律(切换必有动效)
- **AI 只翻译不计算**:MA/量比/通道/支撑压力/企稳 全部确定性算法(`ta_service`);LLM 仅做白话解读,失败自动降级纯指标,页面永不空白
- **AI 分析**:看多/看空/中性大徽章 + 5 指标卡 + 支撑压力价位 + 企稳理由 + 风险提示,一键重新分析
- **AI 对话**:单轮问答助手,自动结合你的持仓成本回答("我 60 块的成本,现在该止损吗?")
- **顶 tab 收编**:板块资金(含 🔔 异动 SSE toast 订阅)与 7×24 快讯收进工作台中间区
- **设置页「🕰 历史工具」分区**:年账单 / 风险报告 / 调仓 / Provider 占比 / 计算器 / 流水 / 持仓健康 / 板块资金独立页 8 个记账向页面统一收编,代码数据保留
- **测试 294 → 325 全绿**(+31:指标层 17 + AI 解读 14);端到端实测 analysis 返回真实 LLM 解读(bullish)、chat 真实回答、quotes/positions/watchlist 全通

---

# Release Notes v0.3.0(2026-08-02)(历史版本)

> 买股工具室 v0.2 二期完成版 — **v0.2-roadmap 排班 8 个 Day 全部完成**

## 🎯 概览

相对 v0.2.0 的累计变更(MVP → v0.3.0):
- 后端 32 → **46 个 API 端点**
- 前端 4 → **10 个页面 + 持仓管理 client 化 + 一键清仓 Modal + SSE 订阅 toast**
- 测试 208 → **294 tests 全绿**(+86)
- 持仓架构从"流水聚合视图" → **持仓主数据表**(关键设计哲学翻转)
- 产品名:盘后诊股室 → **买股工具室**
- 新增 2 个真实数据源(新浪 K 线 / 新浪板块资金排行 + 7×24 快讯)
- 0 mock 残留(测试基础设施 mock ≠ 生产 mock)

## 🆕 v0.3.0 主要功能(按 roadmap Day 排序)

### Day 1 — P9 vision LLM 接入(2h)
- **MiniMax `abab-v-chat` 多模态**:OCR 失败时 fallback 到视觉识别(base64 data URL → JSON 输出)
- `BaseLLM.chat_with_image()` / `supports_vision` 抽象;非视觉 Provider 抛 NotImplementedError
- `screenshot_service` 自动选择:OCR → vision → paste-JSON 三级降级

### Day 2 — P6.2~6.4 年账单前端(4h)
- `/annual-report/[year]` 页:4 宫格(已实现盈亏 / 盈利 / 亏损 / 胜率)+ Top5 最赚 + Top5 最亏
- 首页 / 反思卡 / 计算器 / 风险报告 多处入口
- `no_transactions` 提示(v0.4.0):无流水时引导"导入持仓或录入流水"

### Day 3 — A1 持仓 K 线图(4h)
- `lightweight-charts@4`(~200KB)替代自研 SVG
- `PositionDetailModal` 集成:K 线 + 资金流 SSE
- 持仓详情弹窗内可看日 K / 实时资金流推送

### Day 4 — P-stop-loss-v2 一键清仓 API(2h) — 新增 Day 7
- `POST /api/positions/{code}/clear` body `{price, note?}`:自动 sell 流水覆盖全部股数 → recalc_position 联动删除持仓行
- 前端 [🛑 一键清仓] 按钮 + 确认 Modal(实时盈亏预估)
- **修复 recalc bug**:`aggregate_positions` 严格校验+过滤导致 sell 后负股数失算;加双开关 `(strict, keep_zero)`

### Day 5 — A2 资金流订阅(3h) — 半成补完
- 单只资金流被公司网络 blocked(东财 RST / 网易 502 / 腾讯 param error / 同花顺限流),所有免费源不可用
- **板块异动订阅补完**:`sector_fund_flow_service._detect_alerts` 纯函数(净额绝对变化 ≥ 1 亿 / 领涨股切换 / 新进榜 三规则)
- `start_sector_scheduler` 后台 60s 拉 fenlei=0 → publish `sector_fund_flow_alert`
- `GET /api/sector-fund-flow/events?fenlei=` SSE 端点(按 fenlei 过滤)
- 前端 `/sector-fund-flow` 页加 [🔔 订阅异动] 开关 + 异动列表 + toast

### Day 6 — C1 风险敞口(3h)
- `risk_service.calc_risk()`:单股集中度 + HHI 指数 + 板块分散 + 风险评分 0~100
- `GET /api/risk-report` 端点 + `/risk-report` 页:4 宫格 + 警告区 + 单股集中度条形图 + 板块分布
- v0.4.0 后端到端验证:3 只持仓(茅台 100@1500 + 平安 1000@12 + 宁德 200@200) → total=3, market=20.2 万, top=74.26%, HHI=5942, level=高, 2 条警告

### Day 7 — P-privacy Alembic + A4 调仓(已完成)

**P-privacy Alembic 切换**:
- `uv add alembic==1.13.3` + `migrations/` 初始化 + `env.py` 读 DATABASE_URL env var
- 4 个迁移:initial + fund_flow + kline + positions
- `lifespan` 改 `subprocess.run -m alembic upgrade head`(同步,绕开 Windows asyncio 子进程限制)
- 测试环境自动建表
- v0.4.0 修复 kline head multiple heads 问题

**A4 智能调仓建议**:
- 4 规则启发式:`reduce`(单股 >30% 占 15%) / `add`(持仓 <3 只) / `diversify`(同板块 ≥3) / `alert`(top1 >50%)
- `GET /api/rebalance-suggestion` + `/rebalance` 页

### Day 8 — A3 多 Provider 占比月度(1h)
- `GET /api/provider-stats/monthly?year=2026`:12 个月 Provider / status 分布
- `GET /api/provider-stats/summary?year=2026`:年度汇总(柱状图友好)
- `/provider-stats` 页:年度柱状图 + 月度明细表格 + Provider 颜色映射

### 持仓主数据化(横跨 v0.4.0) — 核心重构

**问题**:软件初衷是"管理和复盘持仓",但持仓只是流水聚合视图,截图导入持仓被拒 → 真实持仓无法进入系统。

**设计哲学翻转**(v0.4.0):
- `positions` 表 = **主数据**(手动录入 / 截图导入 / 流水同步)
- `transactions` 流水 = **事件记录**(复盘用)
- 持仓 = **导入基准(delta) + 全部流水聚合**
- delta 运行时推导,**不落库**(capture_delta 变更前 → 变更流水 → recalc_position 变更后传 delta)

**关键修正**:`recalc_position` 原实现有数学死结(delta + flow 恒等式 + 流水入库后不可推导),**两段式 capture_delta + recalc_position** 是正确解。

**新增/变更端点**:
- `POST /api/positions` 手动录入/覆盖单只持仓(每股成本价口径)
- `DELETE /api/positions/{code}` 删除持仓(**联动删除该股全部流水**,防 recalc 复活)
- `GET /api/holdings-health` 持仓体检(真实持仓 + 实时行情 + calc_risk)
- `POST /api/screenshot/{id}/confirm`(holdings/position 类型)→ 改为导入持仓主数据(原 422 `HOLDINGS_NOT_PERSISTED` 删除)

**前端**:
- 首页持仓区 client 化 `PositionsSection`(添加 / 删除 / CustomEvent `positions-updated` 自动刷新)
- `ScreenshotPreview` 持仓可编辑核心字段(shares/price/cost_price)+ 确认导入
- `/holdings-health` 页

### 产品改名(横跨 v0.4.0)
- **盘后诊股室 → 买股工具室**(副标题 → 个人股票投资辅助工具)
- 18 个文件 + 34 处替换
- PowerShell 写入默认带 BOM,已用 `UTF8Encoding($false)` 修复

### 真实数据源接入(v0.3.2 起)
- **0 mock 残留**(`grep -r "mock" backend/app` 仅 mock 注释)
- 新浪 `quotes.sina.cn` K 线(`CN_MarketDataService.getKLineData`)
- 新浪 `MoneyFlow.ssl_bkzj_bk` 板块资金排行
- 新浪 `MoneyFlow.ssl_bkzj_ssggzj` 单只资金流排行(用于手动触发)
- 新浪 `zhibo.sina.com.cn/api/zhibo/feed` 7×24 快讯(JSONP + 纯 JSON 双格式兼容)
- 数据源不可用 502 `DATA_SOURCE_UNAVAILABLE`(友好提示,无 fallback)

## 🐛 修复的关键 Bug

| # | Bug | 修复 |
|---|---|---|
| 1 | screenshot confirm 静默忽略 holdings/position 类型 | 改为导入持仓主数据(v0.4.0) |
| 2 | 持仓是流水聚合视图,真实持仓无法导入 | 持仓主数据化(v0.4.0 核心重构) |
| 3 | `recalc_position` 恒等式(delta + flow 永不变化) | 两段式 capture_delta + recalc(v0.4.0) |
| 4 | 卖出超额请求无业务校验 | 读持仓表实时校验(v0.4.0) |
| 5 | `_detect_alerts` 测试阈值方向错 | 修测试断言(v0.4.1) |
| 6 | `border-bd-subtle` 错误类名(板块资金页) | 改 `border-border-def`(v0.4.1) |
| 7 | `text-up` 错误用做错误提示色 | 改 `text-down`(v0.4.1) |
| 8 | /risk-report /rebalance 字段名 snake_case 不匹配 camelCase 拦截器 | 改 camelCase + 用 `decimalFormat` 处理数字(v0.4.1) |
| 9 | v0.4.0 commit 漏 add 一批改动文件 | 后续 commit 一次性补全 + 注释说明(v0.4.1) |
| 10 | 风险敞口页面运行时报错 `data.total_market_value.toFixed` undefined | 接口统一 camelCase(v0.4.1) |

## 📊 测试覆盖

**后端 294 tests 全绿**(从 v0.2.0 的 208 增加 86 条):
- v0.3.2 真实数据源 23 条(K 线 + 资金流 + 板块)
- v0.3.3 调仓建议 9 条
- v0.3.4 板块资金 + 快讯 9 条
- v0.4.0 持仓主数据化 17 条(test_positions_v040)
- v0.4.1 板块异动 + 一键清仓 13 条
- 其他 bug 修复 15 条

**端到端验收**:
- 持仓粘贴 JSON → 一键导入 → 3 只入库 → 体检 → 删除联动 全通
- 一键清仓 600519 100@1450 → 清仓 @1500 → realized=5000.00
- 风险报告 3 只 → top=74.26%, HHI=5942, level=高

## 🔒 隐私

- LLM Key Fernet 加密入库,前端从不接收明文
- 评语仅传 6 项脱敏字段(代码/方向/股数分桶/日期/占比/名称),无价格无金额
- 截图原图只存本地 `uploads/`,LLM 只接收 OCR 文本(不传图片)
- 用户可粘贴外网 vision 模型 JSON(豆包/GPT-4V),数据不上传第三方

## 🚀 启动脚本

`scripts/dev.ps1` 一键启动 / 停止开发服务(PowerShell 5.1+ 兼容):

```powershell
powershell -File scripts/dev.ps1                # 默认 start
powershell -File scripts/dev.ps1 -Action start
powershell -File scripts/dev.ps1 -Action stop
powershell -File scripts/dev.ps1 -Action restart
powershell -File scripts/dev.ps1 -Action status
```

## 📋 已知限制

- 单机使用,无鉴权(单机自用)
- 止损离场真实化(已通过一键清仓 API 落地,但 StopLossAlert 仍仅提示,未自动触发清仓)
- 单只资金流推送 blocked(公司网络限流;板块异动推送已补)
- 引导视频 / 截图示例 / 多语言(i18n) 推迟到 v0.4+ 锦上添花期
- DeepSeek 等 LLM Key 过期会导致 failed 降级(用户应切到有效 provider)

## 🔗 API 文档

详见 `docs/api-contract/api-changelog.md`(v0.1.0 ~ v0.4.1 共 14 个版本)