"""DeepSeek 客户端(backend-arch §9.2)

OpenAI 兼容接口:
- POST https://api.deepseek.com/v1/chat/completions
- 3 次指数退避(2s / 4s / 8s)
"""
from app.llm.base import OpenAICompatClient


class DeepSeekClient(OpenAICompatClient):
    """DeepSeek chat API 客户端"""

    name = "deepseek"
    _model = "deepseek-chat"
    BASE_URL = "https://api.deepseek.com/v1/chat/completions"
    provider_label = "DeepSeek"
