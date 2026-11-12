"""应用层数据访问：用户 / 问答记录（含维护状态机）/ 埋点事件。"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pymysql

from rag_agent.database import get_conn


class DuplicateUser(ValueError):
    """用户名已存在。"""


def _sanitize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        out.append(
            {
                k: str(v) if isinstance(v, (datetime.datetime, datetime.date)) else (
                    float(v) if isinstance(v, Decimal) else v
                )
                for k, v in row.items()
            }
        )
    return out


# ── 用户 ────────────────────────────────────────────────────────────────────


def create_user(
    username: str,
    password_hash: str,
    email: str | None = None,
    user_type: str = "自然人",
    display_name: str | None = None,
    role: str = "user",
) -> int:
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_account
                   (username, password_hash, email, user_type, display_name, role)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (username, password_hash, email, user_type, display_name or username, role),
            )
            conn.commit()
            return int(cur.lastrowid)
    except pymysql.err.IntegrityError as e:
        if e.args and e.args[0] == 1062:
            raise DuplicateUser(f"用户名已存在: {username}") from e
        raise


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM user_account WHERE username = %s", (username,))
        return cur.fetchone()


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM user_account WHERE id = %s", (user_id,))
        return cur.fetchone()


# ── 问答记录 ────────────────────────────────────────────────────────────────


def create_qa_record(user_id: int, question: str, session_id: str | None = None) -> int:
    """提问即落库（answer 置空），流式结束后 finish_qa_record 回填。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO qa_record (user_id, question, session_id) VALUES (%s, %s, %s)",
            (user_id, question, session_id),
        )
        conn.commit()
        return int(cur.lastrowid)


def finish_qa_record(qa_id: int, answer: str, sources_json: str | None) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE qa_record SET answer = %s, sources = %s WHERE id = %s",
            (answer, sources_json, qa_id),
        )
        conn.commit()


def qa_record_exists(qa_id: int) -> bool:
    """记录是否存在；配合 rowcount 区分「不存在」与「值未变化（MySQL 返回 0）」两种情况。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 AS ok FROM qa_record WHERE id = %s", (qa_id,))
        return cur.fetchone() is not None


def update_qa_answer(qa_id: int, answer: str) -> int:
    """管理员编辑回答 → 维护状态置为「已维护」，修改时间由 ON UPDATE 自动刷新。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE qa_record SET answer = %s, maintain_status = '已维护' WHERE id = %s",
            (answer, qa_id),
        )
        conn.commit()
        return cur.rowcount


def set_maintain_status(qa_id: int, status: str) -> int:
    """标记正确/不需要维护等状态流转，updated_at 自动刷新。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE qa_record SET maintain_status = %s WHERE id = %s",
            (status, qa_id),
        )
        conn.commit()
        return cur.rowcount


def set_result_evaluation(qa_id: int, user_id: int, evaluation: str) -> int:
    """C 端点赞/点踩 → 结果评价（枚举：赞/踩，撤销写回默认'无'）。

    user_id 收进 WHERE：只允许评价自己的问答记录，越权与不存在同样返回 0 行。
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE qa_record SET result_evaluation = %s WHERE id = %s AND user_id = %s",
            (evaluation, qa_id, user_id),
        )
        conn.commit()
        return cur.rowcount


