# 买股工具室 - 一键启动 / 停止 开发服务
#
# 用法(推荐走 .cmd,它会自动绕过本机执行策略):
#   scripts\dev.cmd                          启动
#   scripts\dev.cmd -Action stop             停止
#   scripts\dev.cmd -Action restart          重启
#   scripts\dev.cmd -Action status           查端口归属 + 本项目实际在跑的进程
#   scripts\dev.cmd -BackendPort 8010        固定后端端口(默认 8000)
#   scripts\dev.cmd -StrictPort              端口被别人占着时直接报错,不自动顺延
#
# 也可以直接用 PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -Action start
#   不加 -ExecutionPolicy Bypass 会报 "is not digitally signed"
#   (本机策略是 RemoteSigned,文件无签名),所以请优先用 dev.cmd。
#
# ── 端口冲突(2026-10-17 踩到的真实事故)──────────────────────────────
# Windows 允许 0.0.0.0:8000 与 127.0.0.1:8000 **同时监听**。如果别的程序先占了
# 127.0.0.1:8000,我们的 uvicorn 绑 0.0.0.0:8000 照样会"启动成功",但所有
# http://127.0.0.1:8000 的请求都会命中绑定更具体地址的那个程序 ——
# 现象就是:日志里 Application startup complete,健康检查却永远超时/404。
# 本机实测:8000 被另一个项目(Merchant AI)占着。
#
# 处理方式(默认行为):
#   ① 端口被**别的程序**占着 → 自动顺延到下一个空闲端口,并同步
#      frontend\.env.local 的 NEXT_PUBLIC_API_URL,你不用改任何配置;
#   ② 端口被**本项目旧进程**占着 → 直接杀干净再起;
#   ③ 两种情况都绝不盲杀别人的进程 —— 判据是命令行里必须出现本项目的路径
#      (backend\ / frontend\),因为"uvicorn app.main:app"这种命令任何 FastAPI
#      项目都有,只认它会把别的项目当成自己的旧进程杀掉(2026-10-17 实测踩到)。
#   传 -StrictPort 可把 ① 改回"报错退出"。
#
# Backend : uvicorn app.main:app --host 0.0.0.0 --port <实际后端端口>
# Frontend: node node_modules\next\dist\bin\next dev -p <FrontendPort>
# Logs    : logs/backend.{out,err}.log + logs/frontend.{out,err}.log
#           + logs/rich-<日期>.log (loguru JSON)
param(
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action = "start",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    # 健康检查超时(秒)。给到 180s 是因为 next dev 冷启动首次编译要 30-60s,
    # 后端启动还要跑 alembic 迁移 + 数据裁剪 + 按需 VACUUM。早先写死 60s,
    # 一次慢启动就打印 TIMEOUT,看起来就像"项目起不来"。
    [int]$HealthTimeout = 180,
    # 端口被别的程序占着时是否直接报错退出。
    # 默认($false)= 自动顺延到下一个空闲端口并同步前端 API 地址。
    # 为什么改默认值:本机 8000 被另一个项目(Merchant AI)常驻占用,
    # 老行为每次都 exit 1,脚本等于永远起不来;顺延是安全的,因为我们只会
    # 绑定一个**确认没人监听**的端口,不会踩 0.0.0.0/127.0.0.1 双重绑定的坑。
    # 想恢复老的"报错退出"行为:scripts\dev.cmd -StrictPort
    [switch]$StrictPort
)

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$LogDir = Join-Path $Root "logs"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
$BackendOutLog = Join-Path $LogDir "backend.out.log"
$BackendErrLog = Join-Path $LogDir "backend.err.log"
$FrontendOutLog = Join-Path $LogDir "frontend.out.log"
$FrontendErrLog = Join-Path $LogDir "frontend.err.log"
$StateFile = Join-Path $LogDir "dev-state.json"

# ---------- helpers ----------

function Show-LogTail {
    param([string]$Path, [int]$Lines = 15)
    if (-not (Test-Path $Path)) { return }
    Write-Host "  --- 日志尾部 $Path ---" -ForegroundColor DarkYellow
    Get-Content -Path $Path -Tail $Lines -Encoding UTF8 -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
}

# 输出监听该端口的 PID 列表。优先 netstat:受限环境下 Get-NetTCPConnection 可能返回空。
function Get-PortPids {
    param([int]$Port)
    $pids = New-Object System.Collections.Generic.List[int]
    try {
        foreach ($row in (netstat -ano | Select-String -Pattern "[:.]$Port\s")) {
            $cols = @(($row.Line -split '\s+') | Where-Object { $_ -ne '' })
            if ($cols.Length -ge 5 -and $cols[3] -eq 'LISTENING') {
                $parsed = 0
                if ([int]::TryParse($cols[4], [ref]$parsed) -and -not $pids.Contains($parsed)) {
                    $pids.Add($parsed)
                }
            }
        }
    } catch {}
    return $pids
}

# 全量枚举一次 Win32_Process 并缓存。
# 为什么不用 `-Filter "ProcessId=N"` 单查:2026-10-17 实测在这台机器上,
# 过滤查询会把 CommandLine 返回成**空字符串**(不报错、不提权失败),照着用就会
# 把本项目进程误判成"别的程序占着端口" —— status 误报、stop 不敢停。
# 全量枚举反而能拿到完整命令行。一次脚本运行里只枚举一次(后续若 miss 再强制刷新)。
$script:ProcCache = $null

