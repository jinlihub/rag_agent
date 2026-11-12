"""C 端问答（FR-03~05、FR-08）：登录后流式问答，问答记录落库。"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from rag_agent.agent.memory import build_chat_history
from rag_agent.agent.runner import run_agent_stream
from rag_agent.api.deps import get_current_user
from rag_agent.clients.model_catalog import resolve_answer_model, resolve_deep_thinking_model
from rag_agent.observability import trace_qa
from rag_agent.store import create_qa_record, finish_qa_record

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    web_search: bool = False  # 前端"联网搜索"开关：开启后必查本地+联网
    session_id: str | None = Field(default=None, max_length=64)  # 前端生成的会话 ID，对话历史按会话聚合
    model: str | None = Field(default=None, max_length=64)  # 前端"LLM 选择"：回答文本问题用的模型，空=默认
    deep_thinking: bool = False  # 前端"深度思考"开关：最终作答调高思考强度（DeepSeek 切 reasoner 模型）


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat")
def chat(req: ChatRequest, user: dict = Depends(get_current_user)) -> StreamingResponse:
    question = req.question.strip()
    try:
        # 只校验合法性（须在候选清单内）；工具轮仍用轻量模型，选择只影响最终作答
        answer_model = resolve_answer_model(req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # 深度思考可能切换实际模型（DeepSeek → reasoner），meta 里报告真正使用的模型
    effective_model = resolve_deep_thinking_model(answer_model) if req.deep_thinking else answer_model
    qa_id = create_qa_record(user["id"], question, req.session_id)  # 提问即落库，修改时间随维护操作刷新

    def gen() -> Iterator[str]:
        answer_parts: list[str] = []
        sources: list[dict] = []
        tools: list[str] = []  # 本次实际调用的工具（供追踪上报）
        stages: list[dict] = []
        total_seconds: float | None = None
        yield _sse({"type": "meta", "qa_id": qa_id, "model": effective_model})  # 供前端关联收藏/评价
        # 会话历史（旧组=滚动摘要、近组=逐字）；构建含压缩调用，失败降级为无历史
        t_hist = time.perf_counter()
        history: list[dict[str, str]] = []
        if req.session_id:
            try:
                history = build_chat_history(user["id"], req.session_id, before_qa_id=qa_id)
            except Exception:  # noqa: BLE001 —— 历史属于增强，任何失败不阻断本次问答
                history = []
        history_secs = time.perf_counter() - t_hist
        try:
            for event in run_agent_stream(
                question,
                history=history,
                allow_web=req.web_search,
                answer_model=answer_model,
                deep_thinking=req.deep_thinking,
            ):
                if event["type"] == "delta":
                    answer_parts.append(event["text"])
                elif event["type"] == "sources":
                    sources = event.get("items", [])
                elif event["type"] == "status" and event.get("stage") == "tool_call":
                    tools.append(event.get("tool", ""))
                elif event["type"] == "timing":
                    # 历史构建（含压缩）耗时计入总用时；太短（<0.05s）就不单列明细
                    if history_secs >= 0.05:
                        event["stages"] = [{"key": "history", "seconds": round(history_secs, 2)}, *event["stages"]]
                        event["total"] = round(event["total"] + history_secs, 2)
                    stages = event["stages"]
                    total_seconds = event["total"]
                yield _sse(event)
        except Exception as e:  # noqa: BLE001 —— 兜底：异常也以 SSE 事件形式返回
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            answer = "".join(answer_parts)
            if answer:
                finish_qa_record(qa_id, answer, json.dumps(sources, ensure_ascii=False))
                trace_qa(
                    question=question,
                    answer=answer,
                    model=effective_model,
                    tools=list(dict.fromkeys(t for t in tools if t)),
                    sources=sources,
                    stages=stages,
                    total_seconds=total_seconds,
                    session_id=req.session_id,
                    user_id=user["id"],
                )
        yield _sse({"type": "done"})

    # X-Accel-Buffering: no —— 预留 Nginx 代理时不攒包
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
