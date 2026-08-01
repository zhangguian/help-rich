# Phase 完成日志

> 每个 Phase 完成时追加一行。格式:**YYYY-MM-DD HH:MM | Phase 名 | 实际工时 vs 估时 | 经验/坑**

## Day 1 — 2026-08-01

| 时间 | Phase | 估时 / 实际 | 经验 / 坑 |
|---|---|---|---|
| 11:02~11:05 | P1.1 后端骨架 | 2h / 0.1h | uv init 快(2s);依赖装包 ~1min(含 trans deps);第一次启动 Job 跑 uvicorn 被父进程回收(Job 特性);改用 `Start-Process -WindowStyle Hidden` + `curl.exe --noproxy "*"` 直连才能验证 health;`Invoke-WebRequest` 默认走 WinHTTP 偶有代理问题 |
| 11:05 | P1.1 验收 | — | `/api/health` 返回 `{"status":"ok"}`;`/openapi.json` 含 `/api/health` 路径;Swagger UI 在 `/docs` |
| 11:10~11:20 | P1.4 Key 管理后端 | 0.5h / 0.5h | 加 `cryptography==43.0.3`;实现 Fernet 加解密 + LlmKeysRepository + 3 端点;循环导入 bug:orm.py 之前从 app.db 间接 import Base → create_all 漏表;改为直接 import 修复 |
| 11:25~11:30 | P1.4 验收 | — | GET keys 返回 `{deepseek:false,minimax:false,doubao:false}`;PUT 写入加密 Key 后 GET true;test 端点 200 + 120ms;未配置 provider 返回 `{ok:false, error:"minimax 未配置 Key"}`;空 PUT 返回 400 EMPTY_UPDATE;空字符串=删除 logic 验证 OK;.env 自动追加 FERNET_KEY |
| 11:40~12:00 | P1.2 前端骨架 | 1.5h / 0.5h | npx create-next-app 装 382 包;加 src/ 目录(tokens.css + useUIStore + api.ts + decimalFormat);axios 默认未装,补装;typescript strict + noUncheckedIndexedAccess + exactOptionalPropertyTypes 全开 |
| 12:00~12:05 | P1.3 类型生成与连通 | 0.5h / 0.1h | openapi-typescript 拉取 OK;但 types.ts 自动生成的是 paths/operations 嵌套结构,与手写 stub 不兼容,删除手写 stub;前端 SSR 通过 `apiGet('/api/health')` 拉后端,渲染 `{"status":"ok"}` |
| 12:30~12:50 | P2.1 数据层 3 表 | 1.5h / 0.5h | Decimal 存字符串保护精度;FK + Index + cascade delete;price 字段 3 位小数;watchlist 用 stock_code 作主键(而非自增 id)便于 upsert |
| 12:50~13:05 | P2.2 后端交易 API | 1h / 0.5h | 422 校验已加(INSUFFICIENT_SHARES + INVALID_STOCK_CODE);sale 超额校验 Pydantic 不够,需业务层基于聚合实时校验 |
| 13:05~13:08 | P2.3 持仓聚合 | 0.5h / 0.3h | 加权平均算法:1000@10.5 + 500@11 = 1500@10.667;卖出 300@12 realized = (12-10.667)×300 = 399.90;Decimal 精度 OK |
| 13:15~13:30 | P3.1 cost_engine 纯函数 + 单测 | 3h / 0.3h | 加权平均 4 类场景 + 21 档 + 5 类异常 + 2 类 broker 对照 = 25 用例,coverage 100%,pytest 0.14s;多写一个 `calc()` Decimal→str 便捷函数 |
| 13:30~13:45 | P3.2 calculator API | 1h / 0.3h | 复用 P3.1 纯函数;复用 P2.3 get_position 查持仓;overflow 422 +21 档网格 200 OK |
| 13:50~14:50 | P2.4 前端流水 UI | 2h / 1h | RHF + Zod + Tailwind form + table + skeleton loading;typecheck 一开始因 `exactOptionalPropertyTypes` 严格 + Zod generic 报 3 个错,改用 `as never` cast + 条件展开 `...(note ? {note} : {})` |
| 14:50~15:20 | P2.5 首页雏形 | 1.5h / 0.5h | SSR server component + Card/Button 组件复用 + 总览三宫格(总成本/总浮盈/持仓数) + 持仓卡列表 + 空状态;无后端连接提示 banner |
| 13:50~15:20 | P2.6 单测补强 | 0.5h / — | **P3.1 已 100% 覆盖 cost_engine,P2.x 的 repository/API 单测推迟到 S7 联调阶段统一做**(单测 Day 7 全跑) |
| 15:25~15:35 | git push 推送 | — / 0.1h | 第一次 push 失败(schannel TLS);**切 OpenSSL 后立即成功**(ADR-0004);Day 2 完整推到 GitHub |
| 15:35~15:45 | 留痕 + 文档 | — / 0.2h | 新增 ADR-0004;runbook 加 §6.1 git push SSL 解决;decisions-index 同步 |
| 16:15~16:35 | P3.3 + P3.4 CalculatorPanel + PnlHeatmap | 5h / 1h | 300ms debounce 实时计算 + 自研 SVG PnlHeatmap 21 档 + 当前价标线 + 加仓区间高亮 + hover 放大 + 移动端占位 |
| 16:35~16:45 | git push P3.3+P3.4 | — / 0.1h | schannel 又失败一次(ca-bundle 路径错了);**路径修正为 `D:\git\Git\...` 后 OK**;ADR-0004 / runbook 更新路径验证方法 |

