# 运维手册(Runbook)

> 单机项目的运维命令清单。遇到问题先翻这里。

## 1. 启动 / 停止

### 启动后端
```bash
cd D:\zga-study\rich\backend
uv run uvicorn app.main:app --reload --port 8000
```
**期望**:`Uvicorn running on http://127.0.0.1:8000`
**健康检查**:浏览器打开 http://localhost:8000/api/health 应返回 `{"status":"ok"}`

### 启动前端
```bash
cd D:\zga-study\rich\frontend
npm run dev
```
**期望**:`- Local: http://localhost:5173`
**注意**:必须先启后端,前端 `axios` 才会连上

### 停止
任一终端 `Ctrl + C`

## 2. 数据库迁移

### 升级数据库结构
```bash
cd backend
uv run alembic upgrade head
```

### 降级
```bash
uv run alembic downgrade -1
```

### 重新初始化(危险,会丢数据)
```bash
rm data.db
uv run alembic upgrade head
```

## 3. 备份 / 恢复

### 手动备份
```bash
# Windows PowerShell
Copy-Item data.db -Destination "backups\data-$(Get-Date -Format yyyy-MM-dd).db"
```

### 自动备份路径
`~/rich/backups/` 每周日 02:00 自动备份,保留 12 周

### 恢复
```bash
Copy-Item backups\data-YYYY-MM-DD.db -Destination data.db -Force
# 重启后端
```

## 4. 故障排查

### 端口 8000 被占用

先看清楚"到底是谁占着",不要直接杀:

```powershell
scripts\dev.cmd -Action status   # 会标出 (本项目) / (其它程序!本项目自动顺延到别的端口)
                                  # 并额外列出本项目实际在跑的进程(与端口无关)
```

**2026-10-17 真实事故**:后端日志打印 `Application startup complete`,
健康检查却连续 180 秒超时。原因是另一个项目(Merchant AI)先绑了
`127.0.0.1:8000`,我们的 uvicorn 绑 `0.0.0.0:8000` 依然成功 ——
Windows 允许两者并存,但 `127.0.0.1:8000` 的请求会优先命中"绑定地址更具体"
的那个程序,于是永远 404/超时。

```powershell
# 确认占用者身份(不要盲杀,可能是你其它项目)
netstat -ano | findstr :8000
# 应用身份可用 openapi 标题判断:本项目 title = 买股工具室
(Invoke-WebRequest http://127.0.0.1:8000/openapi.json -UseBasicParsing).Content | ConvertFrom-Json | % { $_.info.title }
```

**默认行为(不用改任何配置)**:`scripts\dev.cmd` 发现后端端口被别的程序占着时,
自动顺延到下一个空闲端口,并同步 `frontend/.env.local` 的
`NEXT_PUBLIC_API_URL`。所以那台机器上 8000 被 Merchant AI 常驻占着也不影响使用。

想固定端口:

```powershell
scripts\dev.cmd -BackendPort 8010
# 想让"端口被别人占着"直接报错而不是顺延:
scripts\dev.cmd -StrictPort
```

