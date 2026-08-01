# 盘后诊股室 - 一键启动 / 停止 开发服务
#
# Usage:
#   powershell -File scripts/dev.ps1                # default start
#   powershell -File scripts/dev.ps1 -Action start
#   powershell -File scripts/dev.ps1 -Action stop
#   powershell -File scripts/dev.ps1 -Action restart
#   powershell -File scripts/dev.ps1 -Action status
#
# Backend: uvicorn app.main:app --host 0.0.0.0 --port 8000
# Frontend: npx next dev -p 5173
# Logs: logs/backend.{out,err}.log + logs/frontend.out.log
param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "start"
)

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$LogDir = Join-Path $Root "logs"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$BackendPort = 8000
$FrontendPort = 5173
$BackendOutLog = Join-Path $LogDir "backend.out.log"
$BackendErrLog = Join-Path $LogDir "backend.err.log"
$FrontendOutLog = Join-Path $LogDir "frontend.out.log"

# ---------- helpers ----------

function Stop-Port {
    param([int]$Port)
    $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    foreach ($c in $conns) {
        if (-not $c) { continue }
        $procId = $c.OwningProcess
        Write-Host "  - kill PID $procId (port $Port)" -ForegroundColor DarkGray
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
}

function Wait-Health {
    param([int]$Port, [string]$Path, [int]$Timeout = 30)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $Timeout) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port$Path" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { return $true }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Pre-Check {
    if (-not (Test-Path $Python)) {
        Write-Host "X backend venv missing: $Python" -ForegroundColor Red
        Write-Host "  run: cd backend; uv sync" -ForegroundColor Yellow
        exit 1
    }
    if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
        Write-Host "X frontend node_modules missing" -ForegroundColor Red
        Write-Host "  run: cd frontend; npm install" -ForegroundColor Yellow
        exit 1
    }
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
}

# ---------- start ----------

function Do-Start {
    Write-Host ""
    Write-Host "=== START ===" -ForegroundColor Cyan
    Pre-Check

    Write-Host "- clean ports $BackendPort / $FrontendPort" -ForegroundColor DarkGray
    Stop-Port $BackendPort
    Stop-Port $FrontendPort
    Start-Sleep -Milliseconds 800

    Write-Host "- backend  uvicorn :$BackendPort" -ForegroundColor DarkGray
    $backendArgs = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$BackendPort")
    Start-Process -FilePath $Python -ArgumentList $backendArgs -WorkingDirectory $Backend -RedirectStandardOutput $BackendOutLog -RedirectStandardError $BackendErrLog -WindowStyle Hidden | Out-Null

    Write-Host "- frontend next dev :$FrontendPort" -ForegroundColor DarkGray
    $npxCmd = (Get-Command npx.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npxCmd) {
        Write-Host "X npx.cmd not found, install Node.js" -ForegroundColor Red
        exit 1
    }
    # 用 cmd /c 包裹走 shell,合并 stdout+stderr(避免 PowerShell 不允许同文件被两流重定向)
    Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "npx next dev -p $FrontendPort > `"$FrontendOutLog`" 2>&1") -WorkingDirectory $Frontend -WindowStyle Hidden | Out-Null

    Write-Host ""
    Write-Host "  backend health: " -NoNewline
    if (Wait-Health $BackendPort "/api/admin/health" 60) {
        Write-Host "OK http://127.0.0.1:$BackendPort" -ForegroundColor Green
    } else {
        Write-Host "TIMEOUT log: $BackendErrLog" -ForegroundColor Red
    }

    Write-Host "  frontend home: " -NoNewline
    if (Wait-Health $FrontendPort "/" 60) {
        Write-Host "OK http://127.0.0.1:$FrontendPort" -ForegroundColor Green
    } else {
        Write-Host "TIMEOUT log: $FrontendOutLog" -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "=== TIPS ===" -ForegroundColor Cyan
    Write-Host "  logs: $BackendErrLog"
    Write-Host "        $FrontendOutLog"
    Write-Host ""
    Write-Host "  stop:   powershell -File scripts/dev.ps1 -Action stop"
    Write-Host "  restart: powershell -File scripts/dev.ps1 -Action restart"
    Write-Host "  status: powershell -File scripts/dev.ps1 -Action status"
    Write-Host ""
}

# ---------- stop ----------

function Do-Stop {
    Write-Host ""
    Write-Host "=== STOP ===" -ForegroundColor Cyan
    Stop-Port $BackendPort
    Stop-Port $FrontendPort
    Start-Sleep -Milliseconds 800
    Write-Host "  OK backend(:$BackendPort) stopped"
    Write-Host "  OK frontend(:$FrontendPort) stopped"
    Write-Host ""
}

# ---------- status ----------

function Do-Status {
    Write-Host ""
    Write-Host "=== STATUS ===" -ForegroundColor Cyan
    foreach ($p in @($BackendPort, $FrontendPort)) {
        $conn = @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) | Select-Object -First 1
        if ($conn) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            Write-Host ("  :{0}  LISTEN  PID {1}  {2}" -f $p, $conn.OwningProcess, $proc.ProcessName) -ForegroundColor Green
        } else {
            Write-Host "  :$p  free" -ForegroundColor DarkGray
        }
    }
    Write-Host ""
}

switch ($Action) {
    "start"   { Do-Start }
    "stop"    { Do-Stop }
    "restart" { Do-Stop; Start-Sleep -Seconds 1; Do-Start }
    "status"  { Do-Status }
}