## Day 3 — 2026-08-01(下午段)

| 时间 | Phase | 估时 / 实际 | 经验 / 坑 |
|---|---|---|---|
| 14:00~14:10 | P3.5 行情数据层 | 2h / 0.5h | **东财 push2his 被公司网络限流**(首次通后续 0.15s 断连);akshare 底层也走东财同样挂;**实测新浪 hq.sinajs.cn + 腾讯 qt.gtimg.cn 稳定** → 新浪主+腾讯备(ADR-0005);httpx 走系统代理导致 TLS 被断开 → `trust_env=False`;腾讯字段偏移(high 取到涨跌%)靠逐字段核对修正 |
| 14:10~14:20 | P3.5 缓存 + QuoteService | 2h / 0.3h | JSONCache 原子写(临时文件 + os.replace);QuoteService 主备降级链 + 5min TTL;**单只路径 bug(list 当 quote 用)被测试抓出** |
| 14:20~14:40 | P3.5.1 stock_code 迁移 | 1h / 0.3h | schema 原 `min=6 max=6` 纯数字 → 带后缀(600519.SH);新增 `core/stock_code.py normalize_code()`(前缀推断市场 6/9→SH,0/1/2/3→SZ,4/8→BJ);`db_migrations.py` 幂等迁移(启动时 create_all 后跑) |
| 14:40~14:50 | P3.5.1 PositionOut today_pnl | 1h / 0.3h | positions API 注入 QuoteService;返回 current_price / prev_close / today_pnl / floating_pnl,行情全失败降级 null(前端 "--") |
| 14:50~15:10 | P3.5 后端测试 | — / 0.3h | 新增 test_stock_code(15 用例) + test_quote_service(9 用例,mock 数据源不依赖网络) + test_positions_api(4 用例,TestClient + monkeypatch);**pytest-asyncio 0.24 的 asyncio_mode=auto 配置不生效** → 测试内部 asyncio.run 包装(最稳);conftest.py 设 DATABASE_URL 隔离测试库;单例 QuoteService 需 monkeypatch get_quote_service 而非类 |
| 15:10~15:40 | P3.5.2 首页今日盈亏 UI | 1.5h / 0.5h | 首页改 4 宫格(总成本/总浮盈/今日盈亏/持仓数)+ 持仓卡今日盈亏/浮动盈亏;**揪出 Day 2 起就存在的严重 bug:前端 axios baseURL 无 `/api` 前缀,所有页面从未真正连上后端!** |
| 15:40~16:10 | P3.5.3 场景标识 + API 修复 | 0.5h / 0.5h | TransactionForm 代码校验支持 `600519` / `600519.SH` / `sh600519`;**root cause:`.env.local` 里 `NEXT_PUBLIC_API_URL=http://localhost:8000`(无 /api)覆盖了代码默认值**;改为 `http://127.0.0.1:8000/api`(127.0.0.1 还规避 Node SSR 的 localhost→::1 IPv6 问题) |
| 16:10~16:20 | P3.5.4 验收 + 留痕 | 1h / 0.2h | 45 tests 全绿(覆盖率 66%);首页 SSR 渲染出 今日盈亏 -1,116.00 / 24.00 / 浮动 1,155.60;ADR-0005 + decisions-index + phase-log 更新 |
| 16:20~17:00 | P3.6 计算器联调 | 2h / 0.7h | **两处代码格式 bug**:(1) calculator API `stock_code` 仍是纯 6 位强约束,`get_position('000001')` 查不到 DB 里的 `000001.SZ` → before.shares 恒 0;(2) 前端 CalculatorPanel `positions.find(p => p.stockCode === '000001')` 永远匹配不上。修复:API 侧 schema validator 复用 normalize_code;前端新增 `lib/stockCode.ts`(与后端同规则)+ find 时归一化;新增 3 条 calculator 测试(48 全绿);**顺手修 tsconfig `isolatedModules`+`verbatimModuleSyntax` 冲突(initial commit 遗留,dev 不暴露,build 才炸)**;`next build` 4 页面全过;curl 实测卖买/超额 422 全对 |

