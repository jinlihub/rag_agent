"""数据埋点上报（FR-15，PRD §数据埋点）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from rag_agent.api.deps import get_current_user
from rag_agent.store import insert_tracking_event

router = APIRouter(prefix="/api", tags=["tracking"])


class TrackRequest(BaseModel):
    # PRD 定义：事件名"发送"按钮 / 属性名"页面点击" / 属性值"次数"；其余事件为建议扩展
    event_name: str = Field(min_length=1, max_length=64, examples=['"发送"按钮'])
    prop_name: str = Field(min_length=1, max_length=64, examples=["页面点击"])
    prop_value: str = Field(min_length=1, max_length=32, examples=["次数"])
    session_id: str | None = Field(default=None, max_length=64)
    page: str | None = Field(default=None, max_length=64, examples=["/chat"])

    @model_validator(mode="after")
    def _check_default_event(self) -> "TrackRequest":
        # 首期仅 PRD 定义的一个事件，其余值拒绝入库，保证埋点口径与 PRD 一致
        allowed = {('"发送"按钮', "页面点击", "次数"), ("发送按钮", "页面点击", "次数")}
        if (self.event_name, self.prop_name, self.prop_value) not in allowed:
            raise ValueError("埋点口径须与 PRD §数据埋点一致：事件名'发送'按钮 / 属性名'页面点击' / 属性值'次数'")
        return self


@router.post("/track")
def track(req: TrackRequest, user: dict = Depends(get_current_user)) -> dict:
    insert_tracking_event(
        event_name=req.event_name,
        prop_name=req.prop_name,
        prop_value=req.prop_value,
        user_id=user["id"],
        session_id=req.session_id,
        page=req.page,
    )
    return {"status": "ok"}
