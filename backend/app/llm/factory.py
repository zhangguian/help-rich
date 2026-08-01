"""Provider 工厂(backend-arch §9.3 + §11.3.4)

v2.1:Key 从 llm_api_keys 表(加密)取,缺 Key 返回 None(不抛错)。
异步 + 实例缓存。
"""
from app.llm.base import BaseLLM
from app.llm.deepseek import DeepSeekClient
from app.repositories.llm_keys_repo import llm_keys_repo


class ProviderFactory:
    _instances: dict[str, BaseLLM] = {}

    _BUILDERS = {
        "deepseek": DeepSeekClient,
        # P4.2b / P4.2c:minimax / doubao 客户端
    }

    @classmethod
    async def get(cls, name: str) -> BaseLLM | None:
        """获取 Provider 实例;缺 Key / 未知 Provider 返回 None"""
        if name in cls._instances:
            return cls._instances[name]
        if name not in cls._BUILDERS:
            return None

        key = await llm_keys_repo.get_decrypted(name)
        if key is None:
            return None

        instance = cls._BUILDERS[name](key)
        cls._instances[name] = instance
        return instance

    @classmethod
    async def available(cls) -> list[dict]:
        """返回所有 Provider 配置状态(前端设置页用)"""
        status = await llm_keys_repo.list_status()
        return [
            {"name": name, "model": builder.model_name, "configured": status.get(name, False)}
            for name, builder in cls._BUILDERS.items()
        ]

    @classmethod
    def clear_cache(cls) -> None:
        """清空实例缓存(测试用 / Key 更新后)"""
        cls._instances = {}


provider_factory = ProviderFactory()
