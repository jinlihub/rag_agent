"""轻量向量检索：numpy 暴力余弦相似度。

一期语料规模（法条 ~5k + 政策切块 + 问答对 82 ≈ 1 万条向量），
暴力点积足够快，先不引入 FAISS/Milvus，后续语料涨两个量级再升级。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from rag_agent.config import get_settings
from rag_agent.llm import embed_texts


class IndexNotBuilt(RuntimeError):
    """向量索引尚未构建。"""


@lru_cache(maxsize=256)
def _embed_cached(text: str) -> tuple[float, ...]:
    """按 query 文本缓存 embedding（tuple 可哈希）。

    一次问答里 legal/policy/faq 三个库共用同一个 query，原先每次各 embed 一遍；
    缓存后只付一次网络往返。
    """
    return tuple(embed_texts([text])[0])


class VectorStore:
    def __init__(self, name: str) -> None:
        index_dir: Path = get_settings().index_dir
        npz_path = index_dir / f"{name}.npz"
        meta_path = index_dir / f"{name}.meta.jsonl"
        if not (npz_path.exists() and meta_path.exists()):
            raise IndexNotBuilt(
                f"向量索引 {name} 未构建，请先运行: uv run python scripts/build_index.py"
            )
        self.vectors = np.load(npz_path)["vectors"]
        self.meta = [
            json.loads(line)
            for line in meta_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        q = np.asarray(_embed_cached(query), dtype="float32")
        scores = self.vectors @ q  # 均已归一化，点积即余弦
        top = np.argsort(-scores)[: max(1, top_k)]
        # row = 语料行号，sparse 腿与 RRF 融合靠它对齐去重
        return [{**self.meta[int(i)], "row": int(i), "score": float(scores[i])} for i in top]


@lru_cache(maxsize=None)
def get_store(name: str) -> VectorStore:
    return VectorStore(name)
