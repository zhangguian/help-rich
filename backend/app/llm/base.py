"""LLM Provider 抽象基类(backend-arch §9.1)

所有 Provider(DeepSeek / MiniMax / 豆包)共享:
- chat(system, user, temperature, max_retries):指数退避重试
- model_name:模型名(用于 A/B 标签)
"""
import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# 指数退避基础秒数:重试 1/2/3 次分别等待 2s/4s/8s
BACKOFF_BASE = 2.0


class ThinkStripper:
    """增量剥除 <think>…</think> 块(流式分片时标签可能跨 chunk)

    reasoning_split 失效时的双保险;非流式场景直接用全局 strip_think。
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, text: str) -> str:
        """喂入新文本,返回可安全输出的内容(思考内容被丢弃)"""
        self._buf += text
        out = ""
        while True:
            if self._in_think:
                idx = self._buf.find(self._CLOSE)
                if idx == -1:
                    return out  # 思考未结束,全部丢弃
                self._in_think = False
                self._buf = self._buf[idx + len(self._CLOSE) :]
                continue
            idx = self._buf.find(self._OPEN)
            if idx == -1:
                out += self._buf
                self._buf = ""
                return out
            out += self._buf[:idx]
            self._in_think = True
            self._buf = self._buf[idx + len(self._OPEN) :]


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

    @abstractmethod
    async def chat_with_messages(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> str:
        """多轮对话:system 单独传入,messages 是 [{role,content}] 列表(不含 system)

        用于股票问答多轮上下文(切换股票缓存的历史问答随 messages 注入)。
        """
        raise NotImplementedError

    @abstractmethod
    def chat_stream(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """流式对话:逐段产出回复文本增量(不含思考内容)

        调用方消费完整后必须关闭(async for 正常结束即可)。
        失败时抛出 LLMError(流式无重试:已输出内容无法回滚)。
        """
        raise NotImplementedError

    @abstractmethod
    def chat_stream_with_messages(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """多轮流式版:system 单独传入,messages 是 [{role,content}] 列表(不含 system)"""
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    async def chat_with_image(
        self,
        system: str,
        user_prompt: str,
        image_data_url: str,
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> str:
        """多模态 chat:文本 + 图片(base64 data URL)

        默认 raise NotImplementedError;支持视觉的 Provider(MiniMax)override。
        screenshot_service OCR 失败时 fallback 到本方法。
        """
        raise NotImplementedError(
            f"{self.name} 不支持视觉识别,只能 OCR 文本模式"
        )

    @property
    def supports_vision(self) -> bool:
        """是否支持图像输入(默认 False,视觉模型 override 返回 True)"""
        return False


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
        last_err: Exception | None = None
        # trust_env=False:避免系统代理干扰(公司网络下 TSL 断连,ADR-0005 同因)
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

    async def chat_stream(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        async for piece in self.chat_stream_with_messages(
            system, [{"role": "user", "content": user}], temperature
        ):
            yield piece

    def chat_stream_with_messages(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        """OpenAI 兼容流式(SSE chunk 的 choices[0].delta.content)"""
        return self._chat_stream_with_messages_impl(system, messages, temperature)

    async def _chat_stream_with_messages_impl(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> AsyncIterator[str]:
        # 非 2xx 的完整响应体先读到内存再判断,避免与流式读冲突
        request = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": temperature,
            "stream": True,
        }
        stripper = ThinkStripper()
        async with httpx.AsyncClient(trust_env=False, timeout=60) as client:
            async with client.stream(
                "POST",
                self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=request,
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


class LLMError(Exception):
    """LLM 调用失败(重试耗尽)"""