**判据说明(重要)**:脚本只杀命令行里出现本项目路径(`backend\` / `frontend\`)
的进程。只认 `uvicorn app.main:app` 这种通用命令是不够的 —— 任何 FastAPI 项目
都是这条命令,Merchant AI 的 8000 曾因此被当成本项目旧进程杀掉。宁可认不出、
不杀,也不要误杀其它项目。

### 进程台账 `logs/dev-state.json`

`start` 会把自己拉起的 PID 记进 `logs/dev-state.json`(连同进程启动时刻,
用来防 PID 回收复用),`stop` / `status` 以它作为归属判断的权威依据。
再加一层"子孙进程"认亲:真正监听端口的往往是子进程
(`next dev` fork 出来的 `start-server` worker、uvicorn 的实际监听进程),
按 `ParentProcessId` 一路收下去。

之所以要有台账:2026-10-17 实测这台机器上 **519 个进程里有 167 个
`CommandLine` 是空的**(`Get-CimInstance` 和 `Get-WmiObject` 表现一致,
同用户也能读到其它字段,不是权限提示),而这些进程用 taskkill 会
`Access is denied`。也就是说"按命令行认进程"在这里本身就不可靠。

### 端口被占但脚本认不出来时

这种情况通常意味着台账丢失(例如手工 kill 过脚本、或用别的工具起过服务)。
脚本会拒绝动手并打印 PID,确认是自己的之后手动处理:

```powershell
scripts\dev.cmd -Action status      # 先看 PID
taskkill /PID <PID> /T /F          # 确认后再执行
```

### 后端启动慢(1~2 分钟)

`data.db` 被撑爆:删除行只把页还给 freelist,文件不会自己缩小,启动时要打开
巨大的库 + 巨大的 WAL。实测 411 MB 的库里 410 MB 是空页。

```powershell
cd backend; python -m app.services.retention --vacuum
# 实测 411.3 MB -> 0.6 MB,启动 80s -> 6s
```

### 日志里全是 `%s` / 中文乱码

- 两套 logger 并存:`app/core/logging.py` 是 loguru(认 `{}`),
  其余 service/api 是标准库 `logging`(认 `%s`)。风格写错不会报错,
  只会留下字面 `%s` —— `backend/tests/test_logging_style.py` 已加守卫。
- 标准库 logger 写 `{}` 会抛
  `TypeError: not all arguments converted during string formatting`,
  在后台调度器里表现为 `Task exception was never retrieved` + 数据不更新。
- 日志编码:启动脚本固定 `PYTHONIOENCODING=utf-8`;否则按 zh-CN 的 GBK 落盘,
  用 UTF-8 读就是乱码。结构化日志在 `logs/rich-<日期>.log`(JSON,含 DEBUG)。

### 后端启动报错
1. 检查 `.env` 是否存在(首次会自动生成 FERNET_KEY)
2. 检查 `data.db` 是否损坏:`uv run sqlite3 data.db "PRAGMA integrity_check;"`
3. 删除 `__pycache__/` 后重启

### 前端启动报错
1. 删除 `node_modules` + `package-lock.json`,重跑 `npm install`
2. 检查 Node 版本:`node --version`(需 22+)

### LLM 调用失败
1. 设置页 → 测试当前 Provider(看 Key 是否有效)
2. 查日志:`~/.rich/logs/rich-{date}.log`
3. 检查 Provider 状态:DeepSeek / MiniMax / 豆包

## 5. 关键路径

| 内容 | 路径 |
|---|---|
| SQLite 数据库 | `~/rich/backend/data.db` |
| 后端代码 | `~/rich/backend/app/` |
| 前端代码 | `~/rich/frontend/src/` |
| 截图原图 | `~/rich/uploads/` |
| 备份 | `~/rich/backups/` |
| 日志 | `~/rich/logs/` |
| 缓存 | `~/rich/backend/cache/` |
| 环境变量 | `~/rich/backend/.env`(不提交)|
| FERNET_KEY | `~/rich/backend/.env`(`FERNET_KEY=...`)|

## 6. 应急命令

### 完全重置(保留 .env)
```bash
rm data.db
rm -rf __pycache__/ .pytest_cache/
uv run alembic upgrade head
```

### 完全重置(连 .env)
警告:会丢失 FERNET_KEY 和所有 API Key
```bash
rm data.db .env
rm -rf __pycache__/ .pytest_cache/ backups/ logs/ uploads/
uv run alembic upgrade head   # 会重新生成 FERNET_KEY
```

### 紧急停掉所有进程
```powershell
Get-Process python,uvicorn,node -ErrorAction SilentlyContinue | Stop-Process -Force
```

### 6.1 Git push SSL 失败(ADR-0004)

**症状**:`git push origin main` 报:
```
fatal: unable to access '...': schannel: failed to receive handshake, SSL/TLS connection failed
```
但 `curl https://github.com` 返回 200(网络可达)。

**根因**:Windows `git` 默认用 schannel(SChannel),被公司网络 / 代理拦截。

**解决**:改用 OpenSSL 作为 git 的 TLS 后端:
```powershell
git config --global http.sslBackend openssl
# 注意:CA bundle 路径必须匹配实际 git 安装位置
git config --global http.sslCAInfo "D:\git\Git\mingw64\ssl\certs\ca-bundle.crt"
```

第二次 push 应立即成功。

**路径验证**(用 `cmd /c "where git"` 找到实际 git.exe 位置):
- `D:\git\Git\` 安装 → `D:\git\Git\mingw64\ssl\certs\ca-bundle.crt`
- `C:\Program Files\Git\` 安装 → `C:\Program Files\Git\mingw64\ssl\certs\ca-bundle.crt`

路径错误时 push 仍会报 schannel 错(迷惑性)。

## 7. iFinD 故障排查（2026-09-22，ADR-0010）

> 覆盖改动 A (screener 事件因子)、改动 B (screener Top N 基本面兜底)、改动 C (ReflectionCard 消息面提示)。

### 现象
后端 log 出现以下之一:
- `IfindUnavailable: search_trending_news 失败`（改动 A）
- `IfindUnavailable: search_securities 失败`（改动 B）
- `IfindUnavailable: search_news 失败` / `search_notice 失败`（改动 C）

### 排查步骤
1. 确认 mcode-tools connector 已安装且 thsifind 可用：
   ```bash
   mcode-tools connector tools --keyword thsifind
   ```
2. 单独测试工具是否响应：
   ```bash
   mcode-tools connector call thsifind__search_trending_news --args '{"time_scope":"24小时","size":5}'
   ```
3. connector 鉴权失败 → 检查 MiniMax Code 工具授权状态（设置页 → 工具授权）。
4. HTTP 429 限流 → 等次日或降低调用频率（不要手动重试，会加重限流）。
5. **改动 A 失败** → screener 自动降级为 4 因子版（log WARNING），当日仍能产出 Top N，只是没有事件因子加权。
6. **改动 B 失败** → screener Top N 不展示（fail-fast），需修复 ifind 后手动 `POST /api/screener/trigger-now` 重跑。
7. **改动 C 失败** → ReflectionCard 22:00 弹窗静默（按设计意图），不影响主体验。

### 缓存清理
改动 A / C 的当日缓存（每交易日 1 次）：
```sql
-- 清除事件因子缓存（改动 A）
DELETE FROM event_factor_cache WHERE trade_date = 'YYYY-MM-DD';

-- 清除消息面缓存（改动 C）
DELETE FROM reflection_context_cache WHERE fetch_date = 'YYYY-MM-DD';
```
改动 B 不缓存（每次跑选股实时调用）。

### 相关模块
- `backend/app/data/ifind_events.py` / `ifind_fundamentals.py` / `ifind_news.py` — 三个包装层
- `backend/app/services/event_factor_service.py` / `reflection_context_service.py` — A/C 服务
- `backend/app/services/screener_service.py` — A/B 接入点
- 完整设计: `docs/superpowers/specs/2026-09-22-ifind-screener-reflection-optimization-design.md`