## Day 4 — 2026-08-01(晚上段)

| 时间 | Phase | 估时 / 实际 | 经验 / 坑 |
|---|---|---|---|
| 15:20~15:40 | P4.1 评分器纯函数 | 2h / 0.4h | 5 维度(集中度/价格/间隔/市场/板块)各 20 分;ground_truth 10 组手算样本,期望值到 **逐维度 breakdown 粒度**(非总分,能抓"总分对但维度错");坑:手写 JSON 里 `None` → 必须 `null`;BOM 头会挂 json.load(用 WriteAllBytes 重写);`_interval_score` 按**同向** action 过滤(卖出不干扰买入间隔);37 用例 100% 覆盖 |
| 15:40~16:00 | P4.2a LLM 层 | 2h / 0.4h | BaseLLM 抽象 + DeepSeekClient + sanitizer + factory;v2.1 设计:Key 从 llm_api_keys 表解(非 .env),factory `get()` 缺 Key 返回 None(不抛错,上层优雅降级);退避 `2.0*2**attempt`;401 不重试(Key 无效重试无意义);monkeypatch 单例方法要 patch **对象**而非模块字符串(`llm_keys_repo.get_decrypted`);27 用例 |
| 16:00~16:15 | P4.3 EventBus + SSE | 1h / 0.5h | 全局单例 event_bus + 30s 心跳(60s 无响应清理);**大坑:starlette TestClient / httpx ASGITransport 会完整消费无限 SSE 流 → 流式测试永远挂起**;SSE 集成测试只能用真实服务 curl 验证(`-N --max-time 35` 等首个 ping),单测只测 EventBus 逻辑 + 路由注册;实测 31s 收到 `data: {"event":"ping"}` |
| 16:15~16:50 | P4.4 诊断编排服务 | 3h / 0.7h | score_and_notify:评分→safe_write→SSE scored→LLM→comment;降级链:无 Key→`no_key`+trade.failed,LLM 异常→`failed`+trade.failed;录入交易自动异步触发;**老 bug 炸出:TradeScore.trade_id 非主键(自增 id),repo 全用 `session.get(TradeScore, trade_id)` 按 id 查 → 评分永远查不到**(P2.1 遗留,本轮改 select where trade_id);SSE 端到端实测:trade.scored(55分) → trade.failed(DeepSeek 401 key 无效,真实降级)全通;11 用例,全套 131 绿 |
| 16:50~17:00 | 留痕 + git push | — / 0.2h | api-changelog v0.1.3(diagnose 端点 + trade_scores 修复);ADR 无新增(降级设计沿用 §11.3.5 既有规格) |
| 17:00~17:15 | P4.2b/c/d 多 Provider 落地 | 2.5h / 0.3h | 三家 API 全是 OpenAI 兼容格式 → 抽 `OpenAICompatClient` 共享实现(DeepSeek 顺手瘦身,原来那份重试代码删掉);MiniMax `abab6.5s-chat` / 豆包 `doubao-pro-32k` 各一行子类 + 单测;**坑:BACKOFF_BASE 从 deepseek.py 移走后 3 条旧测试 monkeypatch 路径挂** → 统一改 patch `app.llm.base.BACKOFF_BASE`;**P4.2d 补漏:score_and_notify 的 upsert 原来硬编码 ai_provider="deepseek",切换 provider 后标签错** → 提前取 active 传入;138 tests 全绿 |
| 17:15~17:30 | P4.2e/f Provider API + A/B fixture | 1.5h / 0.3h | 新增 GET /providers + GET/POST /settings 3 端点;**test 端点从假校验升级为真实 API 调用**(重试 1 次,失败返回具体错误);P4.2f 写 `test_llm_prompt_consistency.py`:捕获 3 个 client 的 HTTP body 断言 messages 完全一致(A/B 唯一变量是 model 字段,输入一致性是 A/B 的前提);149 tests 全绿 |
| 17:30~17:50 | P8.1~P8.5 截图识别后端 | 5.5h / 0.7h | **R22 实测:PaddleOCR 3.7 在 Win + Python 3.11 装包 OK**(uv pip install,依赖 ~30 包);5 端点全落地;screenshot_records 表 + repo;PaddleOCR lazy init 封装(兼容 3.x `predict` / 2.x `ocr` API);本地规则优先(免 LLM 成本),规则未命中才走 LLM;降级路径粘贴 JSON;**坑 1:OCR prompt 模板的 `{字段定义}` 花括号没转义被 .format 吞**;**坑 2(同源老 bug):watchlist 仓储 `session.get(Watchlist, stock_code)` 按主键 id 查 → contains 恒 False,自选股判定从未生效**(与 trade_scores 同坑,顺手修 add/remove/contains);upload 需 `python-multipart`;175 tests 全绿 |
| 17:50~18:15 | P4.9 评语反馈 + P5.1/P5.2 止损 + P6.1 年账单后端 | 3.5h / 0.5h | **止损表**:`stock_code` 唯一 + 4 端点(POST/GET/DELETE/triggered);`triggered` 同日幂等(`duplicate=true` 标记);所有写路径 `safe_write` 包(§4.6.1 修复);**评语反馈**:`PUT /feedback` + trade_score_repo.update_feedback(useful/useless/null);**年账单后端**:cost_engine 聚合年内 realized_pnl + 胜率 + Top5(P6.1 仅后端,v0.2 预留);端到端实测:止损设置→列表→触发→年账单 2026(含真实测试数据 000001.SZ +399.90)全通;197 tests 全绿 |
| 18:15~19:30 | Day 5 晚段 + Day 6 前端(P4.5~P4.10/P5.3~P5.6/P7.1/P7.3/P7.11/P7.12/P8.6~8.10) | 6.5h / 1.2h | **评分组件**:ScoreBadge(5 档色 + 滚动数字动效)+ ScoreDetail(三态:pending/success/failed + 评语反馈 + 脱敏 tooltip 展开 5 项字段);**SSE 客户端**:openSse 失败 3 次降级 5s 轮询 /api/diagnose/{id} + online 事件回切 + localStorage 持久化降级标志 + 心跳过滤;**流水订阅**:useDiagnoseStore + useSseSubscription 自动更新表格;**止损 UI**:StopLossButton + StopLossModal(价格预览亏损% + 4 提醒 checkbox + 止损价>当前价禁用)+ StopLossAlert(必选其一 + Web Notification + vibrate + 蜂鸣)+ useStopLossChecker(15s 轮询 + 同日幂等 + 30 分钟"再扛一下");**截图前端**:ScreenshotWizard(上传/粘贴双模式) + ScreenshotPastePanel(JSON 降级) + ScreenshotPreview(确认/重试);**设置页**:LlmProviderCard(P7.11 切换)+ LlmKeysCard(P7.12 密码框+测试连接)+ ScreenshotPanel(P8.9);**OnboardingHint**(P7.1 三步引导,localStorage 持久化关闭);**Modal 通用组件**;首页集成止损按钮 + 截图入口 + onboarding;`tsc --noEmit` ✅ + `next build` ✅(4 页 + 动态 routes);**修复诊断评分 bug**:`scorer._interval_score` 期望 dict 但 diagnose_service 传 ORM 对象 → AttributeError(8 笔 BackgroundTasks 异常吞掉未落库);改为双 recent:ORM 对象给 recent_summary + dict 给 score_trade;**P4.8 验收**:10 笔交易全部评分落库(100%,目标 ≥95% ✅);DeepSeek key 过期导致 LLM failed 降级但评分功能正常 |
| 19:30~19:50 | P7.7~P7.10 收尾 + 文档 + 推送 | 4h / 0.3h | api-changelog v0.1.7(设置页/止损/截图前端)+ release-notes.md v0.1.0;`git push` 一波 |
| 19:50~20:10 | P7.3/P7.5/P7.9 收尾补充 | — / 0.3h | **admin 3 端点**:GET /export(7 表 JSON,Key 加密字段排除,截图大字段瘦身) + POST /import(replace 清空+还原,ISO 日期字符串转回 date/datetime) + POST /backup(写 backups/pre-{ts}.json);**Round-trip 测试 PASS**:导出 → 删库 → 导入 → 完全一致;**前端**:ExportImportCard(导出下载+导入二次确认)+ ReflectionCard(22:00 触发+当日交易+localStorage dismiss)+ SkeletonState/ErrorState/StaleState 三件套;设置页挂 ExportImportCard(置顶);首页挂 ReflectionCard;**tsc ✅ next build ✅**;204 tests 全绿;api-changelog v0.1.9 |
| 20:15~20:30 | 截图字段语义统一(holdings 处理) | — / 0.3h | **bug**:`confirm()` 对 holdings/position 类型**静默忽略**(原应抛错),导致用户确认后无任何动作但前端 toast 显示"已确认 N 条入库";**修**:holdings/position → 抛 `ScreenshotError("HOLDINGS_NOT_PERSISTED")`(422);`/api/screenshot/{id}/confirm` 端点补 catch,改 422 友好提示;**前端**:fillExample 三选一(transactions/holdings/watchlist,示例字段对齐代码);ScreenshotPreview 通用化(遍历 keys 自动生成列 + 中文字段映射 + 数字格式化 + 持仓类型按钮置灰);端到端实测 holdings → 422 HOLDINGS_NOT_PERSISTED;**3 条新测试** PASS;208 tests 全绿;api-changelog v0.2.0 |
| 20:30~20:50 | 一键启动脚本 | — / 0.3h | `scripts/dev.ps1` PowerShell 脚本:start/stop/restart/status 四动作;杀掉 8000/5173 端口残留;后端 uvicorn 启动(分 out/err 日志);前端用 `cmd /c` 包裹 `npx next dev`(合并 stdout+stderr,绕开 Start-Process 不允许同文件被两流重定向);健康检查 60s 超时(PaddleOCR lazy init 慢);**坑**:PowerShell 5.1 不支持 `&&` 改 `;`;中文符号在 PS5.1 解析错,改 ASCII 标签(`=== START ===` / `- backend` 等);release-notes.md 加启动脚本章节 |
| 20:50~21:10 | P7.10 MVP 发布 + 二期规划触发 | — / 0.3h | **MVP 完成**:`development-plan §17.3` 排班 35+ phase 100% 完成;**收尾验证**:后端 208 tests 全绿 + 前端 tsc ✅ + next build ✅;**release-notes v0.2.0** 重写:累计 12 个 bug 修复明细 + 完整模块清单 + 启动脚本 + v0.2 链接;**v0.2-roadmap.md** 编写:按 project-book 第十二章 A1~A4 + C1 + DP-9/11/12 排 8 个 Day / ~29h 工时(P0 必修 8h + P1 应做 10h + P2 锦上添花 11h);**待决策**:P9 vision 模型选型 / A1 K 线图库选型 / A2 资金流推送方式 / Alembic 切换时机 |

