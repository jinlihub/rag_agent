"""FastAPI 入口：认证 / C 端问答（SSE）/ 对话历史 / B 端维护 / 埋点 / 模型清单 / 健康检查。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rag_agent.api import admin, auth, chat, history, models, tracking, vision
from rag_agent.config import get_settings
from rag_agent.observability.system_monitor import install_log_capture

# 在 uvicorn 完成日志配置后挂载环形缓冲，供 /api/admin/system 返回近期日志
install_log_capture()

app = FastAPI(title="rag-agent · 招投标智能问答", version="0.2.0")

# 开发期放行前端 dev server（Vite 默认 5173）；生产由 Nginx 同域部署，收紧 origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(history.router)
app.include_router(models.router)
app.include_router(admin.router)
app.include_router(tracking.router)
app.include_router(vision.router)


@app.get("/api/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "llm_configured": s.llm_configured,
        "embedding_configured": s.embedding_configured,
        "auth_configured": bool(s.auth_secret),
        "tavily_configured": bool(s.tavily_api_key),
    }
