"""C 端对话历史：跨会话恢复与搜索、回答反馈（/api/history/*）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from rag_agent.api.deps import get_current_user
from rag_agent.store import (
    delete_all_user_sessions,
    delete_user_session,
    get_session_records,
    list_user_sessions,
    set_result_evaluation,
)

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/sessions")
def list_sessions(
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    user: dict = Depends(get_current_user),
) -> dict:
    """当前用户的会话列表（新→旧）；keyword 命中问题或回答即命中会话。"""
    return list_user_sessions(user["id"], keyword=keyword, page=page, page_size=page_size)


@router.get("/sessions/{session_id}")
def session_messages(session_id: str, user: dict = Depends(get_current_user)) -> dict:
    """按会话取全部消息（按提问顺序展开为 user/assistant 消息对）。

    归属校验：他人会话与不存在的会话一律 404，不泄露存在性。
    """
    rows = get_session_records(user["id"], session_id)
    if not rows:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    messages: list[dict] = []
    for r in rows:
        messages.append({"role": "user", "content": r["question"], "time": r["created_at"]})
        if r.get("answer"):
            try:
                sources = json.loads(r["sources"]) if r.get("sources") else []
            except json.JSONDecodeError:
                sources = []
            messages.append(
                {
                    "role": "assistant",
                    "content": r["answer"],
                    "sources": sources,
                    "time": r["created_at"],
                    "qa_id": r["id"],
                    "rating": r["result_evaluation"],
                }
            )
    return {"session_id": session_id, "messages": messages}


class EvaluationRequest(BaseModel):
    # 与 qa_record.result_evaluation 枚举一致：赞 / 踩 / 空（撤销，写回默认'无'）
    evaluation: str = Field(pattern="^(|赞|踩)$")


@router.put("/qa/{qa_id}/evaluation")
def rate_qa(qa_id: int, req: EvaluationRequest, user: dict = Depends(get_current_user)) -> dict:
    """C 端对回答点赞/点踩（再点一次撤销）；越权与不存在的记录一律 404。"""
    value = req.evaluation or "无"
    updated = set_result_evaluation(qa_id, user["id"], value)
    if not updated:
        raise HTTPException(status_code=404, detail="问答记录不存在或无权访问")
    return {"evaluation": value}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, user: dict = Depends(get_current_user)) -> dict:
    """删除整组历史对话（该会话全部问答记录，连带 B 端不再可见）。"""
    deleted = delete_user_session(user["id"], session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    return {"deleted": deleted}


@router.delete("/sessions")
def delete_all_sessions(user: dict = Depends(get_current_user)) -> dict:
    """清空当前用户的全部对话（不可恢复；流式进行中的记录会话照常落库不受影响）。"""
    return {"deleted": delete_all_user_sessions(user["id"])}