def list_qa_records(
    username: str | None = None,
    keyword: str | None = None,
    user_type: str | None = None,
    maintain_status: str | None = None,
    result_evaluation: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """B 端问答列表：多条件组合筛选 + 分页（设计稿 p12）。"""
    where: list[str] = []
    params: list[Any] = []
    if username:
        like = f"%{username}%"
        where.append("(u.username LIKE %s OR u.display_name LIKE %s)")
        params += [like, like]
    if keyword:
        where.append("q.question LIKE %s")
        params.append(f"%{keyword}%")
    if user_type:
        where.append("u.user_type = %s")
        params.append(user_type)
    if maintain_status:
        where.append("q.maintain_status = %s")
        params.append(maintain_status)
    if result_evaluation:
        where.append("q.result_evaluation = %s")
        params.append(result_evaluation)
    if date_from:
        where.append("q.created_at >= %s")
        params.append(date_from)
    if date_to:
        where.append("q.created_at <= %s")
        params.append(f"{date_to} 23:59:59")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    offset = (page - 1) * page_size

    base = "FROM qa_record q JOIN user_account u ON q.user_id = u.id" + clause
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c {base}", params)
        total = cur.fetchone()["c"]
        cur.execute(
            f"""SELECT q.id, q.question, q.answer, q.maintain_status, q.result_evaluation,
                       q.created_at, q.updated_at, u.username, u.display_name, u.user_type
                 {base} ORDER BY q.created_at DESC LIMIT %s OFFSET %s""",
            params + [page_size, offset],
        )
        rows = _sanitize(list(cur.fetchall()))
    return {"total": total, "page": page, "page_size": page_size, "items": rows}


# ── 未维护问题聚类（B 端批量消化积压）──────────────────────────────────────


def list_unmaintained_qa(limit: int | None = None) -> list[dict[str, Any]]:
    """拉取未维护问题（含来源 JSON），供聚类脚本向量化与起草。

    limit: 只取最近 N 条（冒烟测试用）；不传则全量，按 id 升序。
    """
    with get_conn() as conn, conn.cursor() as cur:
        if limit:
            cur.execute(
                "SELECT id, question, sources FROM qa_record"
                " WHERE maintain_status = '未维护' ORDER BY id DESC LIMIT %s",
                (int(limit),),
            )
            rows = list(reversed(cur.fetchall()))
        else:
            cur.execute(
                "SELECT id, question, sources FROM qa_record"
                " WHERE maintain_status = '未维护' ORDER BY id ASC"
            )
            rows = list(cur.fetchall())
    return _sanitize(rows)


def save_answer_drafts(qa_ids: list[int], draft: str) -> int:
    """把同一簇共用的草稿写回成员行（只更新仍未维护的记录，避免覆盖人工处理结果）。"""
    if not qa_ids:
        return 0
    placeholders = ", ".join(["%s"] * len(qa_ids))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE qa_record SET answer_draft = %s"
            f" WHERE maintain_status = '未维护' AND id IN ({placeholders})",
            [draft, *qa_ids],
        )
        conn.commit()
        return cur.rowcount


def list_qa_clusters(sample_size: int = 5) -> dict[str, Any]:
    """未维护问题的聚类视图：按草稿内容归簇（草稿由聚类脚本写入，同簇共用一份）。

    簇 id 取簇内最小 qa_record.id，脚本重跑后同一批问题得到稳定 id；
    草稿更新后旧簇自然消失，因此不需要额外的簇表。
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, question, answer_draft FROM qa_record
                WHERE maintain_status = '未维护'
                  AND answer_draft IS NOT NULL AND answer_draft <> ''
                ORDER BY id ASC"""
        )
        rows = list(cur.fetchall())
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r["answer_draft"], []).append(r)
    items = [
        {
            "id": int(members[0]["id"]),
            "size": len(members),
            "draft": draft,
            "questions": [m["question"] for m in members[:sample_size]],
            "qa_ids": [int(m["id"]) for m in members],
        }
        for draft, members in groups.items()
    ]
    items.sort(key=lambda c: (-c["size"], c["id"]))
    return {"total": len(items), "total_questions": len(rows), "items": items}


def approve_qa_cluster(cluster_id: int) -> int:
    """一键确认：把该簇（同草稿）的全部未维护记录置为「已维护」，返回更新条数。

    cluster_id 是簇内任一成员 id（前端取簇 id），查不到草稿或已处理时返回 0。
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT answer_draft FROM qa_record
                WHERE id = %s AND maintain_status = '未维护'
                  AND answer_draft IS NOT NULL AND answer_draft <> ''""",
            (cluster_id,),
        )
        row = cur.fetchone()
        if row is None:
            return 0
        cur.execute(
            "UPDATE qa_record SET maintain_status = '已维护'"
            " WHERE maintain_status = '未维护' AND answer_draft = %s",
            (row["answer_draft"],),
        )
        conn.commit()
        return cur.rowcount


# ── C 端对话历史（会话维度）────────────────────────────────────────────────


