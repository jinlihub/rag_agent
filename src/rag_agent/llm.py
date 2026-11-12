"""向量化客户端（embedding）。对话客户端已迁移至 rag_agent/clients/（基类 + 工厂 + 厂商实现）。"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from openai import OpenAI

from rag_agent.config import get_settings


@lru_cache(maxsize=1)
def embedding_client() -> OpenAI:
    s = get_settings()
    if not s.embedding_configured:
        raise RuntimeError(
            "向量模型未配置：请在 .env 中填写 EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL"
            "（或只填 LLM_*，embedding 复用同一服务）"
        )
    return OpenAI(
        base_url=s.embedding_base_url, api_key=s.embedding_api_key, timeout=60, max_retries=2
    )


def embed_texts(texts: list[str], batch_size: int = 16) -> list[list[float]]:
    """批量向量化，返回 L2 归一化后的向量（后续点积即余弦相似度）。"""
    client = embedding_client()
    model = get_settings().embedding_model
    vecs: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(model=model, input=batch)
        vecs.extend(d.embedding for d in resp.data)
    arr = np.asarray(vecs, dtype="float32")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).tolist()
