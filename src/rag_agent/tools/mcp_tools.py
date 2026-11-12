"""MCP 客户端工具桥：把标准 MCP server（非自研）的工具接入 Agent。

与 tools/base.py 的自建工具不同，工具本体由外部 MCP server 提供，本模块不实现检索
逻辑，只负责三件事：

  1. 建会话：Streamable HTTP 连接 → initialize → call_tool；
  2. 归一化：把 MCP 返回的 content 转成 Agent 认识的 {"matches": [...]}，
     每行带 title/url/content（可选 score），这样质量关卡与"参考来源"面板才能工作；
  3. 同步桥接：Agent 是同步生成器，MCP SDK 是 async——不在事件循环里直接 asyncio.run，
     已在循环里则切到独立线程跑，两种上下文都安全。

首个接入：Exa（https://mcp.exa.ai/mcp，官方托管 MCP server），作为 Tavily 之外的
第二个搜索引擎。两者结果都归到 source_kind="web"，前端统一显示为「网页」。
"""

from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic import Field

from rag_agent.config import get_settings
from rag_agent.tools.base import BaseTool, ToolArgs

# Exa MCP server 暴露的搜索工具名（官方 server 的工具定义，非本项目自建）
EXA_SEARCH_TOOL = "web_search_exa"

# MCP 文本结果里的字段行，如 "Title: xxx" / "URL: https://..." / "Published Date: ..."
_FIELD_RE = re.compile(
    r"^\s*(title|url|published date|published|author|text|highlights)\s*:\s*(.*)$", re.I
)


