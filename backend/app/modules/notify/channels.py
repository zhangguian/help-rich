"""具体通知渠道实现。

全部使用 httpx.AsyncClient + 统一超时,不引入新依赖。
每个渠道一个类,失败一律抛 NotifyError,由 `service.py` 捕获降级。
"""
from __future__ import annotations

import httpx

from app.modules.notify.base import (
    CHANNEL_LABELS,
    NotifyChannel,
    NotifyError,
    NotifyLevel,
    NotifyMessage,
    NotifyResult,
    Notifier,
)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_LEVEL_EMOJI = {
    NotifyLevel.INFO: "ℹ️",
    NotifyLevel.WARNING: "⚠️",
    NotifyLevel.ERROR: "🔴",
}


class _HttpNotifier(Notifier):
    """HTTP 类渠道基类:统一超时与异常转换。"""

    async def _post_json(self, url: str, payload: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
        except httpx.HTTPError as e:
            raise NotifyError(f"{self.channel.value} 请求失败: {e}") from e

        if resp.status_code >= 400:
            raise NotifyError(
                f"{self.channel.value} 返回 {resp.status_code}: {resp.text[:200]}"
            )


class ConsoleNotifier(Notifier):
    """终端日志渠道:零配置兜底,便于本地验证链路。"""

    channel = NotifyChannel.CONSOLE

    async def send(self, message: NotifyMessage) -> NotifyResult:
        from app.core.logging import logger

        logger.info(f"[notify:{self.channel.value}] {message.plain_text()}")
        return NotifyResult.success(self.channel.value, "已写入日志")


class DingTalkNotifier(_HttpNotifier):
    """钉钉群机器人(自定义 webhook + 加签)。"""

    channel = NotifyChannel.DINGTALK

    def __init__(self, webhook: str, secret: str | None = None) -> None:
        self._webhook = webhook
        self._secret = secret

    def _signed_url(self) -> str:
        if not self._secret:
            return self._webhook
        import base64
        import hashlib
        import hmac
        import time
        from urllib.parse import quote

        timestamp = str(round(time.time() * 1000))
        sign_str = f"{timestamp}\n{self._secret}"
        sign = base64.b64encode(
            hmac.new(
                self._secret.encode(), sign_str.encode(), digestmod=hashlib.sha256
            ).digest()
        ).decode()
        sep = "&" if "?" in self._webhook else "?"
        return f"{self._webhook}{sep}timestamp={timestamp}&sign={quote(sign)}"

    def _payload(self, message: NotifyMessage) -> dict:
        emoji = _LEVEL_EMOJI.get(message.level, "")
        text = f"#### {emoji} {message.title}\n\n{message.body}"
        if message.url:
            text += f"\n\n[查看详情]({message.url})"
        return {"msgtype": "markdown", "markdown": {"title": message.title, "text": text}}

    async def send(self, message: NotifyMessage) -> NotifyResult:
        await self._post_json(self._signed_url(), self._payload(message))
        return NotifyResult.success(self.channel.value, "已发送")


class WeComNotifier(_HttpNotifier):
    """企业微信群机器人。"""

    channel = NotifyChannel.WECOM

    def __init__(self, webhook: str) -> None:
        self._webhook = webhook

    def _payload(self, message: NotifyMessage) -> dict:
        emoji = _LEVEL_EMOJI.get(message.level, "")
        content = f"**{emoji} {message.title}**\n{message.body}"
        if message.url:
            content += f"\n[查看详情]({message.url})"
        return {"msgtype": "markdown", "markdown": {"content": content}}

    async def send(self, message: NotifyMessage) -> NotifyResult:
        await self._post_json(self._webhook, self._payload(message))
        return NotifyResult.success(self.channel.value, "已发送")


class BarkNotifier(_HttpNotifier):
    """Bark(iOS 推送,通过 device key 鉴权)。"""

    channel = NotifyChannel.BARK

    def __init__(self, device_key: str, server: str = "https://api.day.app") -> None:
        self._device_key = device_key
        self._server = server.rstrip("/")

    async def send(self, message: NotifyMessage) -> NotifyResult:
        emoji = _LEVEL_EMOJI.get(message.level, "")
        payload = {
            "device_key": self._device_key,
            "title": f"{emoji} {message.title}",
            "body": message.body,
            "group": "买股工具室",
        }
        if message.url:
            payload["url"] = message.url
        await self._post_json(f"{self._server}/push", payload)
        return NotifyResult.success(self.channel.value, "已推送")


class DesktopNotifier(Notifier):
    """Windows 原生桌面通知:零配置,浏览器关着也能收到。

    两条投递路径(见 `app/modules/notify/desktop_toast.py`):
    - `toast`   WinRT 通知中心卡片(现代 Toast)
    - `balloon` Win32 托盘气泡(不需要 package identity,受限环境兜底)
    - `auto`    先 Toast,平台不认身份时自动降级到气泡(默认)

    这里只做 DTO → 调用 → 结果转换。
    """

    channel = NotifyChannel.DESKTOP

    def __init__(self, aumid: str | None = None, mode: str = "auto") -> None:
        self._aumid = aumid
        self._mode = mode or "auto"

    async def send(self, message: NotifyMessage) -> NotifyResult:
        from app.modules.notify.desktop_toast import send_toast

        detail = await send_toast(
            message.title, message.body, self._aumid, mode=self._mode
        )
        return NotifyResult.success(self.channel.value, detail or "已弹出桌面通知")


class WebhookNotifier(_HttpNotifier):
    """通用 Webhook:把消息原样 JSON POST 出去,便于对接自建服务。"""

    channel = NotifyChannel.WEBHOOK

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        self._url = url
        self._headers = headers or {}

    async def send(self, message: NotifyMessage) -> NotifyResult:
        payload = {
            "title": message.title,
            "body": message.body,
            "level": message.level.value,
            "context": message.context,
            "url": message.url,
            "created_at": message.created_at.isoformat(),
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(self._url, json=payload, headers=self._headers)
        except httpx.HTTPError as e:
            raise NotifyError(f"webhook 请求失败: {e}") from e
        if resp.status_code >= 400:
            raise NotifyError(f"webhook 返回 {resp.status_code}: {resp.text[:200]}")
        return NotifyResult.success(self.channel.value, "已发送")


__all__ = [
    "BarkNotifier",
    "CHANNEL_LABELS",
    "ConsoleNotifier",
    "DesktopNotifier",
    "DingTalkNotifier",
    "WeComNotifier",
    "WebhookNotifier",
]
