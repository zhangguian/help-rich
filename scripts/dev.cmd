@echo off
rem ============================================================
rem  Stock Toolbox - dev service launcher (PowerShell wrapper)
rem
rem  Why this .cmd exists:
rem    The local PowerShell execution policy is RemoteSigned, so running
rem    dev.ps1 directly fails with:
rem      "File dev.ps1 cannot be loaded. The file is not digitally signed."
rem    This wrapper passes -ExecutionPolicy Bypass for this one process only;
rem    it does NOT change any system setting.
rem
rem  Usage:
rem    scripts\dev.cmd                     start (default)
rem    scripts\dev.cmd -Action stop        stop
rem    scripts\dev.cmd -Action restart     restart
rem    scripts\dev.cmd -Action status      show which process owns each port
rem                                          + the project processes actually running
rem    scripts\dev.cmd -BackendPort 8010   pin the backend port (default 8000)
rem    scripts\dev.cmd -FrontendPort 5174  pin the frontend port (default 5173)
rem    scripts\dev.cmd -StrictPort         fail instead of auto-falling back when
rem                                          the backend port belongs to another app
rem    scripts\dev.cmd -HealthTimeout 300  wait longer for slow cold starts
rem
rem  Default behavior when the backend port is taken by ANOTHER program:
rem    auto-fall-forward to the next free port and sync frontend\.env.local,
rem    so no manual edit is needed. Our own old processes are killed; foreign
rem    processes are never killed.
rem
rem  NOTE: keep this file pure ASCII. cmd.exe parses batch files with the
rem  OEM code page (GBK on zh-CN), so UTF-8 Chinese comments corrupt line
rem  boundaries and produce "'xx' is not recognized as an internal command".
rem ============================================================
setlocal
set "SCRIPT=%~dp0dev.ps1"

where powershell >nul 2>nul
if errorlevel 1 (
    echo [X] powershell.exe not found
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo [X] launcher exited with %CODE% - read the message above; logs: logs\backend.err.log / logs\frontend.out.log
)
exit /b %CODE%
