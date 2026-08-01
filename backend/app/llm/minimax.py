"""MiniMax 客户端(backend-arch §9.2 / P4.2b)

自有 API(v1/text/chatcompletion_v2),消息体与 OpenAI 兼容。
"""
from app.llm.base import OpenAICompatClient


class MiniMaxClient(OpenAICompatClient):
    """MiniMax abab6.5s chat API 客户端"""

    name = "minimax"
    _model = "abab6.5s-chat"
    BASE_URL = "https://api.minimax.chat/v1/text/chatcompletion_v2"
    provider_label = "MiniMax"
