# PanWatch 对标分析 · 买股工具室(rich)优化方案

> 分析日期:2026-10-17
> 对标对象:`PanWatch-main`(FastAPI + Vite/React,pwd 约 442 个 .py / 155 个测试文件)
> 本项目:后端 FastAPI 0.115 + SQLAlchemy 2 async,前端 Next.js 14 App Router

---

## 一、总体判断

两个项目**业务域高度重叠**(A股盯盘 / K 线 / 选股 / AI 解读 / 持仓),但工程成熟度差距明显。

| 维度 | 本项目(rich) | PanWatch |
| --- | --- | --- |
| 后端规模 | ~13.6k LOC / 96 文件 | ~442 个 .py(约 3-4 倍) |
| 测试 | 683 个测试函数 / 51 文件 | 155 个测试文件 |
| 架构 | 分层(api/service/repo/core) | 模块化单体(platform / modules / bootstrap) |
| 边界守卫 | ❌ 无 | ✅ `tests/test_architecture_boundaries.py`(AST 静态校验) |
| 前端质量门禁 | ❌ 无 | ✅ `scripts/check-*.mjs` 接入 build |
| CI | ❌ 无 `.github` | ✅ 6 条 workflow(docker / i18n / js-runtime / pr-policy / timezones / release) |
| 命令入口 | `scripts/dev.ps1` 单脚本 | `Makefile`(setup/dev/test/eval/doctor) |
| 可复用库 | 无 | `packages/`(agent-runtime / marketdata / token-meter) |
| 多语言 | 仅中文 | 中英双语 + i18n CI 校验 |
| 文档 | 较完整(ADR 0001-0010、runbook、api-contract) | 架构文档 + 治理文档(pr-policy / SECURITY) |

**结论**:本项目的**产品设计能力明显强于 PanWatch**(截图 OCR 识别、一键复盘、22:00 消息面反思卡、盘后选股 + 事件因子 + 基本面兜底、确定性指标 + LLM 只做翻译的降级设计),文档纪律也更好(ADR/runbook 齐全)。
**短板集中在工程护栏与数据治理**:边界无约束、数据库无限增长、构建期无门禁、版本信息漂移。

---

## 二、P0 — 阻断级问题(已确认并修复)

### 1. 后端在 HEAD 上无法启动 ⛔ → 已修复

`app/services/kline_service.py:232`、`app/services/score_calibration.py:25` 都执行
`from app.models.orm import KlineCache`,但 `app/models/orm.py` 中**没有该模型**,
而迁移 `migrations/versions/a9b8c7d6e5f4_kline_cache_table.py` 已经建了表。

后果:`import app.main` 直接 ImportError → 后端起不来 → 23 个测试文件 collect 失败。

修复:按迁移 + 既有调用点补回 `KlineCache` 模型(价格列用 `String` 保精度,
与 `ScreenerWatchlistDaily` 一致;唯一性由 `(stock_code, period, trade_date)` 索引保证)。

> **反思**:这类"迁移已建表、ORM 模型丢失"的缺陷,正是 PanWatch 架构守卫测试要防的那一类。

### 2. 全部测试无法 collect(PermissionError) ⛔ → 已修复

`tests/conftest.py` 用 `tempfile.mkdtemp()` 建临时目录。Windows 上 `mkdtemp` 会用
`0o700` 生成**受限 DACL**,沙箱 / 受限令牌 / 部分 CI 非交互进程随后无法在其中创建
`logs` 子目录,`app/core/config.py:42` 的 `Path(log_dir).mkdir()` 直接抛
`PermissionError`,27 个测试文件全部 collect 失败。

修复:改用普通 `makedirs`(继承父目录 ACL),并支持 `RICH_TEST_TMP` 环境变量覆盖,
退出时自动清理(`RICH_KEEP_TEST_TMP=1` 可保留现场)。

### 3. CORS 通配符 + credentials(规范冲突)

`app/main.py:118-124` 同时设置 `allow_origins=["*"]` 与 `allow_credentials=True`。
按 Fetch 规范,带凭证请求的响应头 `Access-Control-Allow-Origin` **不能**为 `*`,
浏览器会直接拒绝。当前是"能跑但不合规",一旦前端加 cookie/token 就会炸。

### 4. 后台任务未被持有