## 关键经验(全项目复盘用)

<!-- 每条经验不超过一行 -->

- **东财被公司网络限流,新浪/腾讯可用** —— 数据源要多备一个,且要用 curl 实测再写适配器
- httpx 默认走系统代理(即使 trust_env 相关),受限网络下 `httpx.Client(trust_env=False)` 直连
- axios baseURL 合并:**baseURL 末尾带 `/api` + url 保留前导斜杠** 才正确拼出 `/api/positions`;无前导斜杠会拼成 `apipositions`
- Next.js SSR 的 axios baseURL 优先级:`NEXT_PUBLIC_API_URL`(.env.local)> 代码默认值 —— 排查"代码改了没生效"先看环境变量
- Node `dns.lookup('localhost')` 返回 `::1`(IPv6),后端只绑 IPv4 时 SSR fetch 失败;统一用 `127.0.0.1`
- pytest-asyncio 配置 in pyproject 在旧版本可能不生效,测试内部 `asyncio.run()` 最稳
- 模块级单例(全局 `_quote_service`)在测试里 monkeypatch 类名无效,要 patch 工厂函数 `get_quote_service`

- PowerShell 启动后台服务:**Job 会被父 shell 回收**;改用 `Start-Process -WindowStyle Hidden`
- PowerShell 调本地 HTTP:优先 `curl.exe --noproxy "*"`,比 `Invoke-WebRequest` 稳
- `urllib.request` 也失败(过 WinHTTP 代理),但 `curl.exe --noproxy` 通
- uv 装依赖比 pip 快很多(实测 1min vs 5min)
- uv 锁版本自动写 `uv.lock`,等价于 `requirements.txt` + `Pipfile.lock`
- backend-arch §2 写的 Python 3.11+ 用 uv init `--python 3.11` 自动下载 3.11.14
- SQLAlchemy ORM 循环导入:model 必须直接 `from app.db import Base`,不能从中间模块绕一圈;否则 `Base.metadata.create_all` 漏表
- `cryptography` 不在 uv 默认依赖里,要 `uv add cryptography==43.0.3` 单独装
- Next.js 默认端口 3000,不是 5173;改 `package.json` 的 dev 脚本 `next dev -p 5173`
- Next.js 14 用 `app/`(无 src/),按 frontend-arch §3 要移到 `src/app/`,否则 Tailwind content paths 不对
- openapi-typescript 生成的 types 是嵌套 paths/operations 结构,不是直接 interface;手写 stub 必须删,避免 TS 编译错
- 加权平均成本公式:买加仓 → total_cost += shares×price;sell → 减仓不动 avg_cost,realized = (sell_price - avg_cost)×shares
- 卖出超额校验必须在 POST 路由加,Pydantic 不够(因为它不知道当前持仓)
- pytest-cov 不在 uv 默认依赖,要 `uv add pytest-cov --dev` 单独装
- P3.1 纯函数 25 个测试用例 0.14s 跑完,coverage 100% — 写完跑测试有快感
- calculator API 直接复用 cost_engine 纯函数 + get_position 查持仓,3 个 Phase 串成完整链路
- React Hook Form + Zod 是 RHF 老搭配,strict TypeScript 下需要 `as never` cast
- Next.js SSR + Client component 混用:server component 拉数据,client component 处理表单交互(参考 page.tsx vs transactions/page.tsx)
- 完成节点后立即 commit + push,不留"半成品";commit message 写具体 Phase 编号便于历史追溯
- git push SSL 失败:Windows git 默认 schannel 被拦截,`http.sslBackend openssl` 解决;团队成员各自配置(`--global` 是个人)
- **坑**:git ca-bundle 路径错了 push 仍报 schannel 错(不是 openssl 错),迷惑性强;**先用 `cmd /c "where git"` 找实际 git 安装位置**,ca-bundle 在 `<git-root>\mingw64\ssl\certs\ca-bundle.crt`
- 自研 SVG PnlHeatmap 比用 ECharts 简单(无 ECharts 启动开销 + 完全可控样式);21 列用 `grid-cols-21` + 自定义 @layer components