def _run_sync(coro: Any) -> Any:
    """在同步上下文执行协程；已在事件循环中时切到独立线程，避免嵌套循环报错。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _leaf_message(e: BaseException) -> str:
    """ExceptionGroup（anyio TaskGroup 包装）逐层解到最内层，避免只报 "unhandled errors"。"""
    for _ in range(8):
        if not isinstance(e, BaseExceptionGroup) or not e.exceptions:
            break
        e = e.exceptions[0]
    text = f"{type(e).__name__}: {e}"
    if any(k in text.lower() for k in ("401", "unauthorized", "invalid api key", "authentication")):
        text += "（请检查 EXA_API_KEY 是否有效）"
    return text


def _content_text(result: Any) -> str:
    """CallToolResult.content → 纯文本（拼所有 TextContent）。"""
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts).strip()


def _rows_from_structured(data: Any) -> list[dict[str, Any]]:
    """MCP structuredContent → 来源行；兼容 results/items 两种外层键。"""
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("results") or data.get("items") or []
    else:
        return []
    rows: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or it.get("name") or "").strip()
        url = str(it.get("url") or "").strip()
        content = str(it.get("text") or it.get("content") or it.get("summary") or "").strip()
        if not title and not url:
            continue
        row: dict[str, Any] = {"title": (title or url)[:200], "url": url, "content": content[:400]}
        score = it.get("score")
        if isinstance(score, (int, float)):
            row["score"] = round(float(score), 3)
        rows.append(row)
    return rows


def _rows_from_text(raw: str) -> list[dict[str, Any]]:
    """解析 Exa MCP 的文本结果（按 "Title:" 切块）；不认识的格式整段兜底一条。"""
    raw = (raw or "").strip()
    if not raw:
        return []
    # 少数部署会直接把 JSON 作为文本返回
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        rows = _rows_from_structured(parsed)
        if rows:
            return rows

    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in raw.splitlines():
        if re.match(r"^\s*title\s*:", line, re.I):
            if current:
                blocks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        blocks.append(current)

    rows: list[dict[str, Any]] = []
    for block in blocks:
        title = url = ""
        body: list[str] = []
        for line in block:
            m = _FIELD_RE.match(line)
            if not m:
                body.append(line.strip())
                continue
            key, value = m.group(1).lower(), m.group(2).strip()
            if key == "title":
                title = value
            elif key == "url":
                url = value
            elif key in ("text", "highlights") and value:
                body.append(value)  # "Text: 正文" 同行时保留内容
        if not (title or url):
            continue
        text = " ".join(x for x in body if x).strip()
        rows.append({"title": (title or url)[:200], "url": url, "content": text[:400]})

    if rows:
        return rows
    # 兜底：没有 Title 标记（server 换格式时不至于让工具空手而归）
    first = next((ln.strip() for ln in raw.splitlines() if ln.strip()), "")[:120]
    return [{"title": first or "Exa 搜索结果", "url": "", "content": raw[:400]}]


async def _call_exa(query: str, max_results: int, timeout: float) -> dict[str, Any]:
    """连接 Exa 托管 MCP server 并调用 web_search_exa。"""
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    s = get_settings()
    url = s.exa_mcp_url
    if "exaApiKey=" not in url:  # 官方托管端点用查询参数带 key；自托管可预置在 URL 里
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}exaApiKey={s.exa_api_key}"

    headers = {"x-api-key": s.exa_api_key}  # 兼容部分自托管部署的 header 鉴权
    async with httpx2.AsyncClient(headers=headers, timeout=timeout) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timeout) as session:
                await session.initialize()
                # 工具名以 server 实际暴露为准（官方 server 可能改版），优先按约定名找，
                # 找不到就退回名称含 search 的第一个，避免硬编码导致整条链路失效
                listed = await session.list_tools()
                names = [t.name for t in (getattr(listed, "tools", None) or [])]
                tool_name = EXA_SEARCH_TOOL if EXA_SEARCH_TOOL in names else next(
                    (n for n in names if "search" in n.lower()), None
                )
                if not tool_name:
                    raise RuntimeError(f"Exa MCP 未提供搜索工具（可用: {', '.join(names) or '无'}）")
                result = await session.call_tool(
                    tool_name,
                    {"query": query, "numResults": max_results},
                    read_timeout_seconds=timeout,
                )
                if getattr(result, "is_error", False):
                    detail = _content_text(result)[:200]
                    raise RuntimeError(detail or "Exa MCP 工具返回错误")

                rows = _rows_from_structured(getattr(result, "structured_content", None))
                if not rows:
                    rows = _rows_from_text(_content_text(result))
    out: dict[str, Any] = {"matches": rows[:max_results]}
    if not rows:
        out["note"] = "Exa 未返回可用网页结果"
    return out


class ExaWebSearchArgs(ToolArgs):
    query: str = Field(description="搜索关键词或查询句")
    max_results: int = Field(default=5, ge=1, le=8, description="返回条数，默认 5")


class ExaWebSearchTool(BaseTool):
    """Exa MCP 搜索：与 Tavily（search_web）并列的第二个联网搜索引擎。"""

    name = "search_web_exa"
    description = (
        "联网搜索（Exa，与 search_web 不同的一家搜索引擎）。适用于查找网页/文章、"
        "最新公告与政策解读；与 search_web 互为备选——一个引擎结果不理想时可换另一个再查。"
        "返回：标题、网址、内容摘要。"
    )
    args_model = ExaWebSearchArgs
    source_kind = "web"
    source_title_key = "title"
    empty_hint = "可换更具体或更宽泛的搜索词重试，或改用 search_web（Tavily）再查一次。"

    def run(self, args: ExaWebSearchArgs) -> dict[str, Any]:
        s = get_settings()
        if not s.exa_api_key:
            return {"error": "未配置 EXA_API_KEY，Exa 联网搜索不可用"}
        try:
            return _run_sync(_call_exa(args.query, args.max_results, s.exa_timeout))
        except Exception as e:  # noqa: BLE001 —— 统一转成 RuntimeError，由基类折叠成可读错误
            raise RuntimeError(f"Exa MCP 调用失败: {_leaf_message(e)}") from e
