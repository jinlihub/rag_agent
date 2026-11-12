"""集中管理环境变量配置。所有配置从仓库根目录的 .env 读取。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# .env 固定取仓库根目录（src 布局下启动位置不定，不能用相对 cwd）
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # MySQL
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    # 对话模型（OpenAI 兼容）
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    # 向量模型（缺省复用对话模型配置）
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    # 向量索引目录
    index_dir: Path
    # JWT 签名密钥
    auth_secret: str
    # glm-4.5/4.6 的 thinking 开关（enabled/disabled），默认关闭换响应速度
    llm_tool_thinking: str
    llm_final_thinking: str
    # 前端「深度思考」开关打开时的思考强度：
    # 智谱 glm-5.3 系取 low/high/max（较早型号自动映射为 enabled）
    llm_deep_thinking: str
    # DeepSeek 无 thinking 透传参数：深度思考开启时最终作答切到该模型
    deepseek_thinking_model: str
    # 工具轮模型（选工具/拼参数用小模型更快更省；空 = 复用 LLM_MODEL）
    llm_tool_model: str
    # LLM 客户端层：厂商选择（zai=智谱[默认] / deepseek）
    llm_provider: str
    # 前端「LLM 选择」候选清单（`id:标签:说明` 逗号分隔；空 = 用内置候选表）
    llm_model_choices: str
    # DeepSeek（LLM_PROVIDER=deepseek 时启用）
    deepseek_api_key: str
    deepseek_base_url: str
    # 检索重排序（Rerank）：off / api / llm
    rerank_backend: str
    rerank_base_url: str
    rerank_api_key: str
    rerank_model: str
    rerank_timeout: float
    # 图片解析（视觉模型，zai SDK）
    vision_model: str
    # Tavily 联网搜索（本地知识库无答案时的补充）
    tavily_api_key: str
    tavily_timeout: float
    # Exa MCP 联网搜索（标准 MCP server，作为 Tavily 之外的第二个搜索引擎）
    exa_api_key: str
    exa_mcp_url: str
    exa_timeout: float
    # Langfuse 可观测性（问答 trace 上报；未启用或缺 key 时整体跳过）
    langfuse_enabled: bool
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str
    # Neo4j 图数据库（GraphRAG；空 uri 视为未启用，工具返回可读提示）
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_base_url and self.embedding_api_key and self.embedding_model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    emb_base = os.getenv("EMBEDDING_BASE_URL") or os.getenv("LLM_BASE_URL") or ""
    emb_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY") or ""
    return Settings(
        db_host=os.getenv("DB_HOST", "127.0.0.1"),
        db_port=int(os.getenv("DB_PORT", "3306")),
        db_user=os.getenv("DB_USER", "root"),
        db_password=os.getenv("DB_PASSWORD", ""),
        db_name=os.getenv("DB_NAME", "rag_cleaned"),
        llm_base_url=os.getenv("LLM_BASE_URL", ""),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", ""),
        embedding_base_url=emb_base,
        embedding_api_key=emb_key,
        embedding_model=os.getenv("EMBEDDING_MODEL", ""),
        index_dir=Path(os.getenv("INDEX_DIR", str(_ROOT / "data" / "index"))),
        auth_secret=os.getenv("AUTH_SECRET", ""),
        llm_tool_thinking=os.getenv("LLM_TOOL_THINKING", "disabled"),
        llm_final_thinking=os.getenv("LLM_FINAL_THINKING", "disabled"),
        llm_deep_thinking=os.getenv("LLM_DEEP_THINKING", "high"),
        deepseek_thinking_model=os.getenv("DEEPSEEK_THINKING_MODEL", "deepseek-reasoner"),
        llm_tool_model=os.getenv("LLM_TOOL_MODEL", ""),
        llm_provider=os.getenv("LLM_PROVIDER", "zai"),
        llm_model_choices=os.getenv("LLM_MODEL_CHOICES", ""),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", ""),
        rerank_backend=os.getenv("RERANK_BACKEND", "llm"),
        rerank_base_url=os.getenv("RERANK_BASE_URL", ""),
        rerank_api_key=os.getenv("RERANK_API_KEY", ""),
        rerank_model=os.getenv("RERANK_MODEL", ""),
        rerank_timeout=float(os.getenv("RERANK_TIMEOUT", "8")),
        vision_model=os.getenv("VISION_MODEL", "glm-4.6v-flashx"),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        tavily_timeout=float(os.getenv("TAVILY_TIMEOUT", "10")),
        exa_api_key=os.getenv("EXA_API_KEY", ""),
        exa_mcp_url=os.getenv("EXA_MCP_URL", "https://mcp.exa.ai/mcp"),
        exa_timeout=float(os.getenv("EXA_TIMEOUT", "15")),
        langfuse_enabled=os.getenv("LANGFUSE_ENABLED", "false").strip().lower()
        in ("1", "true", "yes", "on"),
        langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
        langfuse_host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        neo4j_uri=os.getenv("NEO4J_URI", ""),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", ""),
    )
