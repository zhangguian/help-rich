"""LLM 测试服务(轻量 stub,MVP 阶段先验证 Key 格式 + DB 读写)

真正的 LLM 调用在 P4.2 实施,这里只验证:
1. Key 是否能加密/解密往返
2. Key 是否有效(粗略检查:非空 + 长度合理)
3. 返回延迟(模拟 100ms)

P4.2 升级:真正调 Provider.chat("回复 OK")
"""
import asyncio
import time

from app.models.schemas import LlmTestResponse
from app.repositories.llm_keys_repo import llm_keys_repo


class LlmTestService:
    async def test_provider(self, provider: str) -> LlmTestResponse:
        """测试 provider 连接(P1.4 阶段只验证 Key 存在 + 格式)"""
        t0 = time.time()

        # 1. 取解密 Key
        plaintext = await llm_keys_repo.get_decrypted(provider)
        if plaintext is None:
            return LlmTestResponse(
                ok=False,
                latency_ms=int((time.time() - t0) * 1000),
                error=f"{provider} 未配置 Key",
            )

        # 2. 粗略校验
        if not plaintext or len(plaintext) < 8:
            return LlmTestResponse(
                ok=False,
                latency_ms=int((time.time() - t0) * 1000),
                error="Key 格式无效",
            )

        # 3. 模拟延迟(P4.2 真正调 API)
        await asyncio.sleep(0.1)

        return LlmTestResponse(
            ok=True,
            latency_ms=int((time.time() - t0) * 1000),
        )


llm_test_service = LlmTestService()