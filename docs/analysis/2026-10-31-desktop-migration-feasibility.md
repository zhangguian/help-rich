# 桌面端迁移可行性评估

> 日期:2026-10-31
> 分支:`docs/desktop-feasibility`
> 结论一句话:**能迁,而且比想象便宜 —— 但「桌面端」带来的核心收益其实已经拿到了 90%。**
> 真正剩下的不是「把网页套个壳」,而是 6 处**路径 / 端口 / 生命周期**的工程债。
>
> **状态**:本轮只产出**这份分析**。按 §8 的 5 条决策试做过一轮实现,已全部回滚,
> 代码未落地;经过见 §9。

---

## 1. 结论

| 问题 | 答案 |
|---|---|
| 技术上能不能做成桌面应用? | **能**。前端零 SSR、零 API route handler,后端零 LLM SDK,全是单机可跑形态 |
| 要不要现在做? | **不要一步跳到 Electron**。先补 5 处工程债(约 2 天),PWA 形态就能拿到大部分收益 |
| Electron 完整版成本? | 前端改动 < 1 天,后端路径改造约 1 天,打包调优约 2 天,合计 **3~5 天** |
| 有没有不可行的部分? | **有一处**:Python 重写前端 ❌ 明确不可行(见 §6) |
| 最大风险 | 不是技术,是**产品决策**:关掉窗口后盘中提醒还该不该响(见 §4.5) |

---

## 2. 现状盘点(决定了可行性的事实)

### 2.1 前端:Next.js 14 App Router,**零服务端渲染**

| 事实 | 证据 | 对桌面端的意义 |
|---|---|---|
| 28 个页面 + 2 个 layout,全部 `'use client'` | `frontend/src/app/**` 全量扫描 | 可以整站静态导出 |
| 零 `next/headers` / `next/server` / `cookies()` / `headers()` | 全仓库 grep 无命中 | **没有需要常驻 Node 的 SSR 逻辑** |
| 零 API route handler(`route.ts`) | `frontend/src/app` 下无 `route.ts` | 前端不自建后端,后端可独立打包 |
| 2 个动态路由 `stock/[code]` / `annual-report/[year]`,均为 client 组件 + `useParams` | 逐文件确认 | 静态导出需补 `generateStaticParams`(小改动) |
| 无 `next/image` / `window.open` / `window.print` / `navigator.clipboard` | 全仓库 grep 无命中 | 无浏览器专属 API 依赖,Electron 兼容性好 |
| 依赖 14 个运行时包,`next@14.2.35` | `frontend/package.json` | 打包体积可控 |

### 2.2 后端:FastAPI + SQLite,**零 LLM SDK**

| 事实 | 证据 | 对桌面端的意义 |
|---|---|---|
| 依赖仅 11 个,无 openai/anthropic/langchain | `backend/pyproject.toml` | 打包不需要带大模型 SDK |
| DeepSeek / 豆包 / MiniMax 均走 httpx 手写 OpenAI 兼容协议 | `backend/app/llm/{deepseek,doubao,base}.py` | 用户自带 Key,桌面端只需存 Key |
| LLM Key 用 Fernet 加密存 SQLite | `backend/app/core/crypto.py`、`models/orm.py` | Key 不落明文,随 DB 一起迁移 |
| 29 个 alembic 迁移 | `backend/migrations/versions/` | 首启必须自动 `upgrade head` |
| alembic 支持 `DATABASE_URL` 环境变量覆盖 | `migrations/env.py:29` | 桌面端可把 DB 指到用户目录,无需改代码 |
| CORS `allow_origins=["*"]` + `allow_credentials=False` | `backend/app/main.py:228-238` | `file://` / 自定义协议 origin 都能通 |

### 2.3 **已经有 80% 的 PWA 资产**

| 资产 | 路径 | 状态 |
|---|---|---|
| manifest(standalone + maskable 图标 + 快捷方式) | `frontend/public/manifest.webmanifest` | ✅ `display: standalone`,含 `shortcuts`(今日选股 / 价格提醒) |
| Service Worker | `frontend/public/sw.js` | ✅ 只缓存静态外壳,**绝不缓存 `/api`**(防「看到昨天的价格」) |
| 全套图标 | `frontend/public/icons/` | ✅ 192 / 512 / maskable-512 / apple-touch-icon |
| 离线兜底页 | `frontend/src/app/offline/page.tsx` | ✅ |

### 2.4 **桌面通知已经做好了(关键发现)**

`backend/app/modules/notify/desktop_toast.py` 已经实现:
- **WinRT Toast**(通知中心卡片)+ **Win32 托盘气泡**兜底
- 零新 pip 依赖(纯 PowerShell 5.1 + WinRT)
- **浏览器关着也能收到** —— 通知从后端进程直发,不经浏览器

