"""SSE 事件流入口：API 层与脚本统一从这里取事件，契约见 agent.py 模块注释。

Agent 的创建、工具注册与循环调用都在 Agent 类（agent.py）里；
本模块只保留稳定的应用层接口。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from rag_agent.agent.agent import Agent


def run_agent_stream(
    question: str,
    history: list[dict[str, str]] | None = None,
    allow_web: bool = False,
    answer_model: str | None = None,
    deep_thinking: bool = False,
) -> Iterator[dict[str, Any]]:
    """便捷入口：每次调用创建一个 Agent 实例并流式执行。

    allow_web=True 时启用联网搜索工具（前端"联网搜索"开关）；
    answer_model 指定最终作答模型（前端"LLM 选择"），空则用配置的默认模型；
    deep_thinking=True 时最终作答使用深度思考（前端"深度思考"开关）。
    """
    return Agent().run_stream(
        question,
        history,
        allow_web=allow_web,
        answer_model=answer_model,
        deep_thinking=deep_thinking,
    )
