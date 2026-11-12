"""Langfuse 追踪：把每次问答上报为一条 trace，供观察回答质量、耗时与工具调用。

设计原则：**追踪是增强，不是依赖**。
  - LANGFUSE_ENABLED=false、缺 PUBLIC_KEY/SECRET_KEY、SDK 初始化失败、上报失败，
    任一情况都静默跳过，绝不抛异常影响问答主流程。
  - 上报在问答结束后一次性发生（api/chat.py 的 finally），不改变流式行为；
    span 自身的持续时长因此接近零，真实耗时放在 metadata.total_seconds 里。
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from rag_agent.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client():
    """返回 Langfuse 客户端；未启用、缺 key 或初始化失败时返回 None。"""
    s = get_settings()
    if not s.langfuse_enabled:
        return None
    if not (s.langfuse_public_key and s.langfuse_secret_key):
        logger.info("Langfuse 未配置 PUBLIC_KEY/SECRET_KEY，追踪已跳过")
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host or "https://cloud.langfuse.com",
        )
    except Exception:  # noqa: BLE001 —— 追踪不可用不能影响问答
        logger.warning("Langfuse 初始化失败，追踪已跳过", exc_info=True)
        return None


def trace_qa(
    *,
    question: str,
    answer: str,
    model: str,
    tools: list[str],
    sources: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    total_seconds: float | None,
    session_id: str | None,
    user_id: int | str | None,
) -> None:
    """上报一次完整问答。任何异常都吞掉，只记日志。"""
    client = get_client()
    if client is None:
        return
    try:
        from langfuse import propagate_attributes

        with propagate_attributes(
            user_id=str(user_id) if user_id is not None else None,
            session_id=session_id,
            trace_name="qa",
        ):
            with client.start_as_current_observation(
                name="qa",
                as_type="agent",
                input={"question": question},
                metadata={"model": model, "tools": tools},
            ):
                client.update_current_span(
                    output={
                        "answer": answer,
                        "sources": [s.get("title") for s in sources if s.get("title")],
                    },
                    metadata={
                        "total_seconds": total_seconds,
                        "stages": stages,
                        "tool_count": len(tools),
                        "source_count": len(sources),
                    },
                )
    except Exception:  # noqa: BLE001 —— 上报失败不能影响问答
        logger.warning("Langfuse 上报失败（不影响问答）", exc_info=True)