> **这意味着「桌面化」最主要的用户诉求(盘中不漏提醒)已经拿到 90%。**
> 这也是本文建议「先别急着上 Electron」的核心依据。

### 2.5 体积基线

| 产物 | 实测 |
|---|---|
| `frontend/node_modules` | 728.7 MB |
| `frontend/.next`(dev) | 574.3 MB |
| `backend/.venv` | 100.6 MB |
| `backend/app`(纯源码) | 4.3 MB |

→ Electron 成品(裁剪后)估 **200~280 MB**:Electron runtime ~120MB + Next standalone ~60MB + PyInstaller 后端 ~40MB。

---

## 3. 方案对比

### 方案 A:PWA + 本地守护进程 ⭐ 推荐先做

**形态**:保留现有 Web 架构,加一个常驻的本地进程(后端 + 可选托盘),用户用 Edge/Chrome「安装此应用」。

| 维度 | 评价 |
|---|---|
| 前端改动 | **0 行** |
| 后端改动 | 路径治理 + 固定端口(见 §4) |
| 打包 | 只需打包后端(PyInstaller ~40MB),前端仍是静态文件 |
| 窗口体验 | 无地址栏,但没有系统级托盘 / 窗口状态记忆 |
| 开机自启 | 靠注册表 Run 键或安装器勾选 |
| 工作量 | **1~2 天** |
| 拿到什么 | 双击即用、开机自启、独立窗口、原生通知(已有) |

### 方案 B:Electron 壳 ⭐ 完整形态

**形态**:Electron 主进程做「进程管家」——起后端子进程、起 Next 服务、开窗口。

| 维度 | 评价 |
|---|---|
| 前端改动 | 静态导出需补 `generateStaticParams`;或**保留 Next standalone server**(推荐,零改动) |
| 关键技巧 | Electron `session.webRequest.onBeforeRequest` 把 `/api/*` 重定向到后端端口 → **相对路径 + SSE 都能通**,不用改任何前端 baseURL 逻辑 |
| 打包 | `electron-builder` + PyInstaller 双打包 |
| 工作量 | **3~5 天**(含打包调优、杀软误报、首次启动迁移) |
| 拿到什么 | 方案 A 全部 + 真托盘 + 原生文件对话框 + 自动更新 + 应用商店分发 |

### 方案 C:Tauri

- 壳体积 ~5~10MB(系统 WebView),但**Python 后端照样要打包**(~40MB)→ 省不了多少
- 额外引入 Rust 工具链
- **不推荐**:投入产出比最差

### 方案 D:Python 桌面重写 ❌

PySide6/Qt 重写前端 —— **明确不可行**:
- 28 个页面、30+ React 组件、`lightweight-charts` 图表体系全部要重画
- 后端已有 1879 个测试保护的业务逻辑,前端重写等于把这些 UI 行为全部重新验证一遍
- 成本 ≫ 收益

---

## 4. 真正的阻塞点(6 处,其中 §4.3 已解决)

### 4.1 🔴 路径全部相对 cwd —— 桌面端必炸

```python
# backend/app/core/config.py
database_url: str = "sqlite+aiosqlite:///./data.db"   # :25
env_file = ".env"                                       # :43
log_dir: str = "./logs"                                 # :40
```

