"""MiniMax 客户端(backend-arch §9.2 / P4.2b + 多模态 P8.x)

v0.4.4 迁移至新平台 minimaxi.com(OpenAI 兼容端点),适配 Token Plan 订阅 Key:
- 端点: https://api.minimaxi.com/v1/chat/completions
- 文本模型: MiniMax-M2.5-highspeed(M2.x 思考不可关闭,`reasoning_split` 把思考分离到 reasoning_content)
- 视觉模型: MiniMax-M3(支持图片输入)
"""
import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.llm.base import BACKOFF_BASE, BaseLLM, LLMError, ThinkStripper

logger = logging.getLogger(__name__)

_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """剥除 content 中的 <think>…</think> 块(双保险:即使 reasoning_split 失效也不污染解析)"""
    return _THINK_PATTERN.sub("", text).strip()


class MiniMaxClient(BaseLLM):
    """MiniMax M2.5-highspeed / M3 chat API 客户端(新平台 minimaxi.com)"""

    name = "minimax"
    _model = "MiniMax-M2.5-highspeed"
    BASE_URL = "https://api.minimaxi.com/v1/chat/completions"
    provider_label = "MiniMax"

    # 视觉模型(MiniMax-M3 多模态)
    VISION_MODEL = "MiniMax-M3"

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
        return await self.chat_with_messages(
            system, [{"role": "user", "content": user}], temperature, max_retries
        )

    async def chat_with_messages(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> str:
        """纯文本 chat(走当前 _model,支持多轮 messages)"""
        last_err: Exception | None = None
        payload_messages = [{"role": "system", "content": system}, *messages]
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
                            "messages": payload_messages,
                            "temperature": temperature,
                            "reasoning_split": True,
                        },
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    last_err = e
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue

                if resp.status_code == 200:
                    data = resp.json()
                    base = data.get("base_resp") or {}
                    if base.get("status_code"):
                        raise LLMError(
                            f"{self.provider_label} 响应错误({base.get('status_code')}): "
                            f"{base.get('status_msg') or '未知'}"
                        )
                    choices = data.get("choices")
                    if not choices:
                        raise LLMError(f"{self.provider_label} 响应格式异常: choices 为空")
                    try:
                        content = choices[0]["message"]["content"]
                        return strip_think(content or "").strip()
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

    def chat_stream(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        return self.chat_stream_with_messages(
            system, [{"role": "user", "content": user}], temperature
        )

    def chat_stream_with_messages(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """MiniMax 流式(reasoning_split 分离思考 + base_resp 错误检查,支持多轮 messages)"""
        return self._chat_stream_with_messages_impl(system, messages, temperature)

    async def _chat_stream_with_messages_impl(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> AsyncIterator[str]:
        stripper = ThinkStripper()
        async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
            async with client.stream(
                "POST",
                self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [{"role": "system", "content": system}, *messages],
                    "temperature": temperature,
                    "reasoning_split": True,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", errors="replace")
                    raise LLMError(
                        f"{self.provider_label} HTTP {resp.status_code}: {body[:200]}"
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    base = chunk.get("base_resp") or {}
                    if base.get("status_code"):
                        raise LLMError(
                            f"{self.provider_label} 响应错误({base.get('status_code')}): "
                            f"{base.get('status_msg') or '未知'}"
                        )
                    try:
                        delta = chunk["choices"][0]["delta"]
                    except (KeyError, IndexError, TypeError):
                        continue
                    piece = delta.get("content") or ""
                    if piece:
                        text = stripper.feed(piece)
                        if text:
                            yield text
        rest = stripper.feed("")
        if rest:
            yield rest

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
                            "reasoning_split": True,
                        },
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as e:
                    last_err = e
                    await asyncio.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue

                if resp.status_code == 200:
                    data = resp.json()
                    base = data.get("base_resp") or {}
                    if base.get("status_code"):
                        raise LLMError(
                            f"{self.provider_label} 视觉响应错误({base.get('status_code')}): "
                            f"{base.get('status_msg') or '未知'}"
                        )
                    choices = data.get("choices")
                    if not choices:
                        raise LLMError(f"{self.provider_label} 视觉响应格式异常: choices 为空")
                    try:
                        content = choices[0]["message"]["content"]
                        return strip_think(content or "").strip()
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