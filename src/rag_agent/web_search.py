"""Tavily 联网搜索：本地知识库无答案时的补充检索（最新公告/法规更新）。

REST 直连（urllib，无额外依赖）：POST https://api.tavily.com/search，Bearer 认证；
results[].score 为 0~1 的相关性评分，原样透传给前端展示。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from rag_agent.config import get_settings

_ENDPOINT = "https://api.tavily.com/search"


class NotConfigured(RuntimeError):
    """未配置 TAVILY_API_KEY。"""


def web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """搜索并返回 [{title, url, content, score}]；score 为 Tavily 相关性评分（0~1）。"""
    s = get_settings()
    if not s.tavily_api_key:
        raise NotConfigured("未配置 TAVILY_API_KEY，联网搜索不可用")
    payload = json.dumps(
        {
            "query": query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
    ).encode()
    req = urllib.request.Request(
        _ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {s.tavily_api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=s.tavily_timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Tavily 接口返回 {e.code}: {e.read().decode(errors='replace')[:200]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Tavily 连接失败: {e.reason}") from e
    return _parse_payload(data, max_results)


def _parse_payload(data: dict[str, Any], max_results: int) -> list[dict[str, Any]]:
    """Tavily 响应 → 工具结果行（title 空时回退用 url，content 截断，score 保留 3 位）。"""
    out: list[dict[str, Any]] = []
    for r in (data.get("results") or [])[:max_results]:
        title = str(r.get("title") or "").strip()
        url = str(r.get("url") or "").strip()
        content = str(r.get("content") or "").strip()
        if not title and not url:
            continue
        out.append(
            {
                "title": (title or url)[:200],
                "url": url,
                "content": content[:400],
                "score": round(float(r.get("score") or 0.0), 3),
            }
        )
    return out