`app/main.py:97-102` 三处 `asyncio.create_task(...)` 返回值未保存。
事件循环只持有弱引用,任务可能被 GC 提前回收(表现为调度器"跑着跑着没了"),
且关停时无法 cancel,DB dispose 与后台写并发会产生 `database is locked`。

### 5. 日志体系割裂

项目用 loguru(`app/core/logging.py`),但 `app/main.py:40` 又
`logger = logging.getLogger(__name__)` 走标准库。
标准库 logger 没有 handler,**所有 `logger.info(...)`(如 alembic 结果)被静默丢弃**。

---

## 三、P1 — 数据治理与性能

### 1. `fund_flow` 表无限增长 🔴

实测 `backend/data.db` **348MB**,其中:

| 行数 | 表名 |
| --- | --- |
| **2,349,100** | `fund_flow` |
| 174 | `index_constituents` |
| 140 | `screener_picks` |
| 其余 | 均 < 50 |

成因:调度器每 60s 拉 3 个市场 × Top50 = 150 条/分钟 ≈ **21.6 万条/天**,**无任何清理策略**。

而前端只读 `list_recent(stock_code, limit=30)`(每只股票最近 30 条),
即**只用到最近 30 分钟的数据,其余 99.9% 是纯负担**。

优化:启动时 + 每日定时裁剪,只保留每只股票最近 N 条(建议 N=500,约 8 小时),
并对 `timestamp` 建索引;裁剪后定期 `VACUUM`。

### 2. SQLite 未开 WAL

`app/db.py` 只调了 `create_async_engine(...)`,没有设置任何 PRAGMA。
aiosqlite 是伪异步,多 session 并发写时靠 `app/core/db_lock.py` 的全局 `asyncio.Lock`
串行化(可用但粗)。开 WAL + `busy_timeout` 后读不阻塞写,可显著降低锁冲突。

### 3. 前端巨型组件

| 文件 | 大小 |
| --- | --- |
| `src/app/(app)/page.tsx` | 43.4KB / 913 行 |
| `src/components/advice/AnalysisPanel.tsx` | 36.9KB |
| `src/components/charts/KLineChart.tsx` | 25.5KB |
| `src/components/watch/WatchList.tsx` | 21.9KB |
| `src/components/market/MarketOverviewPage.tsx` | 19.4KB |

`page.tsx` 一个组件持有 18 个 `useState` + 轮询 + SSE 流 + 3 张图表 + 弹窗,
任何一个改动都要通读全文才能确认没破坏别的区域。

### 4. `snakeToCamel` 深拷贝开销

`src/lib/api.ts:28` 对**每个响应**做递归全量 key 转换,K 线 300 根、热力图全组合
这类大 payload 会产生大量临时对象。属于"每次请求都付一次税"。

---

## 四、P2 — 可维护性护栏(建议照搬 PanWatch)

### 1. 架构边界守卫测试

PanWatch 的 `tests/test_architecture_boundaries.py` 用 `ast` 静态校验依赖方向:

```text
web ──► modules ──► platform
```

本项目可迁移为等价的本地规则(建议**先基线化,再逐步收紧**):

| 规则 | 现状 |
| --- | --- |
| `core/` 不得导入 `services/` / `api/` | 需确认 |
| `repositories/` 不得导入 `api/` / `services/` | 需确认 |
| `services/` 不得导入 `api/` | 需确认 |
| `api/` 直接导入 `repositories/` **必须为零** | ❌ 当前 16 处 |
| `models/` 不得导入业务 service | 需确认 |

`api → repositories` 的 16 处横跨 `transactions / positions / diagnose / llm_keys /
screener / stop_losses / screenshot / calculator / reflection_context`,
应逐个收敛到 service 边界;守卫测试用**基线快照**方式上线,防止继续恶化。

### 2. `services/` 成为无边界垃圾桶

`services/` 6830 LOC / 30 个文件,已经和 `api/`(2490)产生规模倒挂。
`ta_service.py` 单文件 1135 行。PanWatch 的对策是:
**一级目录 = 一个业务能力**(`modules/<domain>/{api,service,repository,schemas}`),
并用架构测试守住。存量不建议大爆炸重构,建议**新增代码一律进 `modules/<domain>/`**,
再按 `screener`(最自洽)→ `positions` → `market` 逐个迁移。

### 3. `core/config.py` 混装业务常量