function Get-AllProcesses {
    param([switch]$Force)
    if ($Force -or $null -eq $script:ProcCache) {
        try {
            $script:ProcCache = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        } catch {
            $script:ProcCache = @()
            Write-Host "  ! 枚举进程失败(权限不足),归属判断只能退化到端口" -ForegroundColor DarkYellow
        }
    }
    return $script:ProcCache
}

function Get-ProcessCommandLine {
    param([int]$ProcessId)
    $p = @(Get-AllProcesses) | Where-Object { $_.ProcessId -eq $ProcessId }
    if ($p.Count -eq 0) {
        # 可能是脚本运行期间新起的进程,缓存里还没有 —— 强制重新枚举一次
        $p = @(Get-AllProcesses -Force) | Where-Object { $_.ProcessId -eq $ProcessId }
    }
    if ($p.Count -eq 0) { return $null }
    return $p[0].CommandLine
}

# ---------- 进程台账 ----------
#
# 为什么需要它:2026-10-17 实测这台机器上 **519 个进程里有 167 个 CommandLine 是空的**
# (Get-CimInstance 与 Get-WmiObject 表现一致,不是权限问题 —— 同一个用户也能查到其它
# 字段,只有命令行缺失)。我们自己的 next dev 进程正好落在这一批里,于是"按命令行判归属"
# 完全失效:status 把自己的前端报成"别的程序",stop 也不敢停,残留进程占着 5173,
# 下次 start 直接失败。
# 所以脚本把自己启动过的 PID 记到 logs\dev-state.json,作为归属判断的权威依据。
# 记 PID 的同时记进程启动时刻 —— PID 会被系统回收复用,不校验就会误杀无辜进程。

function New-ProcRef {
    param($Process)
    if (-not $Process) { return $null }
    try {
        return [ordered]@{ pid = [int]$Process.Id; start = [int64]$Process.StartTime.Ticks }
    } catch { return $null }
}