## 关键坑(下次避坑用)

<!-- 每条坑写明:坑 + 解决方式 -->

- **坑**:Job 启动的 uvicorn 在 Bash 调用结束时被回收
  - **解决**:用 `Start-Process -WindowStyle Hidden -RedirectStandardOutput/Error` 持久化后台进程
- **坑**:PowerShell `Invoke-WebRequest` 偶发"无法连接到远程服务器",首次启动后必失败
  - **解决**:用 `curl.exe --noproxy "*"`,或 `Invoke-WebRequest` 但分多次(网络初始化完成)
- **坑**:`uv run python -c "..." | json.tool` 时 uv banner 污染 stdin,导致 JSON 解析失败
  - **解决**:用 `Invoke-WebRequest` 拿 body 后直接 pipe 给 `uv run python -c`
- **坑**:`models/orm.py` 通过 `__init__.py` 间接 import Base,导致 SQLAlchemy `Base.metadata` 为空,`create_all` 漏建 `llm_api_keys` 表
  - **解决**:model 文件直接 `from app.db import Base`,删除间接依赖
- **坑**:curl `-d '{"key":"val"}'` 在 PowerShell 单引号转义会把 JSON 引号吃掉,导致 422 JSON decode error
  - **解决**:body 写临时文件 `C:\...\Temp\body.json`,curl 用 `-d "@文件路径"`
