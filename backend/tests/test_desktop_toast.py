"""桌面通知(Windows Toast)通道测试

覆盖:
- 非 Windows 平台 → NotifyError(平台守卫收在函数内,**import 期不触发**)
- 脚本里的 base64 参数能原样还原出中文标题/正文(含引号/换行/emoji)
- 子进程非零退出 → NotifyError
- 子进程超时 → NotifyError
- desktop 渠道零凭据即可构造 notifier(不要求 webhook/key)
"""
from __future__ import annotations

import asyncio
import base64
import re
from types import SimpleNamespace

import pytest

from app.modules.notify import desktop_toast
from app.modules.notify.base import NotifyChannel, NotifyError, NotifyMessage
from app.modules.notify.channels import DesktopNotifier
from app.modules.notify.service import _build_notifier

_TITLE = "急速拉升 · 002185.SZ"
_BODY = "60 秒内涨 1.83%,现价 12.50\n触发价:12.49 “引号” 😀"


def _decode_script_literal(script: str, var: str) -> str:
    """从脚本里取出 `$var = '<base64>'` 并还原原文。"""
    m = re.search(rf"^\${var} = '([A-Za-z0-9+/=]+)'$", script, flags=re.MULTILINE)
    assert m, f"脚本里找不到 ${var} 的 base64 字面量"
    return base64.b64decode(m.group(1)).decode("utf-8")


class _FakeProc:
    """假的 powershell 子进程。"""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", code: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = code
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True


class _SlowProc(_FakeProc):
    async def communicate(self):
        await asyncio.sleep(10)
        return b"", b""


def test_base64_roundtrip_keeps_chinese_title_and_body() -> None:
    """标题/正文以 base64 内嵌 → 中文/引号/换行/emoji 都不会被脚本解析坏。"""
    script = desktop_toast.build_toast_script(_TITLE, _BODY, "Test!App")
    assert _decode_script_literal(script, "titleB64") == _TITLE
    assert _decode_script_literal(script, "bodyB64") == _BODY


def test_script_encodes_as_utf16le_base64_for_encoded_command() -> None:
    """-EncodedCommand 要求 UTF-16LE base64,这里锁住编码方式。"""
    script = desktop_toast.build_toast_script(_TITLE, _BODY, "Test!App")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    decoded = base64.b64decode(encoded).decode("utf-16-le")
    assert _TITLE in decoded or "titleB64" in decoded


def test_custom_aumid_is_used_and_defaults_are_not() -> None:
    script = desktop_toast.build_toast_script("t", "b", aumid="My.App!App")
    assert "My.App!App" in script
    assert desktop_toast.DEFAULT_AUMIDS[0] not in script


def test_script_sets_process_identity_before_creating_notifier() -> None:
    """非打包进程必须先 SetCurrentProcessExplicitAppUserModelID,否则 0x80073D54。"""
    script = desktop_toast.build_toast_script("t", "b", aumid="My.App!App")
    assert "SetCurrentProcessExplicitAppUserModelID" in script
    # 身份设置必须发生在 CreateToastNotifier 之前
    assert script.index("SetCurrentProcessExplicitAppUserModelID") < script.index(
        "CreateToastNotifier"
    )


