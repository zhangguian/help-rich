"""Provider 工厂(backend-arch §9.3 + §11.3.4)

v2.1:Key 从 llm_api_keys 表(加密)取,缺 Key 返回 None(不抛错)。
异步 + 实例缓存。
"""
from app.llm.base import BaseLLM
from app.llm.deepseek import DeepSeekClient
from app.llm.doubao import DoubaoClient
from app.llm.minimax import MiniMaxClient
from app.repositories.llm_keys_repo import llm_keys_repo


class ProviderFactory:
    _instances: dict[str, BaseLLM] = {}

    # value = (ClientClass, model_name_str)
    # model_name 必须显式存字符串,不能访问类 property(类层面访问得到的是 property 对象)
    _BUILDERS = {
        "deepseek": (DeepSeekClient, "deepseek-chat"),
        "minimax": (MiniMaxClient, "MiniMax-M2.5-highspeed"),
        "doubao": (DoubaoClient, "doubao-pro-32k"),
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

        client_cls = cls._BUILDERS[name][0]
        instance = client_cls(key)
        cls._instances[name] = instance
        return instance

    @classmethod
    async def available(cls) -> list[dict]:
        """返回所有 Provider 配置状态(前端设置页用)"""
        status = await llm_keys_repo.list_status()
        return [
            {"name": name, "model": model, "configured": status.get(name, False)}
            for name, (_, model) in cls._BUILDERS.items()
        ]

    @classmethod
    def clear_cache(cls) -> None:
        """清空实例缓存(测试用 / Key 更新后)"""
        cls._instances = {}


provider_factory = ProviderFactory()
