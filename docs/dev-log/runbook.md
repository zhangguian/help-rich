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
```powershell
netstat -ano | findstr :8000
# 找到 PID 后:
Stop-Process -Id <PID> -Force
```

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

## 7. iFinD 故障排查（2026-09-22，ADR-0008）

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