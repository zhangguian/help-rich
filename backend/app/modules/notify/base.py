"""通知渠道抽象(base)

设计原则(2026-10,阶段1):
- **通知永不阻断主流程**:发送失败只记录,不抛给业务方。价格提醒、盘后选股
  这些任务不能因为"钉钉挂了"就失败。
- **渠道可插拔**:新增渠道只需实现 `Notifier` 协议并注册,不改编排逻辑。
- **密钥加密存储**:各渠道 token/webhook 复用 `app.core.crypto` 的 Fernet 加密,
  与 LLM API Key 同一套密钥管理,不落明文。
"""
from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from datetime import datetime


class NotifyChannel(str, enum.Enum):
    """支持的推送渠道。"""

    CONSOLE = "console"      # 本地日志/终端,默认开启,零配置
    DESKTOP = "desktop"      # Windows 原生桌面通知(Toast),零配置
    DINGTALK = "dingtalk"    # 钉钉机器人
    WECOM = "wecom"          # 企业微信机器人
    BARK = "bark"            # Bark(iOS)
    WEBHOOK = "webhook"      # 通用 Webhook(JSON POST)


# 展示名(前端直接用,避免各页面各写一份中文映射)
CHANNEL_LABELS: dict[str, str] = {
    NotifyChannel.CONSOLE.value: "终端日志",
    NotifyChannel.DESKTOP.value: "桌面通知",
    NotifyChannel.DINGTALK.value: "钉钉",
    NotifyChannel.WECOM.value: "企业微信",
    NotifyChannel.BARK.value: "Bark",
    NotifyChannel.WEBHOOK.value: "Webhook",
}


class NotifyLevel(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class NotifyMessage:
    """一条待推送的消息。"""

    title: str
    body: str
    level: NotifyLevel = NotifyLevel.INFO
    # 业务上下文(股票代码、告警 id 等),渠道可用可不用
    context: dict = field(default_factory=dict)
    # 可选跳转链接
    url: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def plain_text(self) -> str:
        """纯文本兜底渲染(不支持富文本的渠道用)。"""
        lines = [self.title, self.body]
        if self.url:
            lines.append(self.url)
        return "\n".join(lines)


@dataclass(slots=True)
class NotifyResult:
    """单渠道发送结果。"""

    channel: str
    ok: bool
    detail: str = ""
    skipped: bool = False  # 被去重/限流跳过,不算失败

    @classmethod
    def success(cls, channel: str, detail: str = "") -> "NotifyResult":
        return cls(channel=channel, ok=True, detail=detail)

    @classmethod
    def failure(cls, channel: str, detail: str) -> "NotifyResult":
        return cls(channel=channel, ok=False, detail=detail)

    @classmethod
    def skip(cls, channel: str, detail: str = "") -> "NotifyResult":
        return cls(channel=channel, ok=True, detail=detail, skipped=True)


class NotifyError(Exception):
    """渠道发送失败(由 service 层捕获,不会冒泡到业务)。"""


class Notifier(abc.ABC):
    """渠道实现协议。"""

    channel: NotifyChannel

    @abc.abstractmethod
    async def send(self, message: NotifyMessage) -> NotifyResult:
        """发送一条消息。实现方应把异常转成 NotifyError。"""
        raise NotImplementedError

    async def test(self) -> NotifyResult:
        """连通性自检(设置页"测试通知"用)。默认发一条测试消息。"""
        return await self.send(
            NotifyMessage(
                title="买股工具室 · 通知测试",
                body=f"{CHANNEL_LABELS.get(self.channel.value, self.channel.value)} 渠道配置成功。",
            )
        )


__all__ = [
    "CHANNEL_LABELS",
    "NotifyChannel",
    "NotifyError",
    "NotifyLevel",
    "NotifyMessage",
    "NotifyResult",
    "Notifier",
]
