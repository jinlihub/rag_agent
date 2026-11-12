"""FAQ 自动扩充闭环：管理员确认的优质问答对自动沉淀进 faq_qa_pairs，并触发索引重建。

触发点（见 api/admin.py）：
  - 编辑回答并保存  → 以管理员改过的 answer 为准
  - 标记正确        → 优先用聚类草稿 answer_draft，没有则用原 answer
  - 按簇一键确认    → 用簇代表问题 + 共用草稿，只插入一条（不按成员数重复）

为什么不所有记录都收：qa_record 里混着「你好」「问题三」以及「本次未能检索到…」这类
兜底回答，直接全量入 FAQ 会污染检索。粗筛只放行像“问答对”的条目，宁可漏掉边缘问法。

索引重建走 retrieval/faq_index.py（只重算 faq 一个库，~80 条，秒级），在后台线程执行：
管理端的维护操作不等向量化，失败也只记日志，下次确认会再次触发。
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from rag_agent.agent.intent import is_chitchat
from rag_agent.database import get_conn, query_all
from rag_agent.retrieval.faq_index import rebuild_faq_index

logger = logging.getLogger(__name__)

_MIN_QUESTION_LEN = 6   # 「你好」「问题三」这类短句直接排除
_MIN_ANSWER_LEN = 20    # 空回答 / 「—」/ 占位话术排除
_INTERROGATIVE_RE = re.compile(
    r"(什么|如何|怎么|怎样|哪些|哪个|哪家|哪几|多少|多久|是否|能否|可否|"
    r"为什么|为何|是不是|有没有|吗|请问|区别|条件|标准|流程|要求|时限|规定|办法)"
)
_FAILURE_ANSWER_RE = re.compile(
    r"^(?:本次未能|本次未检索|未能检索|未检索到|未找到|无法(?:基于|回答|确定|查询|提供)|抱歉|—|-)"
)

_rebuild_pending = threading.Event()


def is_faq_candidate(question: str | None, answer: str | None) -> bool:
    """粗筛「值得沉淀」的问答：长度、寒暄、疑问句特征、失败兜底话术。"""
    q = (question or "").strip()
    a = (answer or "").strip()
    if len(q) < _MIN_QUESTION_LEN or len(a) < _MIN_ANSWER_LEN:
        return False
    if is_chitchat(q):
        return False
    if not (_INTERROGATIVE_RE.search(q) or q.endswith(("?", "？"))):
        return False
    if _FAILURE_ANSWER_RE.search(a[:20]):
        return False
    return True


def trigger_faq_rebuild() -> bool:
    """后台线程重建 FAQ 索引；已有排队中的重建时合并为一次。

    返回是否真正启动了线程。重建失败不影响已写入的 FAQ 行，下次确认会再次触发。
    """
    if _rebuild_pending.is_set():
        return False
    _rebuild_pending.set()
    threading.Thread(target=_rebuild_worker, name="faq-index-rebuild", daemon=True).start()
    return True


def _rebuild_worker() -> None:
    _rebuild_pending.clear()
    try:
        info = rebuild_faq_index()
        logger.info("FAQ 索引已重建: %s 条", info["count"])
    except Exception:  # noqa: BLE001 —— 后台任务失败只记日志，不冒泡到请求
        logger.exception("FAQ 索引重建失败（FAQ 行已写入，下次确认会再次触发）")


def promote_qa_to_faq(qa_id: int, *, prefer_draft: bool = True) -> dict[str, Any] | None:
    """把一条已确认的问答沉淀为 FAQ（同问题覆盖更新答案，天然幂等）。

    prefer_draft=True 用于「标记正确」：聚类草稿是这组问题的人工确认版本；
    编辑保存时传 False，以管理员刚改过的 answer 为准。不符合沉淀条件返回 None。
    """
    try:
        rows = query_all(
            "SELECT question, answer, answer_draft FROM qa_record WHERE id = %s",
            [qa_id],
        )
        if not rows:
            return None
        row = rows[0]
        answer = (row.get("answer_draft") if prefer_draft else None) or row.get("answer")
        return _promote(row.get("question"), answer, source=f"qa:{qa_id}")
    except Exception:  # noqa: BLE001 —— 自动扩充失败不能影响管理端维护操作
        logger.exception("FAQ 自动扩充失败: qa_id=%s", qa_id)
        return None


def promote_cluster_to_faq(cluster_id: int) -> dict[str, Any] | None:
    """按簇确认后，用簇代表问题 + 共用草稿沉淀一条 FAQ（不按成员数量重复插入）。"""
    try:
        rows = query_all(
            "SELECT question, answer_draft FROM qa_record WHERE id = %s",
            [cluster_id],
        )
        if not rows:
            return None
        row = rows[0]
        return _promote(row.get("question"), row.get("answer_draft"), source=f"cluster:{cluster_id}")
    except Exception:  # noqa: BLE001
        logger.exception("FAQ 自动扩充失败: cluster_id=%s", cluster_id)
        return None


def _promote(question: str | None, answer: str | None, *, source: str) -> dict[str, Any] | None:
    q = (question or "").strip()
    a = (answer or "").strip()
    if not is_faq_candidate(q, a):
        return None

    existing = query_all("SELECT id, answer FROM faq_qa_pairs WHERE question = %s LIMIT 1", [q])
    if existing:
        faq_id = int(existing[0]["id"])
        if (existing[0].get("answer") or "").strip() == a:
            return {"faq_id": faq_id, "action": "unchanged", "question": q}
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE faq_qa_pairs SET answer = %s WHERE id = %s", (a, faq_id))
            conn.commit()
        action = "updated"
    else:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO faq_qa_pairs (question, answer) VALUES (%s, %s)",
                (q, a),
            )
            conn.commit()
            faq_id = int(cur.lastrowid)
        action = "inserted"

    trigger_faq_rebuild()
    logger.info("FAQ 自动扩充[%s]: %s faq_id=%s 问题=%s", source, action, faq_id, q[:40])
    return {"faq_id": faq_id, "action": action, "question": q}
