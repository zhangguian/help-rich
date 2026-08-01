"""DeepSeek 客户端(backend-arch §9.2)

OpenAI 兼容接口:
- POST https://api.deepseek.com/v1/chat/completions
- 3 次指数退避(2s / 4s / 8s)
"""
import asyncio
import logging

import httpx

from app.llm.base import BaseLLM, LLMError

logger = logging.getLogger(__name__)

# 指数退避基础秒数:重试 1/2/3 次分别等待 2s/4s/8s
BACKOFF_BASE = 2.0


class DeepSeekClient(BaseLLM):
    """DeepSeek chat API 客户端"""

    name = "deepseek"
    _model = "deepseek-chat"
    BASE_URL = "https://api.deepseek.com/v1/chat/completions"

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
                        raise LLMError(f"DeepSeek 响应格式异常: {e}") from e

                # 限流/服务端错误可重试
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = LLMError(
                        f"DeepSeek HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue

                # 其他错误(401 无效 Key 等)不重试
                raise LLMError(
                    f"DeepSeek HTTP {resp.status_code}: {resp.text[:200]}"
                )

        raise LLMError(f"DeepSeek 重试 {max_retries} 次仍失败: {last_err}")
