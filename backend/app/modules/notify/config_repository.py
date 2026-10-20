"""通知渠道配置持久化(仓储层)。

凭据加密存储:webhook / device_key / url 等敏感信息用 Fernet 加密后落库,
读取时解密;对外只暴露 config_hint(如 webhook 的域名)供前端辨认。
"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.core.crypto import InvalidToken, decrypt, encrypt
from app.db import async_session
from app.models.orm import NotifyChannelConfig


class NotifyConfigRepo:
    async def list_all(self) -> list[NotifyChannelConfig]:
        async with async_session() as s:
            stmt = select(NotifyChannelConfig).order_by(NotifyChannelConfig.channel)
            return list((await s.execute(stmt)).scalars().all())

    async def get(self, channel: str) -> NotifyChannelConfig | None:
        async with async_session() as s:
            return await s.get(NotifyChannelConfig, channel)

    async def get_decrypted_config(self, channel: str) -> dict:
        """解密某渠道凭据;未配置或解密失败返回 {}。"""
        row = await self.get(channel)
        if row is None or not row.config_encrypted:
            return {}
        try:
            return json.loads(decrypt(row.config_encrypted))
        except (InvalidToken, ValueError, json.JSONDecodeError):
            return {}

    async def get_all_decrypted(self) -> dict[str, dict]:
        """所有已配置渠道的明文凭据(供 service 扇出用)。"""
        out: dict[str, dict] = {}
        for row in await self.list_all():
            if row.config_encrypted:
                try:
                    out[row.channel] = json.loads(decrypt(row.config_encrypted))
                except (InvalidToken, ValueError, json.JSONDecodeError):
                    out[row.channel] = {}
        return out

    async def upsert(
        self,
        channel: str,
        enabled: bool,
        config: dict | None,
        hint: str | None = None,
    ) -> None:
        """保存/更新渠道配置。config 为 None 表示只改 enabled,保留原凭据。"""
        from datetime import datetime

        encrypted = encrypt(json.dumps(config, ensure_ascii=False)) if config is not None else None
        async with async_session() as s:
            row = await s.get(NotifyChannelConfig, channel)
            if row is None:
                row = NotifyChannelConfig(
                    channel=channel,
                    enabled=enabled,
                    config_encrypted=encrypted,
                    config_hint=hint,
                )
                s.add(row)
            else:
                row.enabled = enabled
                if config is not None:
                    row.config_encrypted = encrypted
                if hint is not None:
                    row.config_hint = hint
                row.updated_at = datetime.now()
            await s.commit()

    async def record_result(self, channel: str, ok: bool, error: str | None = None) -> None:
        from datetime import datetime

        async with async_session() as s:
            row = await s.get(NotifyChannelConfig, channel)
            if row is None:
                return
            row.last_ok_at = datetime.now() if ok else row.last_ok_at
            row.last_error = None if ok else (error or "")[:500]
            await s.commit()


notify_config_repo = NotifyConfigRepo()

__all__ = ["NotifyConfigRepo", "notify_config_repo"]
