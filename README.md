# 买股工具室

> 面向小白股民的**买股看股辅助工具**：打开即用的盯盘工作台，把"这只股票现在什么情况、能不能买、该不该卖"用大白话讲清楚。
>
> ⚠️ 投资有风险，本工具所有输出仅供参考，不构成投资建议。

---

## 快速开始

```bash
# 1. 后端（首次会自动建库、跑迁移）
cd backend
uv sync                                    # 或: python -m venv .venv && pip install -e .
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 2. 前端
cd ../frontend
npm install
npm run dev                                # http://localhost:5173
```

后端健康检查：`http://127.0.0.1:8000/api/admin/health`

## 项目结构

```text
.
├── backend/                 FastAPI 后端
│   ├── app/
│   │   ├── api/             HTTP 路由(24 个 router)
│   │   ├── services/        用例编排(业务逻辑主战场)
│   │   ├── repositories/    持久化查询与写入
│   │   ├── models/          ORM + Pydantic DTO
│   │   ├── core/            基础设施(config/logging/crypto/db_lock...)
│   │   ├── data/            外部数据源适配(iFinD/新浪/腾讯)
│   │   ├── llm/             LLM provider 客户端与工厂
│   │   └── ocr/             截图识别
│   ├── migrations/          Alembic 迁移
│   └── tests/               测试(含架构守卫)
├── frontend/                Next.js 14 App Router
│   └── src/{app,components,lib,stores,hooks}
└── docs/                    文档(ADR / api-contract / roadmap / 分析)
```

### 依赖方向（由测试强制）

```text
api  →  services  →  repositories  →  models
         ↘  core / llm / data / ocr  ↗
```

- `core` **不得**反向依赖业务层
- `repositories` **不得**导入 `api` / `services`
- `services` **不得**导入 `api`
- 违规由 `backend/tests/test_architecture_boundaries.py` 拦截（AST 静态分析）

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `scripts\dev.cmd` | 一键启动前后端（推荐；`-Action stop/restart/status`） |
| `scripts\dev.cmd -BackendPort 8010` | 换后端端口启动（8000 被别的程序占用时） |
| `pytest` | 后端全量测试 |
| `pytest tests/test_architecture_boundaries.py` | 只跑架构守卫 |
| `ruff check app` | 后端静态检查 |
| `ruff format app` | 后端格式化 |
| `python -m app.services.retention --vacuum` | 数据裁剪 + 回收磁盘 |
| `npm run typecheck` | 前端类型检查 |
| `npm run lint` | 前端 lint |
| `npm run gen-types` | 由后端 OpenAPI 生成前端类型 |

## 数据与安全

- 所有数据存本地 SQLite（`backend/data.db`），不上传第三方
- LLM API Key 用 Fernet 加密后存库，不落在 `.env` 明文
- `data.db` / `backups/` / `logs/` / `.env` 均不入库
- `fund_flow` 等高频表在**启动时自动裁剪**（默认每只股票保留最近 500 条）

## 启动排错

### 1. 为什么用 `scripts\dev.cmd` 而不是 `dev.ps1`

本机 PowerShell 执行策略是 `RemoteSigned`，`dev.ps1` 没有数字签名，直接运行会报
`File ...dev.ps1 cannot be loaded. The file is not digitally signed.`。
`dev.cmd` 只是给**这一个进程**加上 `-ExecutionPolicy Bypass`，不改任何系统设置。

### 2. "日志说启动成功，页面却打不开 / 健康检查超时"

先看端口归属：

```powershell
scripts\dev.cmd -Action status
```

如果 `:8000` 显示 `(其它程序!...)`，就是这个坑：**Windows 允许 `0.0.0.0:8000`
和 `127.0.0.1:8000` 同时监听**。别的程序先占了 `127.0.0.1:8000`，我们的 uvicorn
绑 `0.0.0.0:8000` 依然会打印 `Application startup complete`，但所有
`http://127.0.0.1:8000` 的请求都会命中绑定更具体地址的那个程序 —— 于是永远超时或 404。

两条路：关掉那个程序，或者换端口（同时改前端配置）：

```powershell
scripts\dev.cmd -BackendPort 8010
# frontend\.env.local: NEXT_PUBLIC_API_URL=http://127.0.0.1:8010/api
```

脚本现在会先查端口归属：占着的是本项目旧进程才杀，是别人的程序就报错退出，
不会盲杀你其它项目。

### 3. 日志在哪

| 路径 | 内容 |
| --- | --- |
| `logs/backend.err.log` | 后端 stderr（人类可读，启动时的 alembic / 快照 / 调度器都在这里） |
| `logs/frontend.out.log` | 前端 `next dev` 输出 |
| `logs/rich-<日期>.log` | loguru JSON 日志，含 DEBUG，保留 30 天，排查问题时最全 |

后端启动时 `PYTHONIOENCODING=utf-8` 由 `dev.cmd` 固定，否则日志按系统 locale
（zh-CN 为 GBK）落盘，遇到中文就是乱码。

### 4. 启动要 1~2 分钟

一般是 SQLite 库被撑大了（删数据只把页还给 freelist，文件不会自己变小）。
`python -m app.services.retention --vacuum` 会裁剪历史数据并 `VACUUM`，
本项目实测 411 MB → 0.6 MB，启动从 80 秒回到 6 秒。

### 5. 日志里出现 `%s` 而不是具体内容

仓库里两套 logger 并存：`app/core/logging.py` 是 loguru（认 `{}`），
其余 service/api 是标准库 `logging`（认 `%s`）。写错风格不会报错，
只会在日志里留下字面的 `%s`，等于没有日志。
`backend/tests/test_logging_style.py` 会拦住这类混用。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/client-overview.md](docs/client-overview.md) | 功能与交互总览（面向非技术读者） |
| [docs/api-contract/api-contract.md](docs/api-contract/api-contract.md) | API 契约 |
| [docs/dev-log/](docs/dev-log/) | ADR 架构决策记录、runbook |
| [docs/analysis/panwatch-benchmark.md](docs/analysis/panwatch-benchmark.md) | PanWatch 对标分析与优化方案 |
| [docs/roadmap.md](docs/roadmap.md) | 功能路线图 |

## License

见 [LICENSE](LICENSE)。
