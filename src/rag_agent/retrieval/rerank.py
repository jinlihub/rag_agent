"""检索结果重排序（Rerank）：对向量召回的候选做二次排序，提升顶部相关性。

后端由 RERANK_BACKEND 选择：
  llm —— 用工具轮小模型对候选 listwise 打分（默认，零新增依赖）。
        实测智谱 /rerank 接口在本语料上判别度不足（候选分数全部 ≈1.0，连无关
        对照都有 0.92），故不用它；glm-4.5-air 打分一次 ~1.8s，判别清晰。
  api —— 通用 rerank 接口（Jina/Cohere/SiliconFlow 风格 POST {RERANK_BASE_URL}/rerank），
        供后续接入 bge-reranker 等有判别度的专用模型。
  off —— 关闭，维持向量相似度序。

重排失败一律回退原向量序，绝不阻断检索链路；分数统一归一到 0~1。
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request

from rag_agent.clients.llm_factory import get_llm_client
from rag_agent.config import get_settings

logger = logging.getLogger(__name__)

CANDIDATE_CAP = 16  # 参与打分的候选上限（控制 prompt 规模与延迟），调用方过量召回不超过它
MIN_CANDIDATES = 8  # 候选少于此数时融合序已足够准，跳过打分省掉一次 LLM 往返（~1.8s）
_CLIP = 260         # 每条候选截断长度，打分只需主旨

_SCORE_SYSTEM = (
    "你是检索相关性评分器。给定一个问题和若干候选片段，为每个片段打相关性分："
    "10=片段直接包含问题的答案；7=高度相关；4=部分相关；0=完全无关。"
    '只输出 JSON：{"scores":[{"i":候选编号,"s":分数},...]}，必须覆盖全部候选编号，'
    "不要输出任何其他内容。"
)


def rerank(query: str, texts: list[str]) -> list[tuple[int, float]] | None:
    """按与 query 的相关性重排候选，返回 [(原索引, 0~1 分)] 降序。

    关闭 / 候选不足 MIN_CANDIDATES / 后端失败时返回 None，调用方保持原向量序即可。
    候选少时融合序已足够准，跳过打分可省一次 LLM 往返；这不是降级，是去掉无收益的开销。
    """
    backend = get_settings().rerank_backend
    if backend not in ("api", "llm") or len(texts) < MIN_CANDIDATES:
        return None
    try:
        if backend == "api":
            return _sort_ranked(_rerank_api(query, texts[:CANDIDATE_CAP]))
        return _sort_ranked(_rerank_llm(query, texts[:CANDIDATE_CAP]))
    except Exception:  # noqa: BLE001 —— 重排只是锦上添花，失败回退原序
        logger.warning("rerank(%s) 失败，回退向量序", backend, exc_info=True)
        return None


def _sort_ranked(pairs: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """按分数降序；同分保持原索引序（稳定，不打乱向量召回的相对次序）。"""
    return sorted(pairs, key=lambda p: (-p[1], p[0]))


def _rerank_llm(query: str, texts: list[str]) -> list[tuple[int, float]]:
    """listwise：一次调用让小模型给全部候选打分（0~10），归一到 0~1。"""
    s = get_settings()
    listing = "\n".join(f"[{i}] {t[:_CLIP]}" for i, t in enumerate(texts))
    resp = get_llm_client().chat(
        [
            {"role": "system", "content": _SCORE_SYSTEM},
            {"role": "user", "content": f"问题：{query}\n\n候选片段：\n{listing}"},
        ],
        model=s.rerank_model or s.llm_tool_model or s.llm_model,
        temperature=0,
        timeout=s.rerank_timeout,
        thinking=s.llm_tool_thinking,
    )
    scores = _parse_scores(resp.choices[0].message.content or "", len(texts))
    return [(i, v / 10) for i, v in enumerate(scores)]


def _parse_scores(raw: str, n: int) -> list[float]:
    """解析模型输出的 {"scores":[{"i","s"}]}；缺编号/越界/非法 JSON 一律按 -1 沉底。"""
    scores = [-1.0] * n
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return scores
    try:
        items = json.loads(m.group()).get("scores", [])
    except json.JSONDecodeError:
        return scores
    for it in items:
        try:
            i, v = int(it["i"]), max(0.0, min(10.0, float(it["s"])))
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= i < n:
            scores[i] = v
    return scores


def _rerank_api(query: str, texts: list[str]) -> list[tuple[int, float]]:
    """专用 rerank 接口（Jina/Cohere/SiliconFlow 风格）。环境未装 httpx，用 urllib。"""
    s = get_settings()
    if not (s.rerank_base_url and s.rerank_api_key and s.rerank_model):
        raise RuntimeError("RERANK_BACKEND=api 需配置 RERANK_BASE_URL / RERANK_API_KEY / RERANK_MODEL")
    body = json.dumps(
        {
            "model": s.rerank_model,
            "query": query,
            "documents": [t[:_CLIP] for t in texts],
            "top_n": len(texts),
        }
    ).encode()
    req = urllib.request.Request(  # noqa: S310 —— URL 来自受信配置
        f"{s.rerank_base_url.rstrip('/')}/rerank",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {s.rerank_api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=s.rerank_timeout) as r:
        data = json.loads(r.read().decode())
    return [
        (int(it["index"]), float(it.get("relevance_score", it.get("score", 0.0))))
        for it in data.get("results", [])
        if 0 <= int(it.get("index", -1)) < len(texts)
    ]
