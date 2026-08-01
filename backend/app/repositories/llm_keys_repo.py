"""LLM API Key 仓储(llm_api_keys 表 CRUD)

v2.1 §11.3
"""
from typing import Optional

from sqlalchemy import select

from app.core.crypto import InvalidToken, decrypt, encrypt
from app.db import async_session
from app.models.orm import LlmApiKey


class LlmKeysRepository:
    async def upsert(self, provider: str, plaintext_key: str) -> LlmApiKey:
        """写入或更新 provider 的 Key(明文传入,自动加密)"""
        encrypted = encrypt(plaintext_key)
        async with async_session() as session:
            existing = await session.get(LlmApiKey, provider)
            if existing:
                existing.encrypted_key = encrypted
                await session.commit()
                await session.refresh(existing)
                return existing
            row = LlmApiKey(provider=provider, encrypted_key=encrypted)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get_decrypted(self, provider: str) -> Optional[str]:
        """返回解密后的 Key

        - 缺 Key 时返回 None(不抛错)
        - 解密失败(FERNET_KEY 变更)时返回 None
        """
        async with async_session() as session:
            row = await session.get(LlmApiKey, provider)
            if row is None:
                return None
            try:
                return decrypt(row.encrypted_key)
            except InvalidToken:
                return None

    async def delete(self, provider: str) -> bool:
        """删除 provider 的 Key"""
        async with async_session() as session:
            row = await session.get(LlmApiKey, provider)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def list_status(self) -> dict[str, bool]:
        """返回 3 个 Provider 的配置状态(已配置/未配置)"""
        async with async_session() as session:
            rows = (await session.execute(select(LlmApiKey.provider))).scalars().all()
            return {
                "deepseek": "deepseek" in rows,
                "minimax": "minimax" in rows,
                "doubao": "doubao" in rows,
            }


llm_keys_repo = LlmKeysRepository()