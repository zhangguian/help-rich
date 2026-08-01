"""MiniMax 客户端(backend-arch §9.2 / P4.2b + 多模态 P8.x)

自有 API(v1/text/chatcompletion_v2),消息体与 OpenAI 兼容。

视觉模型:
- abab-v-chat(默认视觉模型)
- 多模态 messages:`content` 是数组,元素为 {type:text} 或 {type:image_url, image_url:{url:data:...}}
"""
import asyncio
import logging
from typing import Any

import httpx

from app.llm.base import BACKOFF_BASE, BaseLLM, LLMError

logger = logging.getLogger(__name__)


class MiniMaxClient(BaseLLM):
    """MiniMax abab6.5s/abab-v chat API 客户端"""

    name = "minimax"
    _model = "abab6.5s-chat"
    BASE_URL = "https://api.minimax.chat/v1/text/chatcompletion_v2"
    provider_label = "MiniMax"

    # 视觉模型(MiniMax 多模态)
    VISION_MODEL = "abab-v-chat"

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def supports_vision(self) -> bool:
        return True

    async def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> str:
        """纯文本 chat(走当前 _model)"""
        last_err: Exception | None = None
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

                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = LLMError(
                        f"{self.provider_label} HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue

                raise LLMError(
                    f"{self.provider_label} HTTP {resp.status_code}: {resp.text[:200]}"
                )

        raise LLMError(f"{self.provider_label} 重试 {max_retries} 次仍失败: {last_err}")

    async def chat_with_image(
        self,
        system: str,
        user_prompt: str,
        image_data_url: str,
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> str:
        """多模态 chat:文本 + 图片(base64 data URL)

        messages content 是混合数组,OpenAI 兼容格式。
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url},
                    },
                ],
            },
        ]

        last_err: Exception | None = None
        async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
            for attempt in range(max_retries):
                try:
                    resp = await client.post(
                        self.BASE_URL,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.VISION_MODEL,
                            "messages": messages,
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
                        raise LLMError(
                            f"{self.provider_label} 视觉响应格式异常: {e}"
                        ) from e

                if resp.status_code in (429, 500, 502, 503, 504):
                    last_err = LLMError(
                        f"{self.provider_label} Vision HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue

                raise LLMError(
                    f"{self.provider_label} Vision HTTP {resp.status_code}: {resp.text[:200]}"
                )

        raise LLMError(
            f"{self.provider_label} Vision 重试 {max_retries} 次仍失败: {last_err}"
        )