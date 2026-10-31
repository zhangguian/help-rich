"""盘中信号服务(编排:去重 → 通知 → 落库 → 广播)。

**职责边界**:判定在 `engine.py`(纯函数),持久化在 `repository.py`,
本模块只做编排。任何一步失败都**不冒泡**到盯盘主流程。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.core.logging import logger
from app.modules.notify.service import (
    NotifyChannel,
    NotifyLevel,
    NotifyMessage,
    notify_service,
)
from app.modules.signal.engine import Signal
from app.modules.signal.repository import (
    DEFAULT_CHANNELS,
    signal_config_repo,
    signal_trigger_repo,
)
from app.services.event_bus import event_bus

# 事件名(前端 SSE 按事件名过滤)
EVENT_SIGNAL_FIRED = "signal_fired"


@dataclass(slots=True)
class SignalConfig:
    """盘中信号配置(判定层只读这里的值)。"""

    enabled: bool = True
    velocity_window_sec: int = 60
    velocity_pct: float = 1.5
    breakout_up_pct: float = 5.0
    breakout_down_pct: float = -5.0
    enable_velocity: bool = True
    enable_breakout: bool = True
    enable_t_point: bool = True
    enable_buy_point: bool = True
    cooldown_sec: int = 600
    daily_limit: int = 5
    channels: list[str] = field(default_factory=lambda: list(DEFAULT_CHANNELS))

    @classmethod
    def from_row(cls, row) -> SignalConfig:
        channels: list[str] = []
        if getattr(row, "channels_json", None):
            try:
                parsed = json.loads(row.channels_json)
                if isinstance(parsed, list):
                    channels = [str(c) for c in parsed if c]
            except (json.JSONDecodeError, TypeError):
                channels = []
        if not channels:
            channels = list(DEFAULT_CHANNELS)
        return cls(
            enabled=bool(row.enabled),
            velocity_window_sec=int(row.velocity_window_sec),
            velocity_pct=float(row.velocity_pct),
            breakout_up_pct=float(row.breakout_up_pct),
            breakout_down_pct=float(row.breakout_down_pct),
            enable_velocity=bool(row.enable_velocity),
            enable_breakout=bool(row.enable_breakout),
            enable_t_point=bool(row.enable_t_point),
            enable_buy_point=bool(row.enable_buy_point),
            cooldown_sec=int(row.cooldown_sec),
            daily_limit=int(row.daily_limit),
            channels=channels,
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "velocity_window_sec": self.velocity_window_sec,
            "velocity_pct": self.velocity_pct,
            "breakout_up_pct": self.breakout_up_pct,
            "breakout_down_pct": self.breakout_down_pct,
            "enable_velocity": self.enable_velocity,
            "enable_breakout": self.enable_breakout,
            "enable_t_point": self.enable_t_point,
            "enable_buy_point": self.enable_buy_point,
            "cooldown_sec": self.cooldown_sec,
            "daily_limit": self.daily_limit,
            "channels": list(self.channels),
        }


class SignalService:
    """盘中信号用例层。"""

    # ---------- 配置 ----------

    async def get_config(self) -> SignalConfig:
        try:
            row = await signal_config_repo.get()
        except Exception as e:  # noqa: BLE001 — 配置读不到就按默认值跑
            logger.warning("[signal] 读取配置失败,按默认值: {}", e)
            return SignalConfig()
        return SignalConfig.from_row(row)

    async def update_config(self, **kwargs) -> SignalConfig:
        payload = dict(kwargs)
        if "channels" in payload:
            channels = payload.pop("channels") or []
            payload["channels_json"] = json.dumps(list(channels), ensure_ascii=False)
        row = await signal_config_repo.update(**payload)
        return SignalConfig.from_row(row)

    # ---------- 流水 ----------

    async def list_triggers(self, stock_code: str | None = None, limit: int = 50) -> list[dict]:
        rows = await signal_trigger_repo.list(stock_code=stock_code, limit=limit)
        return [
            {
                "id": r.id,
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "kind": r.kind,
                "level": r.level,
                "value": r.value,
                "title": r.title,
                "body": r.body,
                "fingerprint": r.fingerprint,
                "notified": r.notified,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    # ---------- 触发 ----------

    async def fire(self, signal: Signal, cfg: SignalConfig) -> bool:
        """推送一条信号。返回是否**真的送达**(落库 + 广播)。"""
        try:
            # 1) 跨重启去重:到价类按"同价位当日一次"查流水表
            if signal.dedup_by_level and await signal_trigger_repo.fingerprint_notified_today(
                signal.stock_code, signal.fingerprint
            ):
                logger.debug("[signal] 同价位今日已提醒,跳过: {}", signal.fingerprint)
                return False

            # 2) 冷却 + 日限流(内存限流器;到价类的跨重启去重靠上面的流水表)
            results = await notify_service.notify_with_limit(
                NotifyMessage(
                    title=signal.title,
                    body=signal.body,
                    level=NotifyLevel.INFO,
                    context={
                        "stock_code": signal.stock_code,
                        "kind": signal.kind,
                        "level": signal.level,
                    },
                ),
                channels=list(cfg.channels),
                configs=None,  # 由 notify 自行解密取配置,本模块不碰它的仓储
                alert_key=f"signal:{signal.stock_code}:{signal.kind}",
                fingerprint=signal.fingerprint,
                cooldown_sec=cfg.cooldown_sec,
                daily_limit=cfg.daily_limit,
            )

            if results is None:
                # 被冷却/日限流:记一笔 skipped,前端能解释"为什么没推"
                await signal_trigger_repo.record(
                    stock_code=signal.stock_code,
                    stock_name=signal.stock_name,
                    kind=signal.kind,
                    title=signal.title,
                    body=signal.body,
                    fingerprint=signal.fingerprint,
                    notified=False,
                    level=signal.level,
                    value=signal.value,
                    error="被冷却或已达当日上限",
                )
                return False

            ok = any(r.ok for r in results)
            failures = "; ".join(
                f"{r.channel}: {r.detail}" for r in results if not r.ok and r.detail
            )
            trigger_id = await signal_trigger_repo.record(
                stock_code=signal.stock_code,
                stock_name=signal.stock_name,
                kind=signal.kind,
                title=signal.title,
                body=signal.body,
                fingerprint=signal.fingerprint,
                notified=ok,
                level=signal.level,
                value=signal.value,
                error=failures or None,
            )

            if ok:
                await event_bus.publish(
                    {
                        "event": EVENT_SIGNAL_FIRED,
                        "signal": {
                            "id": trigger_id,
                            "kind": signal.kind,
                            "stock_code": signal.stock_code,
                            "stock_name": signal.stock_name,
                            "level": signal.level,
                            "value": signal.value,
                            "title": signal.title,
                            "body": signal.body,
                        },
                    }
                )
            return ok
        except Exception as e:  # noqa: BLE001 — 通知失败绝不冒泡到盯盘主流程
            logger.warning("[signal] 信号 {} 推送异常: {}", signal.kind, e)
            return False

    # ---------- 自检 ----------

    async def test_desktop_notification(self) -> dict:
        """真弹一条桌面通知(设置页「测试」按钮用)。"""
        message = NotifyMessage(
            title="买股工具室 · 盘中信号测试",
            body="桌面通知通道已连通。盘中出现急速拉升/下跌、突破、做T点、买点时会从这里弹。",
            level=NotifyLevel.INFO,
            context={"kind": "test"},
        )
        results = await notify_service.notify(
            message, channels=[NotifyChannel.DESKTOP.value], configs=None
        )
        ok = any(r.ok for r in results)
        detail = "; ".join(f"{r.channel}: {r.detail}" for r in results)
        return {"ok": ok, "detail": detail}


signal_service = SignalService()

__all__ = [
    "EVENT_SIGNAL_FIRED",
    "SignalConfig",
    "SignalService",
    "signal_service",
]
