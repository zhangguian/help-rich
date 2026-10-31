"""盘中信号持久化(仓储层)。

两张表:
- `intraday_signal_config` : 单行配置(id=1);缺行时 `get()` 自动补一行默认值
- `intraday_signal_trigger`: 触发流水;`fingerprint` 用于**跨重启**去重
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select

from app.db import async_session
from app.models.orm import IntradaySignalConfig, IntradaySignalTrigger

# 默认投递渠道(桌面通知零凭据,开箱即用)
DEFAULT_CHANNELS = ["desktop"]


class SignalConfigRepo:
    """盘中信号配置仓储。"""

    async def get(self) -> IntradaySignalConfig:
        """读配置;缺行则补一行默认值(单行设置范式)。"""
        async with async_session() as s:
            row = await s.get(IntradaySignalConfig, 1)
            if row is None:
                row = IntradaySignalConfig(
                    id=1,
                    channels_json=json.dumps(DEFAULT_CHANNELS, ensure_ascii=False),
                )
                s.add(row)
                await s.commit()
                await s.refresh(row)
            return row

    async def update(self, **kwargs) -> IntradaySignalConfig:
        """按字段更新配置(只允许白名单字段,防注入)。"""
        allowed = {
            "enabled",
            "velocity_window_sec",
            "velocity_pct",
            "breakout_up_pct",
            "breakout_down_pct",
            "enable_velocity",
            "enable_breakout",
            "enable_t_point",
            "enable_buy_point",
            "cooldown_sec",
            "daily_limit",
            "channels_json",
        }
        async with async_session() as s:
            row = await s.get(IntradaySignalConfig, 1)
            if row is None:
                row = IntradaySignalConfig(
                    id=1, channels_json=json.dumps(DEFAULT_CHANNELS, ensure_ascii=False)
                )
                s.add(row)
            for key, value in kwargs.items():
                if key in allowed:
                    setattr(row, key, value)
            row.updated_at = datetime.now()
            await s.commit()
            await s.refresh(row)
            return row


class SignalTriggerRepo:
    """触发流水仓储。"""

    async def record(
        self,
        *,
        stock_code: str,
        kind: str,
        title: str,
        body: str,
        fingerprint: str,
        notified: bool,
        stock_name: str | None = None,
        level: float | None = None,
        value: float | None = None,
        error: str | None = None,
    ) -> int:
        async with async_session() as s:
            row = IntradaySignalTrigger(
                stock_code=stock_code,
                stock_name=stock_name,
                kind=kind,
                level=level,
                value=value,
                title=title,
                body=body,
                fingerprint=fingerprint,
                notified=notified,
                error=error,
                created_at=datetime.now(),
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return row.id

    async def list(
        self, stock_code: str | None = None, limit: int = 50
    ) -> list[IntradaySignalTrigger]:
        async with async_session() as s:
            stmt = select(IntradaySignalTrigger)
            if stock_code:
                stmt = stmt.where(IntradaySignalTrigger.stock_code == stock_code)
            stmt = stmt.order_by(IntradaySignalTrigger.id.desc()).limit(limit)
            return list((await s.execute(stmt)).scalars().all())

    async def fingerprint_notified_today(
        self, stock_code: str, fingerprint: str, now: datetime | None = None
    ) -> bool:
        """该指纹今天是否**已经成功推送过**(跨重启去重的依据)。

        只认 `notified=True` 的行 —— 发送失败/被限流的行不阻断后续重试
        (冷却窗口本身已经防住了刷屏)。
        """
        now = now or datetime.now()
        day_start = datetime(now.year, now.month, now.day)
        async with async_session() as s:
            stmt = (
                select(IntradaySignalTrigger.id)
                .where(IntradaySignalTrigger.stock_code == stock_code)
                .where(IntradaySignalTrigger.fingerprint == fingerprint)
                .where(IntradaySignalTrigger.notified.is_(True))
                .where(IntradaySignalTrigger.created_at >= day_start)
                .limit(1)
            )
            return (await s.execute(stmt)).first() is not None


signal_config_repo = SignalConfigRepo()
signal_trigger_repo = SignalTriggerRepo()

__all__ = [
    "DEFAULT_CHANNELS",
    "SignalConfigRepo",
    "SignalTriggerRepo",
    "signal_config_repo",
    "signal_trigger_repo",
]