桌面应用装在 `C:\Program Files\`(**只读**),cwd 不是用户可写目录 → DB、`.env`、日志全部写不进去。

**改法**:引入 `settings.data_dir`(默认 `%APPDATA%/rich`),三个路径改为基于它;`.env` 改为在 `data_dir` 下查找。
**改动面**:1 个文件(`core/config.py`)+ 少量调用点。约 **半天**。

### 4.2 🔴 端口是「构建期常量」

```ts
// frontend/src/lib/api.ts:52
baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api',
```

`NEXT_PUBLIC_*` 在 `next build` 时被**内联进产物**。而 dev 脚本会**自动顺延端口**(`scripts/dev.ps1` 的 `Resolve-BackendPort`)→ 桌面端如果沿用动态端口,构建好的前端就指错地址了。

**两个选择**:
- **(推荐)桌面端固定端口**(如 8765)。桌面应用独占性高,冲突概率低;冲突时弹「端口被占用,请先关闭 XX」。
- 动态端口 → 必须让 `lib/api.ts` 在**运行时**读 `window.__API_BASE__`(Electron preload 注入),改动很小但多一条链路。

### 4.3 ✅ 首启自动跑迁移 —— **已解决,不需要改**

> **2026-10-31 复核更正**:这一条原本写成「桌面端必须新增自动迁移」,是**误判**。
> 后端 `app/main.py:124` 的 lifespan 里**早就有** `await _run_alembic_upgrade()`
> (用 `subprocess` 跑 `alembic upgrade head`,cwd 固定为 backend 目录,与 cwd 无关),
> 后面还跟着 `ensure_schema()` 补建被删的表。
> → 桌面端复用同一套启动流程即可,**零改动**。

29 个 alembic 迁移,含行为信号 3 张表 + 盘中信号 2 张表;启动时自动 `upgrade head`,
所以「首次运行新表全缺」这个风险**本来就不存在**。

顺带一条实施注意:`migrations/env.py` 的 URL 优先级是 `DATABASE_URL` 环境变量 > settings,
所以桌面端把库指到用户目录时,两种方式都生效(设环境变量或改 settings 都行)。

### 4.4 🟠 Fernet Key 与数据库必须一起搬家

Fernet key 首次启动生成后**写进 `.env`**(`core/crypto.py` / `core/config.py:17-19`),用于加密 SQLite 里的 LLM Key。

→ 桌面端把 `.env` 和 `data.db` 迁到 `%APPDATA%` 时,**两者必须同目录**;若只搬 DB 不搬 key,**已存的所有 LLM Key 全部解不开**(且报错是 `InvalidToken`,排查方向容易跑偏)。
→ 迁移逻辑要写成「同目录原子搬运」,不能分开处理。

### 4.5 🟠 进程生命周期 = **产品决策**(最需要拍板的一条)

后端 `lifespan` 里 spawn 了 **9** 个后台常驻任务:

| 任务 | 频率 | 关窗口后是否该继续 |
|---|---|---|
| 秒级行情轮询 `quote_poller` | 2s | ? |
| 盘中信号调度 `signal_scheduler` | 60s | **应该继续**(否则到价提醒会漏) |
| 价格提醒扫描 `price_alert_scheduler` | 60s | **应该继续** |
| 行情调度 `start_sina_scheduler` | 60s | ? |
| 板块资金流 `start_sector_scheduler` | 60s | ? |
| 工作流调度 `start_workflow_scheduler` | 60s | ? |
| 盘后选股 `start_screener_scheduler` | — | ? |
| 模拟盘净值 `start_paper_scheduler` | 1800s | ? |
| 市场快照预热 `_warmup_market_snapshot` | 启动时 | 否(一次性) |

**决策点**:
- **A. 关窗口 = 退出**(最简单)→ 盘中提醒依赖窗口开着,体验倒退
- **B. 关窗口 = 缩到托盘** ✅ **已定** → 需要托盘图标 + 「退出」菜单 + 开机自启
- **C. 窗口关了但进程留着**,靠托盘唤醒

> **2026-10-31 决策:选 B。** 关掉窗口后盘中提醒**必须继续响**。
> 这条不定下来,后面的技术方案都是白设计。

### 4.6 🟡 行情仍然依赖外网

数据源是新浪 / 腾讯的 HTTP 接口(ADR-0005 / ADR-0006,刻意不引入 akshare)。→ 桌面端**同样需要联网**,离线时只剩 UI 外壳可用。SW 明确不缓存 `/api`(防止「看到昨天的价格以为是今天的」)—— 这条纪律在桌面端要**继续保留**,不要为了「离线可用」去缓存行情。

---

## 5. 推荐路线(分两步)

### 第一步:路径与端口治理(1~2 天,收益最大)

这一步**不产出桌面应用**,但它是所有方案的前置条件,而且能顺手改善现在的开发体验:

1. `core/config.py` 引入 `data_dir`,DB / `.env` / `logs` / `cache` / `backups` / `uploads` 全部归位(§4.1)
2. ~~后端启动自动 `alembic upgrade head`~~ → **已存在,不需要做**(§4.3)
3. 固定一个「应用端口」**8765**,与 dev 端口(8000/顺延)区分开(§4.2)
4. ~~前端加一个安装引导页~~ → **不做**(2026-10-31 决策:不要多余东西)
5. 打包一个 `richd` 启动器(PyInstaller)+ 注册表开机自启 + 托盘常驻(§4.5 决策 B)

**做完这一步:双击 → 自动起后端 → 托盘常驻 → 窗口关掉提醒继续。** 已经是一个能发给家人用的桌面工具了。

> **2026-10-31 实施状态:本轮尝试了第 1、3 项(后端 `data_dir` 治理 + 前端运行时端口注入),
> 经确认后**已全部回滚** —— 当前分支只有这份分析文档,代码未落地。**
> 详细经过见 §9。

### 第二步:Electron 壳(3~5 天,按需)

只有当「托盘常驻 + 真应用窗口 + 自动更新」变成刚需时才做。技术上第一天就能跑起来,难的是打包体积、杀软误报、首次启动迁移这些**非功能性**问题。

---

## 6. 明确不做的事

| 方案 | 判定 | 理由 |
|---|---|---|
| Python(PySide6/Qt)重写前端 | ❌ | 28 页 + 图表体系全废,成本远超收益 |
| Tauri | ❌(现阶段) | 体积省的有限,却多引入 Rust 工具链 |
| 缓存行情做离线可用 | ❌ | 违反「绝不展示陈旧价格」纪律 |
| 把 `NEXT_PUBLIC_API_URL` 改成运行时读取 | 🟡 暂不做 | 只在必须用动态端口时才引入(2026-10-31 试做过一次,已回滚) |

---

## 7. 验收标准(若实施第一步)

1. 全新 Windows 机器上双击启动 → 30 秒内出可用界面,**无需手动执行任何命令**
2. 数据库、日志、`.env` 全部落在 `%APPDATA%`,`C:\Program Files` 下零写入
3. 首次启动自动完成 29 个迁移,行为信号 / 盘中信号表存在
4. 端口被占用时给出**可操作**的提示(不是静默失败)
5. 关闭窗口后按 §4.5 的决策表现(建议:缩托盘,提醒继续)
6. 已配置的 LLM Key 在升级后仍能解密使用(§4.4 回归)
7. 断网时前端显示「离线」态,**不显示任何陈旧价格**

---

## 8. 已决策(2026-10-31)

| # | 问题 | 决策 |
|---|---|---|
| 1 | 关窗口后盘中提醒还该不该响? | **要响** —— 关窗口 = 缩到托盘,后台继续跑(§4.5 决策 B) |
| 2 | 要不要「安装引导」? | **不要** —— 不加多余东西 |
| 3 | 桌面端固定用哪个端口? | **`8765`**(与 dev 的 8000/自动顺延区分开) |
| 4 | 只做 Windows,还是也要 macOS? | **只做 Windows** —— WinRT 桌面通知已深度绑定 Windows |
| 5 | 第一步的路径治理要不要立刻做? | **要** —— 它对现有 dev 流程同样有价值 |

**决策 3 + 决策 5 的推论**:既然端口由用户钉死为 8765,前端就不能再让后端端口锁死在
**构建期**(`NEXT_PUBLIC_API_URL` 是 `next build` 时内联的常量)→ 必须有一条**运行时**
指定后端地址的通道(URL 参数注入 / localStorage / 注入脚本三选一)。
这是 §4.2 那条阻塞点在决策后的具体形态。

---

## 9. 实施经过(2026-10-31,已回滚)

本轮按决策 5 动了代码,写完并自测通过后,经确认**全部回滚**,当前分支只保留这份文档。
留档以便将来重启时不必重新踩坑。

**做过并已回滚的改动**:
| 文件 | 改了什么 | 为什么回滚 |
|---|---|---|
| `backend/app/core/config.py` | 引入 `data_dir`(默认 `backend/`,桌面模式 `%APPDATA%\rich`),派生 DB/logs/cache/backups/uploads;相对路径的 sqlite URL 与目录按 `data_dir` 重锚定 | 整体回滚 |
| `backend/app/core/crypto.py` | Fernet key 改写到「实际生效的 `.env`」 | 整体回滚 |
| `backend/app/api/admin.py` | 备份目录归位到 `{data_dir}/backups` | 整体回滚 |
| `backend/app/data/cache.py` | 行情缓存归位到 `{data_dir}/cache` | 整体回滚 |
| `backend/app/services/screenshot_service.py` | 上传原图归位到 `{data_dir}/uploads` | 整体回滚 |
| `frontend/src/lib/api.ts` + 新建 `runtimeConfig.ts` | 后端地址改为运行时可注入(URL 参数 `?api=` → localStorage → 构建期常量) | 写到一半,整体回滚 |

**过程中查到的、值得留档的事实**:

1. **§4.3 是误判** —— 自动 `alembic upgrade head` 早就在 `app/main.py:124` 有了,不用做。
2. **开发期 `.env` 实际生效的是 `backend/.env`**(uvicorn 的 cwd 是 `backend/`),
   仓库根的 `.env` **根本没被读**。桌面化时若把「仓库根 .env」当成生效文件,
   就会造成「库在用户目录、key 读的是仓库的」→ 已存的 LLM Key 全部 `InvalidToken`。
3. **`.env` 里已有 `DATABASE_URL=./data.db` / `LOG_DIR=./logs` 这类相对值** ——
   桌面模式把它们原样复制到用户目录后会指错位置,必须重锚定或改写成绝对路径。
4. **仓库根 `cache/quote*.json`(13 个)是被误提交的运行期缓存**,时间戳停在 2026-10-24
   (热路径改成零缓存后就没再更新过)。与桌面化无关,但属于该清的垃圾。
5. **本机沙箱里 Python 子进程不能写工作区外**(`%APPDATA%` 写不了),PowerShell 可以。
   → 将来验证桌面模式时,数据目录要指到工作区内的路径,否则 Python 侧必然 PermissionError。
   (这不是代码缺陷;真机上以用户身份运行没有这层限制。)
