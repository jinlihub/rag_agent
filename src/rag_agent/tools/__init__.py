"""Agent 工具层：Pydantic 模型驱动的工具定义与注册表。

用法（rag_tools.py 已把 4 个 RAG 工具批量注册进 TOOL_REGISTRY）：
    from rag_agent.tools import TOOL_REGISTRY, WEB_TOOLS, collect_sources
"""

from rag_agent.tools.base import BaseTool, ToolArgs, collect_sources
from rag_agent.tools.rag_tools import TOOL_REGISTRY, WEB_TOOLS

__all__ = [
    "BaseTool",
    "ToolArgs",
    "TOOL_REGISTRY",
    "WEB_TOOLS",
    "collect_sources",
]
