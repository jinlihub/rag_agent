"""LLM 客户端工厂：按厂商返回客户端，支持同一进程内混用多家。

原有 `get_llm_client()` 按 .env `LLM_PROVIDER` 返回单一厂商的客户端——这在
「整个系统只对接一家」时够用。要让前端下拉同时列出智谱与 DeepSeek，就需要
按模型查对应厂商的 base_url 与 Key，因此新增 `get_client_for(provider)`：
每个厂商各缓存一个实例，互不影响。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

from rag_agent.clients.base_client import BaseLLMClient
from rag_agent.clients.deepseek_client import DeepSeekClient
from rag_agent.clients.zai_client import ZaiClient
from rag_agent.config import get_settings

# 厂商 → 客户端构造函数（新增厂商只需在此登记）
_BUILDERS: dict[str, Callable[[], BaseLLMClient]] = {
    "zai": ZaiClient.from_settings,
    "deepseek": DeepSeekClient.from_settings,
}


def known_providers() -> tuple[str, ...]:
    return tuple(_BUILDERS)


@lru_cache(maxsize=None)
def get_client_for(provider: str) -> BaseLLMClient:
    """按厂商返回客户端；同一厂商复用同一实例（连接池不重复建）。

    配置缺失时由各 Client.from_settings() 抛出可读错误，此处不吞异常——
    调用方需要知道「这家没配好」，而不是静默降级到别家。
    """
    key = (provider or "").strip().lower()
    builder = _BUILDERS.get(key)
    if builder is None:
        raise RuntimeError(f"未知 LLM_PROVIDER: {key}（可选 {' / '.join(known_providers())}）")
    return builder()


@lru_cache(maxsize=1)
def get_llm_client() -> BaseLLMClient:
    """返回当前配置的对话客户端（兼容旧调用，等价于 get_client_for(LLM_PROVIDER)）。"""
    provider = (get_settings().llm_provider or "zai").strip().lower()
    return get_client_for(provider)
