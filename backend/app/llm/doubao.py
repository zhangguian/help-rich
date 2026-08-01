"""豆包客户端(backend-arch §9.2 / P4.2c)

火山引擎方舟 OpenAI 兼容端点。
"""
from app.llm.base import OpenAICompatClient


class DoubaoClient(OpenAICompatClient):
    """豆包 doubao-pro chat API 客户端(火山方舟)"""

    name = "doubao"
    _model = "doubao-pro-32k"
    BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    provider_label = "豆包"
