"""DeepSeek 对话客户端：OpenAI 兼容 Chat API（https://api.deepseek.com）。

对话走 /chat/completions（deepseek-chat）；深度思考用 deepseek-reasoner 模型
（模型名由 DEEPSEEK_THINKING_MODEL 配置），Chat API 无 thinking 透传参数，
基类的 thinking 入参在此忽略。
Responses 风格的调用差异统一由 BaseLLMClient 抹平，调用方只用 chat/chat_stream。
"""

from __future__ import annotations

from rag_agent.clients.base_client import BaseLLMClient
from rag_agent.config import get_settings

DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"


class DeepSeekClient(BaseLLMClient):
    """DeepSeek 客户端。"""

    provider = "deepseek"
    default_model = "deepseek-chat"
    default_tool_model = "deepseek-chat"

    @classmethod
    def from_settings(cls) -> "DeepSeekClient":
        s = get_settings()
        if not s.deepseek_api_key:
            raise RuntimeError("DeepSeek 未配置：请在 .env 中填写 DEEPSEEK_API_KEY（platform.deepseek.com 获取）")
        return cls(s.deepseek_base_url or DEEPSEEK_DEFAULT_BASE_URL, s.deepseek_api_key)
