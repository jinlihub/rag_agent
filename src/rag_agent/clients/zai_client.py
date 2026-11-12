"""智谱 AI（GLM）对话客户端：OpenAI 兼容端点 https://open.bigmodel.cn/api/paas/v4。

GLM-4.7-FlashX 用于纯文本对话（默认，可被 .env LLM_MODEL 覆盖）；
工具轮（function calling）默认 glm-4.5-air，可被 LLM_TOOL_MODEL 覆盖。
glm-4.5/4.6 系的 thinking 开关经 extra_body 透传（LLM_THINKING_PARAM=0 整体关闭）；
glm-5.3 系常规走 reasoning_effort；前端「深度思考」时显式开 thinking 以返回思考过程，
较早型号映射为 thinking.enabled。
"""

from __future__ import annotations

import os
from typing import Any

from rag_agent.clients.base_client import BaseLLMClient
from rag_agent.config import get_settings


class ZaiClient(BaseLLMClient):
    """智谱 GLM 客户端。"""

    provider = "zai"
    default_model = "glm-4.7-flashx"
    default_tool_model = "glm-4.5-air"

    @classmethod
    def from_settings(cls) -> "ZaiClient":
        s = get_settings()
        if not s.llm_configured:
            raise RuntimeError(
                "智谱对话模型未配置：请在 .env 中填写 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL"
            )
        return cls(s.llm_base_url, s.llm_api_key)

    def _thinking_extra(self, thinking: str | None, model: str | None = None) -> dict[str, Any]:
        """默认始终透传 disabled 压首字延迟；仅显式 enabled / LLM_TOOL_THINKING 等才开。

        LLM_THINKING_PARAM=0 时整体关闭透传（其他 OpenAI 兼容端点不识别该字段时用）。

        glm-5.3 系始终思考，不接受 thinking.type=disabled（会 400），常规只认
        reasoning_effort: low/high/max，故按模型名分流。前端「深度思考」传 high/max：
        glm-5.3 改为 thinking.type=enabled 以返回 reasoning_content（reasoning_effort
        模式下智谱不返回思考内容）；较早型号没有强度档位，同样映射为 enabled。
        """
        if os.getenv("LLM_THINKING_PARAM", "1") == "0":
            return {}
        if model and model.startswith("glm-5.3"):
            if thinking in ("enabled", "high", "max"):
                # 深度思考：显式开 thinking 才会返回 reasoning_content，供前端展示思考过程。
                # 实测 glm-5.3 在 reasoning_effort 模式下不返回思考内容，且与 thinking
                # 同时传时仍被隐藏，因此深度模式只传 thinking.type=enabled。
                return {"extra_body": {"thinking": {"type": "enabled"}}}
            effort = thinking if thinking in ("low", "high", "max") else "low"
            return {"extra_body": {"reasoning_effort": effort}}
        enabled = thinking in ("enabled", "high", "max")
        return {"extra_body": {"thinking": {"type": "enabled" if enabled else "disabled"}}}
