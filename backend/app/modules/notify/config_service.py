"""通知渠道配置用例层(阶段1)。

把「凭据加解密 + 渠道构造 + 连通性测试」收敛在 service,
让 `api/notify.py` 只做 HTTP 映射,不直接碰 repository
(见 tests/test_architecture_boundaries.py 的 api → repositories 规则)。
"""
from __future__ import annotations

from urllib.parse import urlparse

from app.core.logging import logger
from app.modules.notify.config_repository import notify_config_repo
from app.modules.notify.base import CHANNEL_LABELS, NotifyChannel
from app.modules.notify.channels import (
    BarkNotifier,
    ConsoleNotifier,
    DesktopNotifier,
    DingTalkNotifier,
    WeComNotifier,
    WebhookNotifier,
)
from app.modules.notify.service import notify_service


def _hint_for(channel: str, config: dict) -> str | None:
    """生成不泄密的展示提示(如 webhook 只显示域名)。"""
    url = config.get("webhook") or config.get("url") or ""
    if url:
        try:
            netloc = urlparse(url).netloc
            return f"{netloc}/…" if netloc else "已配置"
        except ValueError:
            return "已配置"
    if config.get("device_key"):
        return f"device_key: {str(config['device_key'])[:6]}…"
    return "已配置" if config else None


class NotifyConfigService:
    """渠道配置 CRUD 与连通性测试。"""

    async def list_channels(self) -> list[dict]:
        rows = await notify_config_repo.list_all()
        known = {r.channel: r for r in rows}
        items = []
        for ch in NotifyChannel:
            row = known.get(ch.value)
            items.append(
                {
                    "channel": ch.value,
                    "label": CHANNEL_LABELS.get(ch.value, ch.value),
                    # console 默认启用,其余默认关闭
                    "enabled": bool(row.enabled) if row else (ch is NotifyChannel.CONSOLE),
                    "configured": bool(row.config_encrypted) if row else False,
                    "hint": row.config_hint if row else None,
                    "last_ok_at": (
                        row.last_ok_at.isoformat() if row and row.last_ok_at else None
                    ),
                    "last_error": row.last_error if row else None,
                }
            )
        return items

    async def save_channel(self, channel: str, enabled: bool, config: dict) -> dict:
        await notify_config_repo.upsert(
            channel=channel,
            enabled=enabled,
            config=config or None,
            hint=_hint_for(channel, config),
        )
        return {"ok": True}

    async def test_channel(self, channel: str) -> dict:
        """发一条测试消息;失败记入 last_error 并把原因带回给调用方。"""
        config = await notify_config_repo.get_decrypted_config(channel)

        if channel == NotifyChannel.DESKTOP.value:
            # 桌面通知零凭据(可选用 aumid / mode 指定借用哪个应用与投递方式)
            desktop_cfg = config or {}
            notifier = DesktopNotifier(
                aumid=desktop_cfg.get("aumid"),
                mode=desktop_cfg.get("mode") or "auto",
            )
        elif channel == NotifyChannel.CONSOLE.value:
            notifier = ConsoleNotifier()
        elif not config:
            raise ValueError("渠道尚未配置")
        elif channel == NotifyChannel.DINGTALK.value:
            notifier = DingTalkNotifier(
                webhook=config.get("webhook", ""), secret=config.get("secret")
            )
        elif channel == NotifyChannel.WECOM.value:
            notifier = WeComNotifier(webhook=config.get("webhook", ""))
        elif channel == NotifyChannel.BARK.value:
            notifier = BarkNotifier(device_key=config.get("device_key", ""))
        elif channel == NotifyChannel.WEBHOOK.value:
            notifier = WebhookNotifier(url=config.get("url", ""))
        else:
            raise ValueError(f"未知渠道: {channel}")

        try:
            result = await notifier.test()
        except Exception as e:  # noqa: BLE001 — 统一转成可展示的错误
            await notify_config_repo.record_result(channel, ok=False, error=str(e))
            logger.warning(f"[notify] {channel} 测试失败: {e}")
            raise RuntimeError(f"测试失败: {e}") from e

        await notify_config_repo.record_result(channel, ok=result.ok, error=result.detail)
        return {"ok": result.ok, "detail": result.detail}


notify_config_service = NotifyConfigService()

__all__ = ["NotifyConfigService", "notify_config_service"]
