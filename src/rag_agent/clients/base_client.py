"""LLM 对话客户端基类：统一智谱 / DeepSeek 等 OpenAI 兼容厂商的调用方式。

子类声明 provider 与默认模型，实现 from_settings()（从 .env 构造）与
_thinking_extra()（厂商特有的推理开关透传）；基类提供统一的 chat() / chat_stream()。
响应统一为 OpenAI SDK 形态（resp.choices[0].message / delta），调用方零感知厂商差异。

HTTP 层复用 openai SDK：智谱与 DeepSeek 均提供 OpenAI 兼容端点，无需手写 SSE 解析。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from openai import OpenAI


class BaseLLMClient(ABC):
    """对话客户端基类。

    用法：
        client = get_llm_client()
        resp = client.chat(messages, tools=schemas, thinking="disabled")
        for chunk in client.chat_stream(messages, temperature=0.3): ...
    """

    provider: str = "base"
    # 默认模型：纯文本对话 / 工具轮（function calling）；可被 .env 对应项覆盖
    default_model: str = ""
    default_tool_model: str = ""

    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        if not (base_url and api_key):
            raise RuntimeError(f"{self.provider} 对话客户端未配置：缺少 base_url 或 api_key")
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=2)

    @classmethod
    @abstractmethod
    def from_settings(cls) -> "BaseLLMClient":
        """从全局配置（.env）构造客户端；未配置时抛出可读错误。"""

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        stream: bool = False,
        thinking: str | None = None,
        timeout: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """对话一轮。

        thinking: "enabled"/"disabled"（None=不透传，是否生效取决于厂商实现）；
        tools: OpenAI function calling 的 Schema 列表；stream=True 返回 chunk 迭代器；
        max_tokens: 生成上限（探活等只需极少 token 的场景用）。
        """
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if timeout is not None:
            kwargs["timeout"] = timeout
        kwargs.update(self._thinking_extra(thinking, model=kwargs["model"]))
        if stream:
            return self._client.chat.completions.create(**kwargs, stream=True)
        return self._client.chat.completions.create(**kwargs)

    def chat_stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        """chat() 的流式版：逐 chunk 返回（chunk.choices[0].delta.content）。"""
        return self.chat(messages, **kwargs, stream=True)

    def _thinking_extra(self, thinking: str | None, model: str | None = None) -> dict[str, Any]:
        """厂商特有的 thinking 透传参数；默认不支持，返回空（model 供子类按型号分流）。"""
        return {}
