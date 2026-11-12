"""B 端维护后台接口（FR-09~14）：筛选列表 + 标记正确 / 编辑 / 不需要维护 + 系统监控。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from rag_agent.api.deps import require_admin
from rag_agent.faq_expansion import promote_cluster_to_faq, promote_qa_to_faq
from rag_agent.observability.system_monitor import get_system_metrics
from rag_agent.store import (
    approve_qa_cluster,
    list_qa_clusters,
    list_qa_records,
    qa_record_exists,
    set_maintain_status,
    update_qa_answer,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/qa")
def list_qa(
    username: str | None = None,
    keyword: str | None = None,
    user_type: str | None = None,
    maintain_status: str | None = None,
    result_evaluation: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """多条件组合查询问答记录（维护结果/结果评价默认值由前端按设计稿传入）。"""
    return list_qa_records(
        username=username,
        keyword=keyword,
        user_type=user_type,
        maintain_status=maintain_status,
        result_evaluation=result_evaluation,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


class AnswerUpdate(BaseModel):
    answer: str = Field(min_length=1, max_length=20000)


@router.put("/qa/{qa_id}")
def edit_answer(qa_id: int, req: AnswerUpdate) -> dict:
    """编辑回答并保存 → 维护状态置为「已维护」（状态机 §6.2）。

    管理员改过的回答是最高质量素材，同步沉淀进 FAQ 并后台重建 faq 索引。
    """
    # MySQL 在「答案与状态都没变化」时 rowcount 也是 0，需要再确认记录是否存在
    if update_qa_answer(qa_id, req.answer.strip()) == 0 and not qa_record_exists(qa_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"问答记录不存在: {qa_id}")
    return {
        "id": qa_id,
        "maintain_status": "已维护",
        "faq": promote_qa_to_faq(qa_id, prefer_draft=False),
    }


def _transition(qa_id: int, new_status: str, message: str) -> dict:
    # 已是目标状态时 MySQL rowcount=0，此时记录仍存在，按幂等成功处理
    if set_maintain_status(qa_id, new_status) == 0 and not qa_record_exists(qa_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"问答记录不存在: {qa_id}")
    return {"id": qa_id, "maintain_status": new_status, "message": message}


@router.post("/qa/{qa_id}/mark-correct")
def mark_correct(qa_id: int) -> dict:
    """标记正确 → 沉淀为 FAQ（有聚类草稿用草稿，否则用原回答）。"""
    result = _transition(qa_id, "已维护", "已标记正确")
    result["faq"] = promote_qa_to_faq(qa_id)
    return result


@router.post("/qa/{qa_id}/no-need")
def no_need(qa_id: int) -> dict:
    return _transition(qa_id, "不需要维护", "已标记为不需要维护")


@router.get("/clusters")
def list_clusters() -> dict:
    """未维护问题的聚类视图：簇大小、问题样例、共用草稿、成员 qa_id。

    草稿由 scripts/cluster_unmaintained.py 离线生成（几百条要跑几十分钟），
    本接口只读，不做同步聚类。
    """
    return list_qa_clusters()


@router.post("/clusters/{cluster_id}/approve")
def approve_cluster(cluster_id: int) -> dict:
    """一键确认：同簇（同草稿）的未维护记录批量置为「已维护」。

    同时用簇代表问题 + 共用草稿沉淀一条 FAQ（只插一条，不按成员数重复）。
    """
    updated = approve_qa_cluster(cluster_id)
    if updated == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"簇不存在或已处理: {cluster_id}")
    return {
        "id": cluster_id,
        "updated": updated,
        "maintain_status": "已维护",
        "faq": promote_cluster_to_faq(cluster_id),
    }


@router.get("/system")
def system_status(log_limit: int = Query(default=100, ge=0, le=500)) -> dict:
    """系统监控快照：CPU/内存/磁盘/GPU/进程与近期日志（仅管理员）。"""
    return get_system_metrics(log_limit=log_limit)
