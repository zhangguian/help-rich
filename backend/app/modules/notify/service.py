"""通知编排服务:渠道路由 + 失败降级 + 多渠道扇出。

调用方只需 `await notify_service.notify(msg, channels=[...])`,
不必关心各渠道的参数与异常 —— 单个渠道失败不影响其它渠道,也不抛给业务。
"""
from __future__ import annotations

from app.core.logging import logger
from app.modules.notify.base import (
    CHANNEL_LABELS,
    NotifyChannel,
    NotifyError,
    NotifyMessage,
    NotifyResult,
    Notifier,
)
from app.modules.notify.channels import (
    BarkNotifier,
    ConsoleNotifier,
    DingTalkNotifier,
    WeComNotifier,
    WebhookNotifier,
)
from app.modules.notify.dedupe import limiter


def _build_notifier(channel: str, config: dict | None) -> Notifier | None:
    """按渠道与配置构造 notifier;配置缺失返回 None(该渠道跳过)。"""
    cfg = config or {}
    try:
        if channel == NotifyChannel.CONSOLE.value:
            return ConsoleNotifier()
        if channel == NotifyChannel.DINGTALK.value:
            webhook = cfg.get("webhook")
            if not webhook:
                return None
            return DingTalkNotifier(webhook=webhook, secret=cfg.get("secret") or None)
        if channel == NotifyChannel.WECOM.value:
            webhook = cfg.get("webhook")
            if not webhook:
                return None
            return WeComNotifier(webhook=webhook)
        if channel == NotifyChannel.BARK.value:
            key = cfg.get("device_key")
            if not key:
                return None
            return BarkNotifier(device_key=key, server=cfg.get("server") or "https://api.day.app")
        if channel == NotifyChannel.WEBHOOK.value:
            url = cfg.get("url")
            if not url:
                return None
            return WebhookNotifier(url=url, headers=cfg.get("headers") or {})
    except Exception as e:  # pragma: no cover - 构造期异常
        logger.warning(f"[notify] 构造渠道 {channel} 失败: {e}")
        return None
    return None


class NotifyService:
    """通知编排。"""

    async def notify(
        self,
        message: NotifyMessage,
        channels: list[str],
        configs: dict[str, dict] | None = None,
    ) -> list[NotifyResult]:
        """向多个渠道扇出,返回每渠道结果(失败不抛)。

        `configs=None` 表示"由本服务自行解密取配置"。跨域调用方(如 alert)
        只需传 None,不必触碰 notify 的 config_repository —— 架构守卫要求
        模块间只能经由 service 交互。
        """
        if configs is None:
            configs = await self._load_configs()
        results: list[NotifyResult] = []
        for ch in channels:
            notifier = _build_notifier(ch, configs.get(ch))
            if notifier is None:
                results.append(NotifyResult.skip(ch, "渠道未配置"))
                continue
            try:
                results.append(await notifier.send(message))
            except NotifyError as e:
                logger.warning(f"[notify] {CHANNEL_LABELS.get(ch, ch)} 发送失败: {e}")
                results.append(NotifyResult.failure(ch, str(e)))
            except Exception as e:  # pragma: no cover - 兜底,绝不冒泡
                logger.warning(f"[notify] {ch} 未知异常: {e}")
                results.append(NotifyResult.failure(ch, str(e)))
        return results

    async def enabled_channels(self) -> list[str]:
        """返回用户已启用的渠道名(按配置顺序)。读不到配置时返回空。"""
        from app.modules.notify.config_repository import notify_config_repo

        try:
            rows = await notify_config_repo.list_all()
        except Exception as e:  # noqa: BLE001 — 配置读不到按"未启用"处理
            logger.warning(f"[notify] 读取渠道列表失败: {e}")
            return []
        return [r.channel for r in rows if r.enabled]

    async def send_to_enabled(self, message: NotifyMessage) -> list[NotifyResult]:
        """推送到全部已启用渠道。跨域调用方(如 workflow)用这一个方法即可。"""
        channels = await self.enabled_channels()
        if not channels:
            return []
        return await self.notify(message, channels)

    async def _load_configs(self) -> dict[str, dict]:
        """解密读取全部渠道配置(本模块私有,不外泄)。"""
        from app.modules.notify.config_repository import notify_config_repo

        try:
            return await notify_config_repo.get_all_decrypted()
        except Exception as e:  # noqa: BLE001 — 配置读不到不该让提醒整条链路崩掉
            logger.warning(f"[notify] 读取渠道配置失败,按未配置处理: {e}")
            return {}

    async def notify_with_limit(
        self,
        message: NotifyMessage,
        channels: list[str],
        configs: dict[str, dict] | None = None,
        alert_key: str = "",
        fingerprint: str = "",
        cooldown_sec: int = 1800,
        daily_limit: int = 5,
    ) -> list[NotifyResult] | None:
        """带去重/限流的发送。被限流时返回 None(调用方无需发任何东西)。"""
        if alert_key:
            ok, reason = limiter.allow(alert_key, fingerprint, cooldown_sec, daily_limit)
            if not ok:
                logger.debug(f"[notify] {alert_key} 被限流: {reason}")
                return None
        return await self.notify(message, channels, configs)


notify_service = NotifyService()

# 跨域契约:其他模块(如 alert)只允许 import `app.modules.notify.service`,
# 因此消息 DTO 与等级枚举必须从这里再导出,而不是让调用方去碰 base/channels。
from app.modules.notify.base import (  # noqa: E402
    CHANNEL_LABELS,
    NotifyChannel,
    NotifyError,
    NotifyLevel,
    NotifyMessage,
    NotifyResult,
    Notifier,
)

__all__ = [
    "CHANNEL_LABELS",
    "Notifier",
    "NotifyChannel",
    "NotifyError",
    "NotifyLevel",
    "NotifyMessage",
    "NotifyResult",
    "NotifyService",
    "notify_service",
]