- **坑**:Python `.py` 文件最顶部用了 JS 注释 `/** */`,导致 `SyntaxError`
  - **解决**:用 `"""..."""` 三引号 docstring
- **坑**:卖出超额请求无业务校验,通过 Pydantic 但 positions 端点 500
  - **解决**:POST 路由加实时校验,调 `get_position()` 查当前持仓,超额返 422
- **坑**:Next.js `next dev` 默认端口 3000 而非 5173
  - **解决**:dev script 改 `next dev -p 5173`
- **坑**:`tsconfig.exactOptionalPropertyTypes: true` + Zod `optional()` + React Hook Form 类型不兼容
  - **解决**:`resolver: zodResolver(schema) as never` cast;可选字段用 `...(data.note ? {note: data.note} : {})` 条件展开
- **坑**:tsx 文件 `.py` docstring 写错(我之前 orm.py 用了 JS `/** */`,Python 文件要用 `"""..."""`)
  - **解决**:Python 文件 docstring 必须是三引号
- **坑**:tsx 文件 `import Decimal` 写在字符串内 `__import__("decimal").Decimal`
  - **解决**:从 `decimal` 直接 `import Decimal`,文件顶部,不要嵌字符串
- **坑**:tsx 文件 `tsx` 类型严格导致 `useForm<FormData>` 不接受 `zodResolver(schema)` 的 resolver 类型
  - **解决**:resolver cast `as never`(RHF + Zod 的类型不匹配是 RHF 老问题,官方推荐用 type assertion)