"""LLM 设置仓储(llm_settings 单行表)"""
from sqlalchemy import select

from app.db import async_session
from app.models.orm import LlmSettings


class LlmSettingsRepository:
    async def get_active(self) -> str:
        """获取当前激活 provider,默认 deepseek"""
        async with async_session() as session:
            row = await session.get(LlmSettings, 1)
            if row is None:
                # 首次访问:插入默认值
                row = LlmSettings(id=1, active_provider="deepseek")
                session.add(row)
                await session.commit()
                return "deepseek"
            return row.active_provider

    async def set_active(self, provider: str) -> str:
        """切换激活 provider"""
        async with async_session() as session:
            row = await session.get(LlmSettings, 1)
            if row is None:
                row = LlmSettings(id=1, active_provider=provider)
                session.add(row)
            else:
                row.active_provider = provider
            await session.commit()
            return provider


llm_settings_repo = LlmSettingsRepository()