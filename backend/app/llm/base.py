"""LLM Provider 抽象基类(backend-arch §9.1)

所有 Provider(DeepSeek / MiniMax / 豆包)共享:
- chat(system, user, temperature, max_retries):指数退避重试
- model_name:模型名(用于 A/B 标签)
"""
from abc import ABC, abstractmethod


class BaseLLM(ABC):
    """LLM 客户端抽象

    name: 'deepseek' / 'minimax' / 'doubao'
    """

    name: str = ""

    @abstractmethod
    async def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> str:
        """发送对话,返回回复文本

        Raises:
            LLMError: 重试耗尽仍失败
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError


class LLMError(Exception):
    """LLM 调用失败(重试耗尽)"""
