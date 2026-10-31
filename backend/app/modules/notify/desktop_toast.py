"""Windows 原生桌面通知。

两条投递路径(自动降级,都能在「浏览器关着」时收到):

1. **WinRT Toast**(首选,现代通知中心卡片)
   `powershell.exe` + `Windows.UI.Notifications.ToastNotificationManager`。
2. **Win32 托盘气泡**(兜底,经典气泡提示)
   `System.Windows.Forms.NotifyIcon.ShowBalloonTip` —— **不需要 package identity**,
   在受限环境(受限令牌 / 沙箱 / 非交互会话)里 Toast 路径会被平台拒掉,气泡仍能弹。

**零新依赖**:`backend/.venv` 里没有 winotify / win11toast / plyer / winsdk,
`BurntToast` 也没装 → 只用 Windows 自带的 PowerShell 5.1。
注意只能用 `powershell.exe`(Windows PowerShell),`pwsh.exe`(PowerShell 7)
去掉了 WinRT 投影,发不出去。

**坑 1:「The process has no package identity」(0x80073D54)**
非打包应用(我们的后端进程就是)直接调 `ToastNotificationManager.CreateToastNotifier(AUMID)`
会抛这个错 —— 实测借系统 AUMID 也一样抛。
解法:**先调 `SetCurrentProcessExplicitAppUserModelID(AUMID)`** 给当前进程一个显式身份,
再 `CreateToastNotifier(同一个 AUMID)`。注意该 API **每进程只能调一次**,
所以每个 AUMID 候选要各起一个 powershell 进程。

**坑 2:`Add-Type` 要写编译临时文件**
上面的 P/Invoke 靠 `Add-Type` 现场编译 C#,它把中间产物写在 **%TEMP%**。
若子进程的 %TEMP% 不可写(受限环境 / 杀软策略),`Add-Type` 报 UnauthorizedAccessException
→ 类型没加载 → 身份没设上 → 又回到坑 1。
解法:给 powershell 子进程**显式指定一个它自己能写的临时目录**(见 `_temp_dir_candidates`),
并在报错像临时目录问题时换目录重试。气泡路径只用 `Add-Type -AssemblyName`(纯加载,不编译),
不依赖临时目录。

**传参纪律**:整段脚本用 `-EncodedCommand`(UTF-16LE base64)交给 powershell.exe,
标题/正文再各自 base64(UTF-8)后内嵌进脚本 → 中文 / 引号 / 换行 / emoji 都不会
被 argv 解析坏(本项目已多次踩过「`python -c` 内嵌双引号被 argv 吞掉」「管道给
stdin 加 BOM」的坑)。

**平台守卫**:平台判断收在函数内,**import 期不做任何平台相关调用**
(CI 在 Linux 上跑 pytest,import 期调用会直接炸)。
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import re
import tempfile
from pathlib import Path

from app.modules.notify.base import NotifyError

# 借用的系统应用 AUMID(本机实测:先 SetCurrentProcessExplicitAppUserModelID 再
# CreateToastNotifier 均可 SHOW_OK)。
# 已知外观限制:通知中心里显示的是**被借用应用**的名字/图标 —— 见 ADR-0007。
DEFAULT_AUMIDS: tuple[str, ...] = (
    "Microsoft.WindowsPowerShell_8wekyb3d8bbwe!Microsoft.PowerShell",
    "Microsoft.WindowsTerminal_8wekyb3d8bbwe!App",
    "Microsoft.WindowsStore_8wekyb3d8bbwe!App",
)

_POWERSHELL = "powershell.exe"
_DEFAULT_TIMEOUT_SEC = 15.0  # Add-Type 要现场编译 C#,给足冷启动时间
_BALLOON_VISIBLE_SEC = 8     # 气泡在屏上的时长
_BALLOON_TIMEOUT_SEC = 25.0  # 气泡脚本要在屏上待几秒,超时给足

# 已验证可用的临时目录(模块级缓存,避免每次发通知都重新试一遍)
_tmp_dir_cache: str | None = None


def _b64(text: str) -> str:
    """UTF-8 文本 → base64(ASCII 安全,可直接内嵌进 PowerShell 脚本)。"""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _temp_dir_candidates() -> list[str]:
    """给 powershell 子进程挑临时目录的候选(按优先级,去重保序)。

    `Add-Type` 把 C# 编译中间产物写在 %TEMP%;目录不可写就会整套失败。
    候选顺序:环境变量 TEMP/TMP → `tempfile.gettempdir()` → 应用自己的目录。
    """
    candidates: list[str] = []
    for name in ("TEMP", "TMP"):
        value = os.environ.get(name)
        if value:
            candidates.append(value)
    with contextlib.suppress(Exception):
        candidates.append(tempfile.gettempdir())
    with contextlib.suppress(Exception):
        from app.core.config import settings

        candidates.append(str(Path(settings.log_dir).parent))
    with contextlib.suppress(Exception):
        candidates.append(str(Path(tempfile.gettempdir()).parent))

    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    return unique or [str(Path.cwd())]


def _extract_error(raw: str) -> str:
    """把 powershell 的 stderr 收拾成一句人能看懂的话(去掉 CLIXML 噪音)。

    保留足够长的尾巴:关键信息(如 `no package identity`)往往在报错靠前的位置,
    截太短会让上层判断不出该不该降级到气泡。
    """
    text = raw or ""
    if "#< CLIXML" in text:
        text = text.split("<Objs", 1)[-1]
    text = text.replace("_x000D__x000A_", "\n").replace("_x000D_", "")
    lines = [re.sub(r"<[^>]+>", "", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    tail = lines[-12:] if lines else ["未知错误"]
    return " | ".join(tail)[:900]


def _looks_like_temp_problem(err: str) -> bool:
    """判断失败是否由「临时目录不可写 / Add-Type 编译失败」引起。"""
    markers = ("Add-Type", "UnauthorizedAccessException", "Access to the path")
    return any(m in err for m in markers)


def _looks_like_identity_problem(err: str) -> bool:
    """判断失败是否由「进程没有 package identity」引起(→ 可降级到气泡)。"""
    markers = ("no package identity", "0x80073D54")
    return any(m in err for m in markers)


def build_toast_script(title: str, body: str, aumid: str) -> str:
    """生成**单个 AUMID** 的 WinRT Toast PowerShell 脚本(标题/正文 base64 内嵌)。

    拆成多行拼接而不是 f-string:PowerShell 脚本里到处是 `{}`,f-string 会逼着
    到处写 `{{`/`}}`,极易漏一处 —— 这里只对两行 base64 与 AUMID 做插值。
    """
    safe_aumid = aumid.replace("'", "''")
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "$titleB64 = '" + _b64(title) + "'\n"
        "$bodyB64 = '" + _b64(body) + "'\n"
        # --- 给当前进程一个显式身份(否则 CreateToastNotifier 抛 0x80073D54)---
        "Add-Type -TypeDefinition @'\n"
        "using System;\n"
        "using System.Runtime.InteropServices;\n"
        "namespace RichToast {\n"
        "  public static class Helper {\n"
        "    [DllImport(\"shell32.dll\", CharSet = CharSet.Unicode)]\n"
        "    public static extern int SetCurrentProcessExplicitAppUserModelID(string appID);\n"
        "  }\n"
        "}\n"
        "'@\n"
        "$rc = [RichToast.Helper]::SetCurrentProcessExplicitAppUserModelID('" + safe_aumid + "')\n"
        "if ($rc -ne 0) { Write-Error ('SetCurrentProcessExplicitAppUserModelID failed: ' + $rc) "
        "exit 1 }\n"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType=WindowsRuntime] | Out-Null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, "
        "ContentType=WindowsRuntime] | Out-Null\n"
        "$title = [System.Text.Encoding]::UTF8.GetString("
        "[System.Convert]::FromBase64String($titleB64))\n"
        "$body = [System.Text.Encoding]::UTF8.GetString("
        "[System.Convert]::FromBase64String($bodyB64))\n"
        "$xml = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, "
        "ContentType=WindowsRuntime]::new()\n"
        "$toastNode = $xml.CreateElement('toast')\n"
        "$visualNode = $xml.CreateElement('visual')\n"
        "$bindingNode = $xml.CreateElement('binding')\n"
        "$bindingNode.SetAttribute('template', 'ToastText02')\n"
        "$t1 = $xml.CreateElement('text')\n"
        "$t1.SetAttribute('id', '1')\n"
        "$t1.AppendChild($xml.CreateTextNode($title)) | Out-Null\n"
        "$t2 = $xml.CreateElement('text')\n"
        "$t2.SetAttribute('id', '2')\n"
        "$t2.AppendChild($xml.CreateTextNode($body)) | Out-Null\n"
        "$bindingNode.AppendChild($t1) | Out-Null\n"
        "$bindingNode.AppendChild($t2) | Out-Null\n"
        "$visualNode.AppendChild($bindingNode) | Out-Null\n"
        "$toastNode.AppendChild($visualNode) | Out-Null\n"
        "$xml.AppendChild($toastNode) | Out-Null\n"
        "$toast = [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, "
        "ContentType=WindowsRuntime]::new($xml)\n"
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        "CreateToastNotifier('" + safe_aumid + "').Show($toast)\n"
        "Write-Output ('OK:' + '" + safe_aumid + "')\n"
        "exit 0\n"
    )


def build_balloon_script(title: str, body: str, visible_sec: int = _BALLOON_VISIBLE_SEC) -> str:
    """生成托盘气泡脚本(纯程序集加载,不编译 C#,不依赖 %TEMP% 可写)。"""
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "$titleB64 = '" + _b64(title) + "'\n"
        "$bodyB64 = '" + _b64(body) + "'\n"
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$title = [System.Text.Encoding]::UTF8.GetString("
        "[System.Convert]::FromBase64String($titleB64))\n"
        "$body = [System.Text.Encoding]::UTF8.GetString("
        "[System.Convert]::FromBase64String($bodyB64))\n"
        "$ni = New-Object System.Windows.Forms.NotifyIcon\n"
        "$ni.Icon = [System.Drawing.SystemIcons]::Information\n"
        "$ni.Visible = $true\n"
        "$ni.BalloonTipTitle = $title\n"
        "$ni.BalloonTipText = $body\n"
        "$ni.ShowBalloonTip(" + str(int(visible_sec)) + ")\n"
        "Write-Output 'BALLOON_SHOWN'\n"
        # 气泡必须托着图标才能留在屏上 —— 脚本自己多活几秒再退
        "Start-Sleep -Seconds " + str(int(visible_sec) + 1) + "\n"
        "$ni.Dispose()\n"
        "Write-Output 'OK:BALLOON'\n"
        "exit 0\n"
    )


def _child_env(temp_dir: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if temp_dir:
        env["TEMP"] = temp_dir
        env["TMP"] = temp_dir
    return env


async def _spawn(script: str, temp_dir: str | None) -> asyncio.subprocess.Process:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        return await asyncio.create_subprocess_exec(
            _POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_child_env(temp_dir),
        )
    except OSError as e:
        raise NotifyError(f"启动 {_POWERSHELL} 失败: {e}") from e


async def _run_script(
    script: str, timeout_sec: float, temp_dir: str | None
) -> tuple[int, str, str]:
    """跑完一段 PowerShell 脚本,返回 (exit code, stdout, stderr)。"""
    proc = await _spawn(script, temp_dir)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except TimeoutError as e:
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
        raise NotifyError(f"桌面通知超时({timeout_sec:g}s)") from e
    return (
        proc.returncode,
        (out or b"").decode("utf-8", "replace").strip(),
        (err or b"").decode("utf-8", "replace").strip(),
    )


async def _drain(proc: asyncio.subprocess.Process) -> None:
    """后台收尾:等子进程自然退出并回收管道(气泡要活几秒,不能阻塞调用方)。"""
    with contextlib.suppress(Exception):
        await proc.communicate()


async def _send_via_toast(
    title: str, body: str, aumid: str | None, timeout_sec: float
) -> str:
    """WinRT Toast 路径(逐个 AUMID 候选试)。"""
    global _tmp_dir_cache

    candidates = (aumid,) if aumid else DEFAULT_AUMIDS
    temp_dirs = [_tmp_dir_cache] if _tmp_dir_cache else _temp_dir_candidates()
    last_error = "未知错误"

    for candidate in candidates:
        script = build_toast_script(title, body, candidate)
        for temp_dir in temp_dirs:
            code, out, err = await _run_script(script, timeout_sec, temp_dir)
            if code == 0:
                _tmp_dir_cache = temp_dir
                return out or f"OK:{candidate}"
            last_error = _extract_error(err or out)
            if temp_dir is not temp_dirs[-1] and _looks_like_temp_problem(last_error):
                # 这个临时目录子进程写不动 → 换下一个目录重试
                continue
            if _looks_like_identity_problem(last_error):
                # 身份问题与 AUMID 无关 → 换候选也没用,直接上抛让上层降级到气泡
                raise NotifyError(
                    f"桌面通知失败(候选 {len(candidates)} 个全部失败): {last_error[:900]}"
                )
            break

    raise NotifyError(f"桌面通知失败(候选 {len(candidates)} 个全部失败): {last_error[:400]}")


async def _send_via_balloon(title: str, body: str) -> str:
    """Win32 托盘气泡路径(不需要 package identity)。"""
    script = build_balloon_script(title, body)
    temp_dir = _tmp_dir_cache or (_temp_dir_candidates() or [None])[0]
    proc = await _spawn(script, temp_dir)
    try:
        line = await asyncio.wait_for(
            proc.stdout.readline(), timeout=_BALLOON_TIMEOUT_SEC
        )
    except TimeoutError as e:
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
        raise NotifyError(f"桌面气泡通知超时({_BALLOON_TIMEOUT_SEC:g}s)") from e
    except Exception as e:  # pragma: no cover - 管道异常
        raise NotifyError(f"桌面气泡通知失败: {e}") from e

    if b"BALLOON_SHOWN" not in line:
        with contextlib.suppress(Exception):
            err_text = (await proc.stderr.read()).decode("utf-8", "replace").strip()
        with contextlib.suppress(ProcessLookupError, OSError):
            proc.kill()
        raise NotifyError(f"桌面气泡通知失败: {_extract_error(err_text)[:300]}")

    # 气泡还要在屏上待几秒 —— 后台收尾,不阻塞调用方
    asyncio.create_task(_drain(proc))
    return "OK:BALLOON"


async def send_toast(
    title: str,
    body: str,
    aumid: str | None = None,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
    mode: str = "auto",
) -> str:
    """发一条 Windows 桌面通知。

    Args:
        title: 通知标题(中文/emoji 安全)
        body: 通知正文
        aumid: 指定 AUMID;None → 按 `DEFAULT_AUMIDS` 逐个尝试
            (每个候选各起一个 powershell 进程:`SetCurrentProcessExplicitAppUserModelID`
            每进程只能调一次)
        timeout_sec: Toast 路径的子进程超时秒数(默认 15s,Add-Type 要现场编译 C#)
        mode: `auto`(默认,Toast 失败自动降级到气泡) / `toast`(只用 Toast) /
            `balloon`(只用气泡)

    Returns:
        脚本 stdout(`OK:<aumid>` 或 `OK:BALLOON`),用于诊断实际走了哪条路。

    Raises:
        NotifyError: 非 Windows / 启动失败 / 超时 / 两条路径都失败。
    """
    if os.name != "nt":
        raise NotifyError("桌面通知仅支持 Windows(当前平台不支持)")

    if mode == "balloon":
        return await _send_via_balloon(title, body)

    try:
        return await _send_via_toast(title, body, aumid, timeout_sec)
    except NotifyError as e:
        if mode == "toast":
            raise
        toast_error = str(e)
        if not _looks_like_identity_problem(toast_error) and not _looks_like_temp_problem(
            toast_error
        ):
            raise
        # 平台不认这个进程的 package identity(或临时目录写不动)→ 降级到托盘气泡
        try:
            return await _send_via_balloon(title, body)
        except NotifyError as balloon_error:
            raise NotifyError(
                f"桌面通知失败(Toast: {toast_error[:200]} | 气泡: {str(balloon_error)[:200]})"
            ) from balloon_error


__all__ = ["DEFAULT_AUMIDS", "build_balloon_script", "build_toast_script", "send_toast"]
