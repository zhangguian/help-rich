"""LLM Provider 抽象基类(backend-arch §9.1)

所有 Provider(DeepSeek / MiniMax / 豆包)共享:
- chat(system, user, temperature, max_retries):指数退避重试
- model_name:模型名(用于 A/B 标签)
"""
import asyncio
import logging
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)

# 指数退避基础秒数:重试 1/2/3 次分别等待 2s/4s/8s
BACKOFF_BASE = 2.0


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


class OpenAICompatClient(BaseLLM):
    """OpenAI 兼容 chat API 通用实现(DeepSeek / MiniMax / 豆包共用)

    三家请求体均为 `{model, messages:[{role,content}...], temperature}`,
    响应均为 `{choices:[{message:{content}}]}`。子类只需声明:
    - name / _model / BASE_URL / provider_label(错误信息前缀)
    """

    name: str = ""
    _model: str = ""
    BASE_URL: str = ""
    provider_label: str = "OpenAICompat"

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def model_name(self) -> str:
        return self._model

    async def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> str:
        last_err: Exception | None = None
        # trust_env=False:避免系统代理干扰(公司网络下 TSL 断连,ADR-0005 同因)
        async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
            for attempt in range(max_retries):
                try:
                    resp = await client.post(
                        self.BASE_URL,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._model,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                            "temperature": temperature,
                        },
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    last_err = e
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue

                if resp.status_code == 200:
                    data = resp.json()
                    try:
                        return data["choices"][0]["message"]["content"].strip()
                    except (KeyError, IndexError, TypeError) as e:
                        raise LLMError(f"{self.provider_label} 响应格式异常: {e}") from e

                # 限流/服务端错误可重试
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = LLMError(
                        f"{self.provider_label} HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue

                # 其他错误(401 无效 Key 等)不重试
                raise LLMError(
                    f"{self.provider_label} HTTP {resp.status_code}: {resp.text[:200]}"
                )

        raise LLMError(f"{self.provider_label} 重试 {max_retries} 次仍失败: {last_err}")


class LLMError(Exception):
    """LLM 调用失败(重试耗尽)"""
