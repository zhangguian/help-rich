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
git config --global http.sslCAInfo "C:\Program Files\Git\mingw64\ssl\certs\ca-bundle.crt"
```

第二次 push 应立即成功。