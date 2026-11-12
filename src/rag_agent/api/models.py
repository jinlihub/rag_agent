"""可选回答模型清单：前端「LLM 选择」按钮的数据源（含可用性探测结果）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from rag_agent.api.deps import get_current_user
from rag_agent.clients.model_catalog import list_payload

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models")
def get_models(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """候选模型 + 默认项 + 可用性（未探完时 available=null，前端稍后重取）。"""
    return list_payload()