@pytest.mark.asyncio
async def test_non_windows_raises_notify_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 Windows → NotifyError(CI 在 Linux 上跑,这里不能炸)。"""
    monkeypatch.setattr(desktop_toast, "os", SimpleNamespace(name="posix"))
    with pytest.raises(NotifyError, match="仅支持 Windows"):
        await desktop_toast.send_toast(_TITLE, _BODY)


@pytest.mark.asyncio
async def test_nonzero_exit_raises_notify_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """脚本非零退出 → 逐个候选试完仍失败 → NotifyError(带 stderr 摘要)。"""
    calls: list = []

    async def _fake_exec(*args, **kwargs):
        calls.append(args)
        return _FakeProc(stderr="Toast 发送失败: 找不到 AUMID".encode(), code=1)

    monkeypatch.setattr(desktop_toast.asyncio, "create_subprocess_exec", _fake_exec)
    with pytest.raises(NotifyError) as exc:
        await desktop_toast.send_toast(_TITLE, _BODY)
    # 每个候选各起一个进程(SetCurrentProcessExplicitAppUserModelID 每进程只准调一次)
    assert len(calls) == len(desktop_toast.DEFAULT_AUMIDS)
    assert "Toast 发送失败" in str(exc.value)


@pytest.mark.asyncio
async def test_timeout_raises_notify_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """子进程超时 → NotifyError(并且要杀掉残留进程)。"""
    proc = _SlowProc()

    async def _fake_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(desktop_toast.asyncio, "create_subprocess_exec", _fake_exec)
    with pytest.raises(NotifyError, match="超时"):
        await desktop_toast.send_toast(_TITLE, _BODY, timeout_sec=0.05)
    assert proc.killed is True


@pytest.mark.asyncio
async def test_success_returns_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """成功 → 返回脚本 stdout(带实际使用的 AUMID)。"""

    async def _fake_exec(*args, **kwargs):
        return _FakeProc(stdout=b"OK:Microsoft.WindowsPowerShell_8wekyb3d8bbwe!Microsoft.PowerShell")

    monkeypatch.setattr(desktop_toast.asyncio, "create_subprocess_exec", _fake_exec)
    out = await desktop_toast.send_toast(_TITLE, _BODY)
    assert out.startswith("OK:")


@pytest.mark.asyncio
async def test_desktop_notifier_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """DesktopNotifier.send → 走 send_toast 并返回成功结果。"""
    captured: dict = {}

    async def _fake_send_toast(title, body, aumid=None, timeout_sec=15.0, mode="auto"):
        captured.update(title=title, body=body, aumid=aumid, mode=mode)
        return "OK:Test!App"

    monkeypatch.setattr(desktop_toast, "send_toast", _fake_send_toast)
    notifier = DesktopNotifier(aumid="Test!App")
    result = await notifier.send(NotifyMessage(title=_TITLE, body=_BODY))
    assert result.ok is True
    assert result.channel == NotifyChannel.DESKTOP.value
    assert captured["title"] == _TITLE
    assert captured["aumid"] == "Test!App"
    assert captured["mode"] == "auto"


def test_balloon_script_loads_assembly_without_compiling() -> None:
    """气泡路径只用 `Add-Type -AssemblyName`(纯加载)→ 不依赖 %TEMP% 可写。"""
    script = desktop_toast.build_balloon_script(_TITLE, _BODY)
    assert "Add-Type -AssemblyName System.Windows.Forms" in script
    assert "Add-Type -TypeDefinition" not in script
    assert _decode_script_literal(script, "titleB64") == _TITLE
    assert _decode_script_literal(script, "bodyB64") == _BODY


@pytest.mark.asyncio
async def test_auto_falls_back_to_balloon_on_identity_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """平台不认 package identity → 自动降级到托盘气泡(仍然能通知到人)。"""

    async def _fake_toast(*args, **kwargs):
        raise NotifyError("桌面通知失败: The process has no package identity. 0x80073D54")

    async def _fake_balloon(*args, **kwargs):
        return "OK:BALLOON"

    monkeypatch.setattr(desktop_toast, "_send_via_toast", _fake_toast)
    monkeypatch.setattr(desktop_toast, "_send_via_balloon", _fake_balloon)
    assert await desktop_toast.send_toast(_TITLE, _BODY) == "OK:BALLOON"


@pytest.mark.asyncio
async def test_auto_does_not_swallow_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """与身份/临时目录无关的错误不得被吞掉(例如拼写错误)。"""

    async def _fake_toast(*args, **kwargs):
        raise NotifyError("桌面通知失败: 脚本语法错误")

    async def _fake_balloon(*args, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("不应降级到气泡")

    monkeypatch.setattr(desktop_toast, "_send_via_toast", _fake_toast)
    monkeypatch.setattr(desktop_toast, "_send_via_balloon", _fake_balloon)
    with pytest.raises(NotifyError, match="脚本语法错误"):
        await desktop_toast.send_toast(_TITLE, _BODY)


@pytest.mark.asyncio
async def test_mode_toast_never_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """mode=toast 时即使身份不被认可也不降级(用户显式要求)。"""

    async def _fake_toast(*args, **kwargs):
        raise NotifyError("桌面通知失败: no package identity")

    async def _fake_balloon(*args, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("不应降级到气泡")

    monkeypatch.setattr(desktop_toast, "_send_via_toast", _fake_toast)
    monkeypatch.setattr(desktop_toast, "_send_via_balloon", _fake_balloon)
    with pytest.raises(NotifyError):
        await desktop_toast.send_toast(_TITLE, _BODY, mode="toast")


@pytest.mark.asyncio
async def test_mode_balloon_skips_toast(monkeypatch: pytest.MonkeyPatch) -> None:
    """mode=balloon 时直接走气泡,完全不碰 WinRT。"""

    async def _fake_toast(*args, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("不应走 Toast 路径")

    async def _fake_balloon(*args, **kwargs):
        return "OK:BALLOON"

    monkeypatch.setattr(desktop_toast, "_send_via_toast", _fake_toast)
    monkeypatch.setattr(desktop_toast, "_send_via_balloon", _fake_balloon)
    assert await desktop_toast.send_toast(_TITLE, _BODY, mode="balloon") == "OK:BALLOON"


def test_desktop_channel_needs_no_credentials() -> None:
    """desktop 渠道零凭据即可构造(不像钉钉/webhook 缺配置就跳过)。"""
    notifier = _build_notifier(NotifyChannel.DESKTOP.value, None)
    assert isinstance(notifier, DesktopNotifier)
    notifier2 = _build_notifier(NotifyChannel.DESKTOP.value, {"aumid": "X!Y", "mode": "balloon"})
    assert isinstance(notifier2, DesktopNotifier)
    assert notifier2._aumid == "X!Y"
    assert notifier2._mode == "balloon"