function Write-DevState {
    param([object[]]$Backend = @(), [object[]]$Frontend = @(),
          [int]$BackendPort = 0, [int]$FrontendPort = 0)
    $state = [ordered]@{
        backend     = @($Backend | Where-Object { $_ })
        frontend    = @($Frontend | Where-Object { $_ })
        backendPort = $BackendPort
        frontendPort = $FrontendPort
        updatedAt   = (Get-Date).ToString('s')
    }
    try {
        [System.IO.File]::WriteAllText($StateFile, ($state | ConvertTo-Json -Depth 4),
            (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Write-Host "  ! 写进程台账失败:$($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

# 读台账里仍然有效的 PID(进程还在、且启动时刻对得上才算数)。
function Read-DevStatePids {
    param([ValidateSet('backend', 'frontend')][string]$Kind)
    $out = New-Object System.Collections.Generic.List[int]
    if (-not (Test-Path $StateFile)) { return $out }
    $st = $null
    try { $st = [System.IO.File]::ReadAllText($StateFile) | ConvertFrom-Json } catch { return $out }
    $recs = if ($Kind -eq 'backend') { $st.backend } else { $st.frontend }
    if (-not $recs) { return $out }
    foreach ($r in @($recs)) {
        if ($null -eq $r -or $null -eq $r.pid) { continue }
        $proc = Get-Process -Id ([int]$r.pid) -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        try {
            if ([int64]$r.start -ne [int64]$proc.StartTime.Ticks) { continue }
        } catch { continue }
        $out.Add([int]$r.pid)
    }
    return $out
}

# 沿父进程链回溯,返回**第一个读得到命令行的祖先**的命令行;找不到返回 $null。
# 用途:uv 的 venv 解释器是 launcher,真正跑代码的是它的子进程,命令行里没有项目路径。
# 深度上限 5 层(uv shim → venv python → uvicorn 实际执行者,3 层足够),
# 设上限是为了防止 PID 异常成环导致死循环。
function Get-ProcessAncestorCommandLine {
    param([int]$ProcessId, [int]$MaxDepth = 5)
    $procs = @(Get-AllProcesses)
    if ($procs.Count -eq 0) { return $null }
    $cur = $ProcessId
    for ($i = 0; $i -lt $MaxDepth; $i++) {
        $p = $procs | Where-Object { $_.ProcessId -eq $cur } | Select-Object -First 1
        if (-not $p -or -not $p.ParentProcessId) { return $null }
        $cur = [int]$p.ParentProcessId
        if ($cur -le 0 -or $cur -eq $ProcessId) { return $null }
        $ap = $procs | Where-Object { $_.ProcessId -eq $cur } | Select-Object -First 1
        if (-not $ap) { return $null }
        if ($ap.CommandLine) { return $ap.CommandLine }
    }
    return $null
}

# 判断 PID 是不是本项目自己的进程(uvicorn app.main:app / next dev)。
# 必须同时命中"本项目的路径",不能只认通用命令特征 ——
# 任何 FastAPI 项目都是 `python -m uvicorn app.main:app`,而 next dev 也不是本项目独有。
# 2026-10-17 实测:另一个项目(Merchant AI)的命令行是
#   "...\uv\python\cpython-3.12-...\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 老写法只判断 `uvicorn` + `app.main:app`,把它当成"本项目旧进程"直接 kill ——
# 正好违反本文件"绝不误杀用户其它项目"的初衷。
# 原则:宁可认不出(当成别人的,不杀),也不要误杀用户其它项目。
function Test-IsProjectProcess {
    param([int]$ProcessId, [ValidateSet('backend', 'frontend')][string]$Kind)
    # ① 台账优先:上一次 start 记下的 PID 就是我们自己起的,最权威
    if (@(Read-DevStatePids -Kind $Kind) -contains $ProcessId) { return $true }

    # ② 命令行:必须同时命中"本项目的路径",不能只认通用命令特征 ——
    #    任何 FastAPI 项目都是 `python -m uvicorn app.main:app`,只认它会把
    #    别的项目当成自己的旧进程杀掉(2026-10-17 实测踩到)。
    $cmd = Get-ProcessCommandLine $ProcessId
    if ($cmd) {
        if ($Kind -eq 'backend') {
            # 本项目的后端永远是 backend\.venv 下的 python 起的
            if (($cmd -match 'uvicorn') -and ($cmd -match 'app\.main:app') `
                -and ($cmd -match [regex]::Escape($Backend + '\'))) { return $true }
            # uv 的 venv 解释器只是 launcher:它会把真正执行代码的解释器**再 fork 一次**
            # (孙进程),孙进程的命令行里只有 uv 自己的 python 路径,没有本项目路径。
            # 只按命令行判 → 自家后端被当成"别的程序":status 每次误报"端口被其它程序占用",
            # stop 不敢停它,start 甚至会顺延到别的端口。
            # 这里沿**父进程链**回溯:祖先里只要有本项目的 uvicorn,这个孙进程就是本项目的
            # (与 Get-ProjectProcessIds 的子孙进程收拢逻辑同一套依据)。
            # 安全性不变:别的项目(Merchant AI 等)其祖先路径不含本项目 → 仍判为"别人",不误杀。
            if (($cmd -match 'uvicorn') -and ($cmd -match 'app\.main:app')) {
                $ancestor = Get-ProcessAncestorCommandLine -ProcessId $ProcessId
                if ($ancestor -and ($ancestor -match [regex]::Escape($Backend + '\'))) { return $true }
            }
            return $false
        }
        # 前端:next dev 会 fork 一个 start-server worker,**真正监听端口的是 worker**。
        # 两者的命令行都带本项目 node_modules 下的 next 路径,都要认出来 ——
        # 只认 `next dev` 会漏掉 worker,后果是 stop 杀不掉它(孤儿进程占着端口),
        # 下次 start 直接 EADDRINUSE。
        return ($cmd -match [regex]::Escape($Frontend + '\node_modules')) `
            -and (($cmd -match 'next') -or ($cmd -match 'start-server'))
    }
    # 读不到命令行(权限/沙箱)时退化为可执行文件路径判断 —— 后端只有我们自己的
    # venv 才会命中。仍然读不到就一律当成"别人的",绝不盲杀。
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) { return $false }
    if ($Kind -eq 'backend') {
        try {
            if ($proc.Path -and ($proc.Path -ieq $Python)) { return $true }
        } catch {}
    }
    Write-Host "  ! 读不到 PID $ProcessId 的命令行/路径,按'不是本项目'处理(不杀)" -ForegroundColor DarkYellow
    return $false
}

# 按命令行特征扫描本项目的进程,**与端口无关**。
# 为什么需要它:端口顺延之后,"只按 :$BackendPort 找"就找不到真正在跑的后端了
# (stop 会漏杀、status 会误报没起)。这是那台机器上 stop 漏掉 8010 上 uvicorn 的原因。
function Get-ProjectProcessIds {
    param([ValidateSet('backend', 'frontend')][string]$Kind)
    $ids = New-Object System.Collections.Generic.List[int]
    $procs = @(Get-AllProcesses)
    if ($procs.Count -eq 0) {
        # 枚举不到就至少还能靠台账
        return (Read-DevStatePids -Kind $Kind)
    }

    $seed = New-Object System.Collections.Generic.List[int]
    foreach ($p in $procs) {
        if (-not $p.ProcessId -or $p.ProcessId -eq $PID) { continue }
        $c = $p.CommandLine
        if (-not $c) { continue }
        if ($Kind -eq 'backend') {
            if (($c -match 'uvicorn') -and ($c -match 'app\.main:app') `
                -and ($c -match [regex]::Escape($Backend + '\'))) { $seed.Add([int]$p.ProcessId) }
        } else {
            # 同 Test-IsProjectProcess:next dev 的父进程和 start-server worker 都要算
            if (($c -match [regex]::Escape($Frontend + '\node_modules')) `
                -and (($c -match 'next') -or ($c -match 'start-server'))) { $seed.Add([int]$p.ProcessId) }
        }
    }
    foreach ($rec in (Read-DevStatePids -Kind $Kind)) {
        if (-not $seed.Contains($rec)) { $seed.Add($rec) }
    }

    # 把子孙进程一并收进来:next dev 真正监听端口的是它 fork 出来的 worker,
    # uv 的 venv 解释器还是孙进程(`.venv\Scripts\python.exe` 只是 launcher),
    # 而这机器上大量进程 WMI 拿不到 CommandLine,只能靠 ParentProcessId 认亲
    # (这个字段是好的,实测能读)。
    # ⚠ 不能无差别收下所有子孙:python/node 会带出 conhost.exe(控制台宿主)这类
    # 与本项目无关的系统进程,实测被误认成"本项目"打进了 kill 列表。
    # 所以子孙还要再过一道筛:命令行指向本项目目录的才收;命令行读不到的,
    # 只放行 python/node 这类解释器本身。
    $queue = New-Object System.Collections.Generic.Queue[int]
    foreach ($s in $seed) { $queue.Enqueue($s) }
    while ($queue.Count -gt 0) {
        $cur = $queue.Dequeue()
        if ($ids.Contains($cur)) { continue }
        $ids.Add($cur)
        foreach ($p in $procs) {
            if (-not $p.ProcessId -or -not $p.ParentProcessId) { continue }
            if ([int]$p.ParentProcessId -ne $cur) { continue }
            if (-not $queue.Contains([int]$p.ProcessId)) { $queue.Enqueue([int]$p.ProcessId) }
        }
    }
    # 剔除不该算进来的系统进程(它们的父进程恰好是我们的)
    $keep = New-Object System.Collections.Generic.List[int]
    foreach ($id in $ids) {
        $p = $procs | Where-Object { $_.ProcessId -eq $id } | Select-Object -First 1
        if ($p -and $p.CommandLine -and ($p.CommandLine -notmatch [regex]::Escape($Root + '\'))) {
            # 有命令行却不指向本项目 —— conhost / dllhost 之类,不是我们的服务
            continue
        }
        $keep.Add($id)
    }
    return $keep
}

# 打印"端口被别人占着"的完整说明(启动失败与 stop 两条路径共用一份,避免说法不一致)。
function Show-PortConflict {
    param([int]$Port, [ValidateSet('backend', 'frontend')][string]$Kind, [int]$ProcessId, [string]$ProcessName, [switch]$CanFallback)
    $alt = $Port + 10
    Write-Host ""
    Write-Host "  X 端口 $Port 被其它程序占用:PID $ProcessId ($ProcessName)" -ForegroundColor Red
    Write-Host "    这不是本项目的进程,脚本不会去杀它。" -ForegroundColor Yellow
    Write-Host ""
    if ($CanFallback) {
        Write-Host "    本次会自动顺延到下一个空闲端口,并同步 frontend\.env.local,你不用改任何配置。" -ForegroundColor Yellow
    }
    Write-Host "    想自己定端口:" -ForegroundColor Yellow
    if ($Kind -eq 'backend') {
        Write-Host "      scripts\dev.cmd -BackendPort $alt" -ForegroundColor Yellow
        Write-Host "    (前端 API 地址会自动同步,不用手改 frontend\.env.local)" -ForegroundColor DarkGray
    } else {
        Write-Host "      scripts\dev.cmd -FrontendPort $alt" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "    为什么必须换端口而不是继续:Windows 允许 0.0.0.0:$Port 与 127.0.0.1:$Port" -ForegroundColor DarkGray
    Write-Host "    同时监听。对方占着 127.0.0.1 时,我们的后端照样会打印启动成功," -ForegroundColor DarkGray
    Write-Host "    但所有 127.0.0.1:$Port 的请求都命中它 —— 健康检查永远超时。" -ForegroundColor DarkGray
    Write-Host ""
}

# 只停本项目占用该端口的进程;遇到别人的程序绝不盲杀。
# 默认(-无 -Soft):直接报错退出。
# -Soft:不退出,把别人的 PID 返回给调用方(端口顺延逻辑用)。
# 两条路径都会返回"别人的 PID 列表"。
function Stop-Port {
    param([int]$Port, [ValidateSet('backend', 'frontend')][string]$Kind, [switch]$Soft)
    $foreign = New-Object System.Collections.Generic.List[int]
    foreach ($procId in (Get-PortPids $Port)) {
        if ($procId -eq $PID) { continue }
        if (Test-IsProjectProcess $procId $Kind) {
            Write-Host "  - kill 本项目旧进程 PID $procId (:$Port)" -ForegroundColor DarkGray
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        } else {
            $foreign.Add($procId)
            if ($Soft) { continue }
            $procName = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
            # 提权/其它用户的进程读不到名字,说清楚原因,别显示成 "unknown" 让人以为脚本坏了
            if (-not $procName) { $procName = '进程名不可读,可能属于其它用户或提权进程' }
            Show-PortConflict -Port $Port -Kind $Kind -ProcessId $procId -ProcessName $procName
            exit 1
        }
    }
    return $foreign
}

# 解析本次要用的后端端口。
# 1) 先杀掉本项目在该端口上的旧进程;
# 2) 端口被别人占着 → 默认顺延到下一个**确认没人监听**的端口(并提示);
#    -StrictPort 则报错退出。
# 返回最终使用的端口号。
function Resolve-BackendPort {
    param([int]$Preferred)
    $port = $Preferred
    while ($true) {
        $foreign = @(Stop-Port -Port $port -Kind 'backend' -Soft)
        if ($foreign.Count -eq 0) { return $port }

        $pid0 = $foreign[0]
        $procName = (Get-Process -Id $pid0 -ErrorAction SilentlyContinue).ProcessName
        if (-not $procName) { $procName = '进程名不可读' }

        if ($StrictPort) {
            Show-PortConflict -Port $port -Kind 'backend' -ProcessId $pid0 -ProcessName $procName
            exit 1
        }

        $next = $port + 1
        while ((Get-PortPids $next).Count -gt 0) { $next++ }
        Write-Host ""
        Write-Host "  ! 端口 $port 被其它程序占用(PID $pid0 $procName),自动改用空闲端口 $next" -ForegroundColor Red
        Write-Host "    不杀它,也不假装绑定成功。想固定端口:scripts\dev.cmd -BackendPort <端口> -StrictPort" -ForegroundColor DarkGray
        $port = $next
    }
}

# 等后端就绪,并确认响应来自本项目,而不是占了同一端口的别的程序。
# 两个坑:①Invoke-WebRequest 在 PS 5.1 下按 Latin-1 解码响应体,中文标题会变乱码,
# 所以这里从原始字节流自己按 UTF-8 解码;②万一标题还是不可用,用一条 ASCII 路由
# 指纹兜底,确保"不会把别的程序误判成本项目"(误判会让你以为项目起来了)。
function Wait-BackendIdentity {
    param([int]$Port, [int]$Timeout)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $foreignTitle = $null
    while ($sw.Elapsed.TotalSeconds -lt $Timeout) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/openapi.json" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            $text = ''
            if ($resp.RawContentStream) {
                $text = [System.Text.Encoding]::UTF8.GetString($resp.RawContentStream.ToArray())
            } else {
                $text = [string]$resp.Content
            }
            $doc = $text | ConvertFrom-Json
            $title = $doc.info.title
            $isOurs = ($title -and $title -like '*买股工具室*') -or ($text -like '*/api/paper-trading/accounts*')
            if ($isOurs) {
                return @{ ok = $true; title = $title; seconds = $sw.Elapsed.TotalSeconds }
            }
            if ($title) { $foreignTitle = $title }
        } catch {}
        Start-Sleep -Milliseconds 400
    }
    return @{ ok = $false; title = $foreignTitle; seconds = $sw.Elapsed.TotalSeconds }
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

# ---------- 前端启动 ----------

# 把前端 API 地址对齐到本次实际使用的后端端口。
# 不对齐的后果不是报错,而是前端安静地打到占用同一端口的**别的项目**上 ——
# 这是最难查的一类故障:页面能开、数据全是别家的。
# 刻意用字节级读写,不用 Get-Content/Set-Content 管道:
#   ① PS 5.1 的 Set-Content -Encoding UTF8 会写 BOM,BOM 会被 dotenv 当成变量名
#      的一部分,首行变量直接失效(而且还不报错);
#   ② PS 5.1 默认按 ANSI(中文 Windows = GBK)解码,原文件里的中文注释会被重写成乱码。
# 换行风格与 BOM 有无都按原样保留。
function Set-FrontendApiUrl {
    param([int]$Port)
    $file = Join-Path $Frontend '.env.local'
    $value = "NEXT_PUBLIC_API_URL=http://127.0.0.1:$Port/api"

    if (-not (Test-Path $file)) {
        [System.IO.File]::WriteAllText($file, "$value`n", (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "  - 已新建 frontend\.env.local -> $value" -ForegroundColor DarkGray
        return
    }

    $bytes = [System.IO.File]::ReadAllBytes($file)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    if ($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF) { $text = $text.Substring(1) }
    $nl = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }

    $m = [regex]::Match($text, 'NEXT_PUBLIC_API_URL\s*=\s*(\S+)')
    if ($m.Success) {
        if ($m.Groups[1].Value -eq $value) { return }   # 已经一致,一个字都不动
        $current = $m.Groups[1].Value
        # 用 MatchEvaluator 而不是字符串替换,避免 $ 之类被当成替换组语法
        $new = [regex]::Replace($text, 'NEXT_PUBLIC_API_URL\s*=\s*\S+', { param($x) $value })
    } else {
        $current = '(未设置)'
        $new = $text.TrimEnd("`r", "`n") + $nl + $value + $nl
    }
    [System.IO.File]::WriteAllText($file, $new, (New-Object System.Text.UTF8Encoding($hasBom)))
    Write-Host "  - frontend\.env.local 已对齐:$current -> $value" -ForegroundColor DarkGray
}

# 从前端日志里认出"进程已经死了"的硬失败,避免白等满 180s 超时。
# 两个日志都要看:next 的启动横幅走 stdout,而 spawn EPERM 这类崩溃走 stderr。
function Get-FrontendCrashReason {
    if (-not (Test-Path $FrontendOutLog) -and -not (Test-Path $FrontendErrLog)) { return $null }
    $lines = @()
    foreach ($f in @($FrontendOutLog, $FrontendErrLog)) {
        if (Test-Path $f) {
            try { $lines += Get-Content -Path $f -Tail 40 -Encoding UTF8 -ErrorAction Stop } catch {}
        }
    }
    $tail = $lines -join "`n"
    if (-not $tail) { return $null }
    foreach ($sig in @('spawn EPERM', 'Cannot find module', 'ERR_MODULE_NOT_FOUND',
                        'EADDRINUSE', 'Failed to load next.config')) {
        if ($tail.Contains($sig)) { return $sig }
    }
    return $null
}

function Get-FrontendDiagnosis {
    param([string]$Reason)
    switch ($Reason) {
        'spawn EPERM' {
            return @"
  next dev 创建子进程时被系统拒绝(EPERM)。这是 Windows 上偶发的 spawn 失败,脚本会自动重试一次;
  重试仍失败时按顺序排查:
    1) 关掉正在同步 frontend\.next / node_modules 的软件(OneDrive、坚果云等)
    2) Windows 安全中心 -> 受控文件夹访问:把 node.exe 与 Windows Terminal 加白名单
    3) 用管理员身份打开终端再跑一次
"@
        }
        'EADDRINUSE' {
            return "  前端端口被占用。用 scripts\dev.cmd -FrontendPort <其它端口> 换一个。"
        }
        { $_ -match 'Cannot find module|ERR_MODULE_NOT_FOUND' } {
            return "  node_modules 不完整。跑:cd frontend; npm install"
        }
        { $_ -match 'next.config' } {
            return "  next.config 加载失败,详见上面的日志。"
        }
        default { return $null }
    }
}

# 启动 next dev 并等它就绪。返回 @{ ok; reason; seconds }
# reason: ready / crash / timeout
#
# 为什么直接用 node 起 next 的 bin,不走 `npx next dev`,也不套 cmd /c 转发:
#   ① `cmd /c "...node.exe" "...\next" dev > log 2>&1` 这条链在 PS 5.1 下
#      引号会被 Start-Process 重新转义,实测命令行被切坏,next 起不来;
#   ② npx = npm exec 自己先 fork 一层,多一层 spawn 就多一次 EPERM 机会;
#   ③ stdout/stderr 分开重定向正好和后端一致(PS 不允许两个流写同一个文件),
#      不用再为了合并输出而绕 shell。实测直连 node 4.5s 就绪。
function Start-Frontend {
    param([int]$Port, [int]$Timeout, [string]$NodeExe, [string]$NextBin,
          [object]$BackendRef = $null, [int]$BackendPort = 0)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $proc = Start-Process -FilePath $NodeExe -ArgumentList @($NextBin, 'dev', '-p', "$Port") `
        -WorkingDirectory $Frontend -RedirectStandardOutput $FrontendOutLog `
        -RedirectStandardError $FrontendErrLog -WindowStyle Hidden -PassThru
    # 注意:变量不能叫 $pid —— $PID 是 PowerShell 的只读自动变量(当前进程 ID),
    # 给它赋值会直接抛错并中断整个脚本(2026-10-17 实测踩到)。
    $childPid = if ($proc) { [int]$proc.Id } else { 0 }
    # 立刻记账:首次编译可能要一两分钟,这段时间里如果用户 Ctrl+C / 关掉终端,
    # 下一轮 start 就没有台账可依,只能报"端口被别的程序占用"。
    $frontRef = New-ProcRef $proc
    if ($frontRef) {
        Write-DevState -Backend @($BackendRef) -Frontend @($frontRef) `
            -BackendPort $BackendPort -FrontendPort $Port
    }
    while ($sw.Elapsed.TotalSeconds -lt $Timeout) {
        $crash = Get-FrontendCrashReason
        if ($crash) { return @{ ok = $false; reason = $crash; seconds = $sw.Elapsed.TotalSeconds; pid = $childPid } }
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                return @{ ok = $true; reason = 'ready'; seconds = $sw.Elapsed.TotalSeconds; pid = $childPid }
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    return @{ ok = $false; reason = 'timeout'; seconds = $sw.Elapsed.TotalSeconds; pid = $childPid }
}

# 把本项目所有在跑的进程停掉(与端口无关)。返回停掉的数量。
# start 之前也要调一次:上一轮如果中途失败退出(比如前端起不来),
# 它的后端往往还活着 —— 不清掉的话,下次 start 会因为"旧端口还占着"
# 一路顺延(8001 → 8002 → 8003…),端口越漂越远。
function Stop-ProjectProcesses {
    param([string]$Label = 'stop')
    $n = 0
    foreach ($kind in @('backend', 'frontend')) {
        foreach ($procId in (Get-ProjectProcessIds -Kind $kind)) {
            Write-Host "  - $Label 本项目 $kind PID $procId" -ForegroundColor DarkGray
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
            $n++
        }
    }
    return $n
}

# ---------- start ----------

function Do-Start {
    Write-Host ""
    Write-Host "=== START ===" -ForegroundColor Cyan
    Pre-Check

    Write-Host "- check ports $BackendPort / $FrontendPort" -ForegroundColor DarkGray
    Stop-ProjectProcesses -Label '清理上一轮遗留' | Out-Null
    Start-Sleep -Milliseconds 500
    $port = Resolve-BackendPort -Preferred $BackendPort   # 被别人占着就顺延(除非 -StrictPort)
    Stop-Port $FrontendPort 'frontend'
    Start-Sleep -Milliseconds 800

    # 固定 Python 的 stdout/stderr 编码为 UTF-8。否则日志文件的字节编码跟着系统
    # locale 走(zh-CN 是 GBK),而这个脚本又用 UTF-8 读日志 —— 全是乱码,
    # 排查问题时等于没有日志。
    $env:PYTHONIOENCODING = 'utf-8'
    Write-Host "- backend  uvicorn :$port" -ForegroundColor DarkGray
    $backendArgs = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$port")
    $backendProc = Start-Process -FilePath $Python -ArgumentList $backendArgs -WorkingDirectory $Backend `
        -RedirectStandardOutput $BackendOutLog -RedirectStandardError $BackendErrLog -WindowStyle Hidden -PassThru
    # 立刻记账:后面前端可能要等一两分钟,中途失败退出也要能靠台账清理后端
    $backendRef = New-ProcRef $backendProc
    Write-DevState -Backend @($backendRef) -Frontend @() -BackendPort $port -FrontendPort $FrontendPort

    Write-Host "- frontend next dev :$FrontendPort" -ForegroundColor DarkGray
    # 直接 node 起 next 的 bin:不经 npx、不套 cmd 转发(见 Start-Frontend 的注释),
    # 输出按后端同样的方式分成 out/err 两个日志文件。
    $node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
    if (-not $node) {
        Write-Host "X node.exe not found, install Node.js" -ForegroundColor Red
        exit 1
    }
    $nextBin = Join-Path $Frontend 'node_modules\next\dist\bin\next'
    if (-not (Test-Path $nextBin)) {
        Write-Host "X next not installed: $nextBin" -ForegroundColor Red
        Write-Host "  run: cd frontend; npm install" -ForegroundColor Yellow
        exit 1
    }
    # 后端端口变了就同步前端配置,并给子进程一份正确的环境变量
    Set-FrontendApiUrl -Port $port
    $env:NEXT_PUBLIC_API_URL = "http://127.0.0.1:$port/api"
    Write-Host "  (前端首次编译 / 可能要 1-3 分钟,进度看 logs\frontend.out.log)" -ForegroundColor DarkGray

    Write-Host ""
    Write-Host "  backend: " -NoNewline
    $be = Wait-BackendIdentity -Port $port -Timeout $HealthTimeout
    $ok = $true
    if ($be.ok) {
        Write-Host ("OK http://127.0.0.1:{0}  ({1:N1}s)" -f $port, $be.seconds) -ForegroundColor Green
    } else {
        $ok = $false
        Write-Host ("TIMEOUT (>{0}s)" -f $HealthTimeout) -ForegroundColor Red
        if ($be.title) {
            Write-Host "  ! 该端口上应答的程序是「$($be.title)」,不是本项目 —— 端口被占用了" -ForegroundColor Red
            Write-Host "    换端口:scripts\dev.cmd -BackendPort $($BackendPort + 10)(并同步改 frontend\.env.local)" -ForegroundColor Yellow
        }
        Show-LogTail $BackendErrLog
        Show-LogTail $BackendOutLog 8
    }

    Write-Host "  frontend: " -NoNewline
    # 超时预算给满 $HealthTimeout:崩溃(spawn EPERM 之类)是**秒级**返回的,靠
    # Get-FrontendCrashReason 早退出 + 重试处理;而首次编译 / 可能要 1-3 分钟,
    # 期间 next dev 会挂住请求而不是报错,只能用完整预算去等。
    # (早先单次只给 90s,实测 next 已 Ready 但仍在 "Compiling /",就被误判成起不来。)
    $fe = Start-Frontend -Port $FrontendPort -Timeout $HealthTimeout -NodeExe $node -NextBin $nextBin `
        -BackendRef $backendRef -BackendPort $port
    if (-not $fe.ok -and $fe.reason -ne 'timeout') {
        # next dev 秒崩(spawn EPERM 之类),重试一次
        Write-Host ("{0},自动重试一次..." -f $fe.reason) -ForegroundColor Red
        Start-Sleep -Seconds 2
        $fe = Start-Frontend -Port $FrontendPort -Timeout $HealthTimeout -NodeExe $node -NextBin $nextBin `
            -BackendRef $backendRef -BackendPort $port
    }
    if ($fe.ok) {
        Write-Host ("OK http://127.0.0.1:{0}  ({1:N1}s)" -f $FrontendPort, $fe.seconds) -ForegroundColor Green
    } else {
        $ok = $false
        if ($fe.reason -eq 'timeout') {
            Write-Host ("TIMEOUT (>{0:N0}s)" -f $fe.seconds) -ForegroundColor Red
        } else {
            Write-Host ("启动失败:$($fe.reason)") -ForegroundColor Red
        }
        Show-LogTail $FrontendErrLog
        Show-LogTail $FrontendOutLog
        $diag = Get-FrontendDiagnosis -Reason $fe.reason
        if ($diag) { Write-Host $diag -ForegroundColor Yellow }
        Write-Host "  其他常见原因:" -ForegroundColor Yellow
        Write-Host "    - node_modules 不完整 → cd frontend; npm install" -ForegroundColor Yellow
        Write-Host "    - 端口被别的东西占了 → scripts\dev.cmd -FrontendPort $($FrontendPort + 10)" -ForegroundColor Yellow
    }

    Write-Host ""
    if (-not $ok) {
        Write-Host "=== 启动未全部成功 ===" -ForegroundColor Red
        Write-Host "  上面标红的服务没起来,日志尾部已经打出来了。" -ForegroundColor Yellow
        if ($port -ne $BackendPort) {
            Write-Host "  本次后端用的是 $port($BackendPort 被别的程序占着,已自动顺延)。" -ForegroundColor Yellow
            Write-Host "  要固定用别的端口:scripts\dev.cmd -BackendPort $($port + 10)" -ForegroundColor Yellow
        }
    }
    # 记账前端 PID(取最后一次尝试的)。下次 start / stop 就靠它认亲 ——
    # 这机器上 WMI 经常给不出 next 的命令行,只靠命令行会认不出自己的进程。
    $frontendRefs = @()
    if ($fe.pid) {
        $ref = New-ProcRef (Get-Process -Id $fe.pid -ErrorAction SilentlyContinue)
        if ($ref) { $frontendRefs = @($ref) }
    }
    Write-DevState -Backend @($backendRef) -Frontend $frontendRefs -BackendPort $port -FrontendPort $FrontendPort
    Write-Host "=== TIPS ===" -ForegroundColor Cyan
    Write-Host "  logs: $BackendErrLog   (人类可读)"
    Write-Host "        $LogDir\rich-<日期>.log   (loguru JSON,含 DEBUG,排查时更全)"
    Write-Host "        $FrontendOutLog / $FrontendErrLog"
    Write-Host ""
    Write-Host "  stop:    scripts\dev.cmd -Action stop"
    Write-Host "  restart: scripts\dev.cmd -Action restart"
    Write-Host "  status:  scripts\dev.cmd -Action status"
    Write-Host "  固定后端端口: scripts\dev.cmd -BackendPort 8010    (8000 被占时默认自动顺延)"
    Write-Host ""
    if (-not $ok) { exit 1 }
}

# ---------- stop ----------

function Do-Stop {
    Write-Host ""
    Write-Host "=== STOP ===" -ForegroundColor Cyan
    # 用 -Soft:默认端口 8000 可能是别人的进程,stop 不该因此报错退出。
    Stop-Port $BackendPort 'backend' -Soft | Out-Null
    Stop-Port $FrontendPort 'frontend' -Soft | Out-Null
    # 兜底:按命令行扫一遍本项目的进程。
    # 端口顺延之后"只按 :$BackendPort 找"会漏掉真正在跑的后端(上次就漏过一次,
    # 结果 stop 之后 8010 上的 uvicorn 还活着,只能手动 taskkill)。
    Stop-ProjectProcesses -Label 'kill' | Out-Null
    Start-Sleep -Milliseconds 800
    # 台账清空:不然后一轮 start 会拿着旧 PID(虽然有启动时刻校验)反复尝试
    Write-DevState -Backend @() -Frontend @() -BackendPort $BackendPort -FrontendPort $FrontendPort
    Write-Host "  OK backend / frontend 已停止(别人的进程一律没动)" -ForegroundColor Green
    Write-Host ""
}

# ---------- status ----------

function Do-Status {
    Write-Host ""
    Write-Host "=== STATUS ===" -ForegroundColor Cyan
    foreach ($item in @(
        @{ Port = $BackendPort; Kind = 'backend' },
        @{ Port = $FrontendPort; Kind = 'frontend' }
    )) {
        $pids = Get-PortPids $item.Port
        if ($pids.Count -eq 0) {
            Write-Host ("  :{0}  free" -f $item.Port) -ForegroundColor DarkGray
            continue
        }
        foreach ($procId in $pids) {
            $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
            $name = if ($proc) { $proc.ProcessName } else { 'unknown' }
            if (Test-IsProjectProcess $procId $item.Kind) {
                Write-Host ("  :{0}  LISTEN  PID {1}  {2}  (本项目)" -f $item.Port, $procId, $name) -ForegroundColor Green
            } else {
                Write-Host ("  :{0}  LISTEN  PID {1}  {2}  (其它程序!本项目自动顺延到别的端口)" -f $item.Port, $procId, $name) -ForegroundColor Red
                Write-Host ("      确认确实是你自己的再手动停:taskkill /PID {0} /T /F" -f $procId) -ForegroundColor DarkGray
            }
        }
    }

    # 端口被顺延过的时候,上面只看默认端口会误报"没起" —— 补一段与端口无关的实际扫描。
    $running = 0
    foreach ($kind in @('backend', 'frontend')) {
        foreach ($procId in (Get-ProjectProcessIds -Kind $kind)) {
            $running++
            $cmd = Get-ProcessCommandLine $procId
            $shown = if ($cmd) { $cmd } else { '(读不到命令行)' }
            if ($shown.Length -gt 110) { $shown = $shown.Substring(0, 110) + '...' }
            Write-Host ("  [本项目] {0}  PID {1}  {2}" -f $kind, $procId, $shown) -ForegroundColor Green
        }
    }
    if ($running -eq 0) {
        Write-Host "  本项目当前没有进程在跑(用 scripts\dev.cmd 启动)" -ForegroundColor DarkGray
    }
    Write-Host ""
}

switch ($Action) {
    "start"   { Do-Start }
    "stop"    { Do-Stop }
    "restart" { Do-Stop; Start-Sleep -Seconds 1; Do-Start }
    "status"  { Do-Status }
}
