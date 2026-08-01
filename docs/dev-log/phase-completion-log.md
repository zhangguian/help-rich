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

## 关键经验(全项目复盘用)

<!-- 每条经验不超过一行 -->

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