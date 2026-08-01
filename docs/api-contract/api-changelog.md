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