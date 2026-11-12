"""FAQ 索引重建：只重建 faq 一个库（~80 条，秒级），服务 B 端确认后的自动扩充。

为什么单独一个模块：全量 build_index.py 要重算法条/政策（几分钟），而运维确认一条问答后
只多了一条 FAQ，没必要整库重来。本模块从 MySQL faq_qa_pairs 全量读问题（80 条量级，
「全量重算 faq」本身就是秒级的增量操作），与 scripts/build_index.py 的 faq 分支共用实现。

dense（npz）与 sparse（meta.jsonl 按行号对齐）必须一起更新；写完清掉 get_store /
get_sparse 的进程内缓存，下一次检索即读到新语料。写入先落临时文件再原子替换，
避免并发检索读到半截索引。
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

import numpy as np

from rag_agent.config import get_settings
from rag_agent.database import query_all
from rag_agent.llm import embed_texts
from rag_agent.retrieval.sparse import get_sparse
from rag_agent.retrieval.vector_store import get_store

# 串行化重建：多个管理员几乎同时确认时排队，避免两份临时文件互相覆盖
_REBUILD_LOCK = threading.Lock()


def rebuild_faq_index() -> dict[str, Any]:
    """从 faq_qa_pairs 重建 faq.npz + faq.meta.jsonl，并刷新检索侧内存缓存。

    返回 {"count": 条数, "npz": 路径, "meta": 路径}；数据库/向量化异常向上抛出，
    由调用方决定是否吞掉（自动扩充场景不应影响管理端操作）。
    """
    with _REBUILD_LOCK:
        rows = query_all("SELECT question, answer FROM faq_qa_pairs ORDER BY id")
        texts = [r["question"] for r in rows]
        vectors = np.asarray(embed_texts(texts), dtype="float32") if texts else np.zeros((0, 1), dtype="float32")
        metas = [{"question": r["question"], "answer": r["answer"]} for r in rows]

        out_dir = get_settings().index_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        npz_path = out_dir / "faq.npz"
        meta_path = out_dir / "faq.meta.jsonl"
        # 临时文件尾部必须仍是 .npz：np.savez 只会给不带 .npz 的路径补后缀
        tmp_npz = out_dir / "faq.tmp.npz"
        tmp_meta = out_dir / "faq.meta.tmp.jsonl"
        np.savez_compressed(tmp_npz, vectors=vectors)
        with open(tmp_meta, "w", encoding="utf-8") as f:
            for m in metas:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")
        os.replace(tmp_npz, npz_path)
        os.replace(tmp_meta, meta_path)

    # 索引文件已换新：丢掉进程内的旧副本，下次 get_store/get_sparse 重新加载
    get_store.cache_clear()
    get_sparse.cache_clear()
    return {"count": len(rows), "npz": str(npz_path), "meta": str(meta_path)}
