"""LLM 测试服务(P4.2e:真实 API 调用)

1. 取解密 Key,未配置 → 直接失败
2. factory.get(provider) 实例化
3. 真正调 Provider.chat("回复 OK")(短超时,重试 1 次)
"""
import time

from app.llm.base import LLMError
from app.llm.factory import provider_factory
from app.models.schemas import LlmTestResponse
from app.repositories.llm_keys_repo import llm_keys_repo


class LlmTestService:
    async def test_provider(self, provider: str) -> LlmTestResponse:
        """测试 provider 连接:真实调一次 API"""
        t0 = time.time()

        # 1. 取解密 Key
        plaintext = await llm_keys_repo.get_decrypted(provider)
        if plaintext is None:
            return LlmTestResponse(
                ok=False,
                latency_ms=int((time.time() - t0) * 1000),
                error=f"{provider} 未配置 Key",
            )

        # 2. 实例化(缺 Key 返回 None)
        llm = await provider_factory.get(provider)
        if llm is None:
            return LlmTestResponse(
                ok=False,
                latency_ms=int((time.time() - t0) * 1000),
                error=f"{provider} 未配置 Key",
            )

        # 3. 真实调用
        try:
            await llm.chat("你是连接测试助手", "回复 OK", max_retries=1)
        except LLMError as e:
            return LlmTestResponse(
                ok=False,
                latency_ms=int((time.time() - t0) * 1000),
                error=str(e),
            )

        return LlmTestResponse(
            ok=True,
            latency_ms=int((time.time() - t0) * 1000),
        )


llm_test_service = LlmTestService()