def list_user_sessions(
    user_id: int,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """当前用户的会话列表（新→旧）：任一条问答命中关键词即视为该会话命中。"""
    where = ["user_id = %s", "session_id IS NOT NULL"]
    params: list[Any] = [user_id]
    if keyword:
        where.append("(question LIKE %s OR answer LIKE %s)")
        params += [f"%{keyword}%", f"%{keyword}%"]
    clause = " AND ".join(where)
    page = max(1, page)
    page_size = max(1, min(page_size, 50))
    offset = (page - 1) * page_size
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(DISTINCT session_id) AS c FROM qa_record WHERE {clause}", params)
        total = cur.fetchone()["c"]
        cur.execute(
            f"""SELECT session_id, COUNT(*) AS cnt, MAX(created_at) AS last_time, MIN(id) AS first_id
                  FROM qa_record WHERE {clause}
              GROUP BY session_id ORDER BY last_time DESC LIMIT %s OFFSET %s""",
            params + [page_size, offset],
        )
        rows = list(cur.fetchall())
        titles: dict[int, str] = {}
        if rows:
            first_ids = [r["first_id"] for r in rows]
            cur.execute(
                f"SELECT id, question FROM qa_record WHERE id IN ({', '.join(['%s'] * len(first_ids))})",
                first_ids,
            )
            titles = {r["id"]: r["question"] for r in cur.fetchall()}
    items = [
        {
            "session_id": r["session_id"],
            "title": titles.get(r["first_id"], ""),
            "count": int(r["cnt"]),
            "last_time": r["last_time"],
        }
        for r in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": _sanitize(items)}


def get_session_records(user_id: int, session_id: str) -> list[dict[str, Any]]:
    """会话内全部问答（按提问顺序）；user_id 同时充当归属校验，查不到即无权/不存在。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, question, answer, sources, maintain_status, result_evaluation, created_at
                 FROM qa_record WHERE user_id = %s AND session_id = %s ORDER BY id ASC""",
            (user_id, session_id),
        )
        return _sanitize(list(cur.fetchall()))


def delete_user_session(user_id: int, session_id: str) -> int:
    """删除整组会话问答（归属校验含在 WHERE 中），返回删除的条数；滚动摘要随之清除。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM qa_record WHERE user_id = %s AND session_id = %s",
            (user_id, session_id),
        )
        deleted = cur.rowcount
        cur.execute(
            "DELETE FROM session_memory WHERE user_id = %s AND session_id = %s",
            (user_id, session_id),
        )
        conn.commit()
        return deleted


def delete_all_user_sessions(user_id: int) -> int:
    """删除当前用户全部问答记录（含未归入会话的记录），B 端随之不可见；摘要一并清除。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM qa_record WHERE user_id = %s", (user_id,))
        deleted = cur.rowcount
        cur.execute("DELETE FROM session_memory WHERE user_id = %s", (user_id,))
        conn.commit()
        return deleted


def get_session_memory(user_id: int, session_id: str) -> dict[str, Any] | None:
    """会话滚动摘要（历史压缩用）；无则 None。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT summary, upto_qa_id FROM session_memory WHERE session_id = %s AND user_id = %s",
            (session_id, user_id),
        )
        return cur.fetchone()


def save_session_memory(user_id: int, session_id: str, summary: str, upto_qa_id: int) -> None:
    """写入/推进会话摘要（session_id 唯一，重复压缩覆盖推进）。"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO session_memory (session_id, user_id, summary, upto_qa_id)
                    VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE summary = VALUES(summary), upto_qa_id = VALUES(upto_qa_id)""",
            (session_id, user_id, summary, upto_qa_id),
        )
        conn.commit()


# ── 埋点 ────────────────────────────────────────────────────────────────────


def insert_tracking_event(
    event_name: str,
    prop_name: str,
    prop_value: str,
    user_id: int | None = None,
    session_id: str | None = None,
    page: str | None = None,
) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO tracking_event
               (event_name, prop_name, prop_value, user_id, session_id, page)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (event_name, prop_name, prop_value, user_id, session_id, page),
        )
        conn.commit()
