"""构建知识库向量索引（法条 / 政策全文 / 问答对）→ data/index/*.npz + *.meta.jsonl

前置：.env 中 embedding 配置可用；标的物/问答对已导入 MySQL（import_xlsx_to_mysql.py）。
用法: uv run python scripts/build_index.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from rag_agent.config import get_settings
from rag_agent.database import query_all
from rag_agent.llm import embed_texts
from rag_agent.retrieval.faq_index import rebuild_faq_index

_CHUNK_SIZE = 500   # 切块字符数
_CHUNK_OVERLAP = 80


def chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    step = size - overlap
    return [text[i : i + size] for i in range(0, len(text), step)]


def _save(name: str, vectors: np.ndarray, metas: list[dict]) -> None:
    out_dir = get_settings().index_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_dir / f"{name}.npz", vectors=vectors)
    with open(out_dir / f"{name}.meta.jsonl", "w", encoding="utf-8") as f:
        for m in metas:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"  ✓ {name}: {len(metas)} 条向量 → {out_dir / name}.npz")


def build_legal() -> None:
    print("[1/3] 法条 legal_articles + legal_metadata")
    rows = query_all(
        """SELECT a.id, a.article_title, a.content_text, m.name_zh, m.law_type
             FROM legal_articles a LEFT JOIN legal_metadata m ON a.law_id = m.law_id"""
    )
    metas: list[dict] = []
    texts: list[str] = []
    for r in rows:
        for piece in chunk_text(r["content_text"] or ""):
            texts.append(piece)
            metas.append(
                {
                    "law_name": r.get("name_zh") or "",
                    "law_type": r.get("law_type") or "",
                    "article_title": r.get("article_title") or "",
                    "text": piece,
                }
            )
    vectors = np.asarray(embed_texts(texts), dtype="float32")
    _save("legal", vectors, metas)


def build_policy() -> None:
    print("[2/3] 政策全文 policy_政策全文（整部法规切块，块首带标题）")
    rows = query_all("SELECT title, content FROM policy_政策全文")
    metas, texts = [], []
    for r in rows:
        title = r["title"] or ""
        for piece in chunk_text(r["content"] or ""):
            embedded = f"【{title}】{piece}"  # 块首带标题，提升检索命中
            texts.append(embedded)
            metas.append({"title": title, "text": embedded})
    vectors = np.asarray(embed_texts(texts), dtype="float32")
    _save("policy", vectors, metas)


def build_faq() -> None:
    print("[3/3] 问答对 faq_qa_pairs（用问题做向量，答案存元数据）")
    # 与 B 端自动扩充共用实现（retrieval/faq_index.py），保证索引格式与缓存刷新一致
    info = rebuild_faq_index()
    print(f"  ✓ faq: {info['count']} 条向量 → {info['npz']}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    build_legal()
    build_policy()
    build_faq()
    print("\n全部索引构建完成")


if __name__ == "__main__":
    main()
