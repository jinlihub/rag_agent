"""轻量稀疏检索：语料内建 BM25（中文按字符二元组切词），纯内存零依赖。

与向量检索共用同一份语料（data/index/*.meta.jsonl，约 1 万条），作为 dense 腿之外的
关键词召回腿：法规名/条款号/专有名词等强特征词 Embed 常不到位，BM25 补得上。

中文无分词器，取字符二元组（bigram）近似词粒度——"质疑时限" → 质疑/疑时/时限；
ASCII 连续串按整词（EPC、ISO9001）。字段按库配置加权重复（标题类 ×2），让
法名/问题文本的命中强于正文长尾。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Any

from rag_agent.retrieval.vector_store import get_store

_ASCII_TOKEN = re.compile(r"[a-zA-Z0-9]+")
_CJK_RUN = re.compile(r"[一-鿿]+")

# 每个库参与 BM25 的字段与重复次数（×2 = 提权：命中标题/法名比命中正文更说明相关）
_FIELDS: dict[str, tuple[tuple[str, int], ...]] = {
    "legal": (("law_name", 2), ("article_title", 2), ("text", 1)),
    "policy": (("title", 2), ("text", 1)),
    "faq": (("question", 2), ("answer", 1)),
}

_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> list[str]:
    """ASCII 词 + 中文二元组；单字汉字串退回单字。"""
    tokens = [m.group().lower() for m in _ASCII_TOKEN.finditer(text)]
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


class SparseIndex:
    """BM25 索引：构建时持有各行的 meta，检索按行号回带原记录。"""

    def __init__(self, metas: list[dict[str, Any]], fields: tuple[tuple[str, int], ...]) -> None:
        self.metas = metas
        self.doc_tokens = [
            tokenize(" ".join(part for f, rep in fields for part in [str(m.get(f) or "")] * rep))
            for m in metas
        ]
        self.doc_len = [len(d) for d in self.doc_tokens]
        self.avgdl = (sum(self.doc_len) / len(self.doc_tokens)) if self.doc_tokens else 1.0
        # 倒排表 tok -> {行号: tf}：检索时只遍历命中文档，避免每个 token 扫全量语料
        self.inverted: dict[str, dict[int, int]] = {}
        df: Counter[str] = Counter()
        for i, d in enumerate(self.doc_tokens):
            for tok, tf in Counter(d).items():
                self.inverted.setdefault(tok, {})[i] = tf
                df[tok] += 1
        self.df = df

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """返回 [{**meta, "row", "score"(BM25)}] 降序；无命中返回空。"""
        q_tokens = tokenize(query)
        if not q_tokens or not self.doc_tokens:
            return []
        n = len(self.doc_tokens)
        scores: dict[int, float] = {}
        for tok in set(q_tokens):
            postings = self.inverted.get(tok)
            if not postings:
                continue
            idf = math.log(1.0 + (n - self.df[tok] + 0.5) / (self.df[tok] + 0.5))
            for i, tf in postings.items():
                denom = tf + _K1 * (1.0 - _B + _B * self.doc_len[i] / self.avgdl)
                scores[i] = scores.get(i, 0.0) + idf * tf * (_K1 + 1.0) / denom
        top = sorted(scores.items(), key=lambda p: (-p[1], p[0]))[: max(1, top_k)]
        return [{**self.metas[i], "row": i, "score": round(s, 3)} for i, s in top]


@lru_cache(maxsize=None)
def get_sparse(name: str) -> SparseIndex:
    """按库名取稀疏索引（语料与 get_store(name) 完全一致）。"""
    fields = _FIELDS.get(name)
    if fields is None:
        raise ValueError(f"未配置稀疏检索字段: {name}")
    return SparseIndex(get_store(name).meta, fields)