`app/core/config.py` 前半是基础设施配置(DB / 日志 / Key),后半 50 行全是
`SCREENER_*` 选股评分阈值。基础设施配置与选股业务规则混在一个文件,
是 PanWatch 明令禁止的 `core` 反模式。建议把选股阈值迁到 `services/screener_rules.py`
或未来的 `modules/screener/rules.py`。

### 4. 构建期质量门禁

PanWatch 把 `check-ui-primitives.mjs`(禁原生 `alert/confirm`、`select/dialog` 必须用
共享组件)、`check-timezones.mjs`、`check-i18n-literals.mjs` 直接串进
`"build": "check... && tsc && vite build"`。

本项目可平移:
- `pnpm lint` 已存在但 `eslint` 规则未配置(仅 `next lint` 默认)
- 后端无 ruff / mypy 配置

### 5. 版本号四处漂移

| 位置 | 版本 |
| --- | --- |
| `backend/pyproject.toml` | 0.1.0 |
| `app/main.py` FastAPI | 0.1.0 |
| `app/main.py` 启动日志 | v0.2.0 |
| `docs/client-overview.md` | v0.4.2 |
| `docs/release-notes.md` | v2.7 |

建议单一来源(`app/__init__.py: __version__`),FastAPI 与日志统一读取。

### 6. 文档与 CI 空白

- 根 `README.md` 与 `backend/README.md` **均为 0 字节**
- 无 `.github/workflows`
- `Makefile` 等价物只有 `scripts/dev.ps1`

---

## 五、优先级清单

| # | 项 | 类型 | 风险 | 收益 |
| --- | --- | --- | --- | --- |
| 1 | 补回 `KlineCache` 模型 | P0 | 已修 | 后端可启动 |
| 2 | conftest 临时目录 ACL | P0 | 已修 | 683 个测试可跑 |
| 3 | CORS 通配符 + credentials | P0 | 低 | 合规 / 避免未来炸 |
| 4 | 后台任务持有 + 关停 cancel | P0 | 低 | 调度器不丢、不锁库 |
| 5 | loguru 接管标准库日志 | P0 | 低 | 启动日志不再静默丢失 |
| 6 | `fund_flow` 保留策略 + 索引 | P1 | 低 | 348MB → 几十 MB |
| 7 | SQLite WAL / busy_timeout | P1 | 低 | 并发写不再排队 |
| 8 | 版本号单一来源 | P1 | 低 | 文档与运行时一致 |
| 9 | 架构边界守卫测试(基线版) | P1 | 低 | 防止架构继续腐化 |
| 10 | ruff 配置 + pytest 严格化 | P1 | 低 | 统一风格 |
| 11 | 根 README + Makefile | P1 | 低 | 新人可上手 |
| 12 | GitHub Actions(pytest + tsc + lint) | P1 | 低 | 合并前自动拦截 |
| 13 | 拆分 `page.tsx` 巨型组件 | P2 | 中 | 可维护性 |
| 14 | `api → repositories` 收敛到 service | P2 | 中 | 分层清晰 |
| 15 | `modules/<domain>` 渐进式迁移 | P3 | 高 | 长期架构 |

---

## 六、值得从 PanWatch 直接借鉴的五个做法

1. **架构守卫测试**:用 `ast` 把依赖方向写成会失败的测试,而不是写在文档里靠自觉。
2. **可复用包零框架依赖**:`pan_agent` 不许 import FastAPI/SQLAlchemy,保证可单测。
3. **质量门禁前置到 build**:前端检查脚本串进 `build` 命令,而不是靠人记得跑。
4. **Makefile 统一入口**:`make setup / dev / test / doctor`,新环境零学习成本。
5. **专有 Agent 评测集**(`tests/eval`):LLM 输出质量也有回归测试,不只测代码。

---

## 七、不建议照搬的部分

| PanWatch 做法 | 原因 |
| --- | --- |
| 迁 Vite + React Router(弃 Next.js) | 本项目已用 Next.js App Router,无 SSR 收益需求,换栈成本高 |
| 引入 `packages/` 多包 + pnpm workspace | 13.6k LOC 后端拆 4 个包,收益低于成本 |
| 中英双语 i18n | 面向国内小白用户,纯负担 |
| 6 条 GitHub workflow | 本地单机工具,2 条(test + lint)足矣 |
