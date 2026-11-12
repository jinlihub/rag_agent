# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

招投标智能问答机器人：FastAPI + Vue 3，RAG + ReAct Agent。C 端流式问答（SSE）、B 端问答维护后台。数据分布在 MySQL（业务表/企业/项目）、PostgreSQL（含「标的物」列的项目表，已启用）、Neo4j（采购交易图谱，可选）与文件型向量索引（`data/index/`）。设计文档在 `docs/`：`系统架构图.md`（分层总览 + 主链路/维护飞轮/部署图，图片在 `docs/assets/`）、`开发文档.md`（模块与接口）、`核心算法.md`（检索/Agent）、`组件工作机制.md`、`技术栈.md`（选型与现状）。

## 常用命令

```bash
# 后端依赖与环境
uv sync
cp .env.example .env          # 配置数据库 / LLM / 可选项；改 .env 后必须重启

# 首次初始化（顺序不可颠倒）
uv run python scripts/import_xlsx_to_mysql.py   # 导入标的物与 FAQ 到 MySQL（源 xlsx 路径见脚本头部）
uv run python scripts/init_db.py                # 建 user_account / qa_record / tracking_event / session_memory，播种 admin/admin123
uv run python scripts/build_index.py            # 构建 data/index/{legal,policy,faq}.npz + .meta.jsonl
uv run python src/database/to_postgresql.py     # 导入 PostgreSQL（含标的物列，8789 行）；需先启动 PG 服务
uv run python scripts/import_to_neo4j.py        # 可选：导入 Neo4j 采购交易图谱

# 启动（Git Bash；同时拉起前后端并开浏览器）
bash start.sh                 # 另有 status / stop / restart
# 只启后端：
uv run uvicorn rag_agent.api.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir src

# 前端
cd frontend
npm install
npm run dev                   # http://localhost:5173，/api 代理到 127.0.0.1:8000（strictPort）
npm run build                 # vue-tsc --noEmit + vite build

# B 端维护：未维护问题聚类 + 草稿（离线跑，几百条要几十分钟）
uv run python scripts/cluster_unmaintained.py              # 全量，余弦阈值 0.85
uv run python scripts/cluster_unmaintained.py --limit 5    # 只跑最近 5 条（冒烟）
uv run python scripts/cluster_unmaintained.py --dry-run    # 只聚类，不调模型不写库

# 验证（仓库没有 pytest / lint，下列脚本就是测试入口）
uv run python scripts/tools_smoke_test.py --dry          # 最快：工具 Schema/注册表/容错，不连库不调模型
uv run python scripts/tools_smoke_test.py                # 结构断言 + 真实工具执行
uv run python scripts/smoke_test.py "你好"                # Agent 能力层：chitchat 分支
uv run python scripts/smoke_test.py "供应商提出质疑的时限是多少天？"   # faq 分支
uv run python scripts/smoke_test.py "近半年安徽合肥区域有哪些企业中标？" # complex 分支
uv run python scripts/smoke_test.py --web "…"            # 开联网搜索
uv run python scripts/smoke_test.py --deep "…"           # 开深度思考
uv run python scripts/app_smoke_test.py                  # 应用层全链路（会写库、真实调用一次 LLM）
uv run python evals/run_eval.py --limit 3                # 评估冒烟；全量见 evals/README.md

# 语法检查（无测试框架时的下限）
uv run python -m compileall -q src
```

## 问答主链路（改问答/Agent 时先读这条）

1. `POST /api/chat`（`src/rag_agent/api/chat.py`）校验模型 id → 立即 `create_qa_record` 落问题 → 构建会话历史 → `agent.runner.run_agent_stream`。
2. `Agent.run_stream`（`src/rag_agent/agent/agent.py`）先做**意图路由**（`agent/intent.py`）：寒暄用正则零成本判定；其余用工具轮小模型单标签分类 `faq` / `complex`，失败一律降级 `complex`。
3. `chitchat` 不调工具直接短答；`faq` 只查一次 `search_bidding_knowledge(scope="faq")`，质量 `ok` 才直接作答，否则退回完整循环；`complex` 走最多 3 轮 ReAct（多工具并行执行，`assess_quality` 不达标会回填质量结论驱动换参/换工具）。指代不明/实体歧义/时间口径模糊时模型调用 `ask_user`，或代码识别出无历史的“那家公司/那个项目”，立即发 `clarify` 事件并结束本轮（不生成回答）。
4. 联网开关开启且模型没联网时，会强制补一次 Tavily（`search_web`）或 Exa（`search_web_exa`）。
5. 最终作答按分支选择收束提示词（寒暄/FAQ/空结果/部分失败/常规），流式输出 `delta` 与 `reasoning`；企业画像类问题（`prompt.py` 的 `is_company_profile_question`）追加「概况/经营状况/中标表现/风险提示」四节模板。
6. `finally` 中回填答案与来源，并调用 `observability/langfuse_tracer.trace_qa`（可选，失败静默）。

SSE 事件契约见 `agent.py` 模块 docstring（`status` / `delta` / `reasoning` / `sources` / `timing` / `error` / `done`），API 层额外在最前面发 `meta`；前端镜像在 `frontend/src/types/index.ts`。新增或修改事件必须同步后端、`frontend/src/api/chat.ts` 的解析与 `ChatView.vue` 的分发。`timing` 的 key 为 `history | routing | analysis | tool | generating`。

## 工具与检索

- **工具层**（`src/rag_agent/tools/`）：参数用 Pydantic `ToolArgs` 子类声明，`BaseTool.openai_schema` 自动生成 function calling Schema；`execute()` 把参数错误与执行异常都折叠成 `{"error": ...}`。新工具继承 `BaseTool`、在 `rag_tools.py` 注册进 `TOOL_REGISTRY`，并按需加入 `WEB_TOOLS`（联网工具会随请求开关裁剪）。
- **内置能力**：`search_bidding_knowledge`（法条/政策/FAQ 混合检索）、`search_knowledge_graph`（MySQL 企业/中标/违规关联；wins 分支附 `wins_summary` 全量中标汇总，支撑企业画像）、`search_postgresql`（结构化项目检索，PG 不可用时自动降级 MySQL，但 MySQL 无标的物列）、`graph_query`（Neo4j 预定义只读模板，模型不能写 Cypher）、`search_web`（Tavily）、`search_web_exa`（Exa MCP，配置 Key 才注册）、`ask_user`（主动澄清，不查数据，参数 `question` + `options`）。
- **混合检索**（`retrieval/`）：dense = numpy 归一化向量点积（`data/index/*.npz`）；sparse = 字符 bigram BM25（`sparse.py`），两路共用 `.meta.jsonl` 的**行号**对齐；`fusion.py` 按法规/概念/通用三类问题加权 RRF；`rerank.py` 默认用工具轮小模型 listwise 重排（候选 ≥8 才触发），关闭/失败回退融合序。索引文件被 gitignore，需本地构建。
- **结果质量关卡**：`BaseTool.assess_quality` 返回 `ok|empty|weak|error`，是 FAQ 快速路径与 ReAct 收束的依据；`collect_sources` 过滤弱结果、去重并封顶 20 条来源。

## 数据与配置

- `src/rag_agent/store.py` 是应用表（用户/问答/会话摘要/埋点）的唯一数据访问层；`database.py` 提供 MySQL 短连接与 `query_all`；`retrieval/sql_search.py` 是项目/企业结构化查询。
- MySQL 表：`user_account`、`qa_record`、`session_memory`、`tracking_event`、`bid_subjects`（18 列，无标的物）、`enterprise_企业信息`、`enterprise_违法违规记录`、`policy_政策文件`；PostgreSQL 的 `bid_subjects` 多一个 `subject` 列。`qa_record.answer_draft` 存未维护问题聚类草稿（同簇共用），由 `scripts/init_db.py` 幂等 ALTER 补齐。
- B 端确认动作（编辑保存 / 标记正确 / 按簇确认）会自动把合格问答对写入 `faq_qa_pairs`（`faq_expansion.py` 粗筛，同问题覆盖更新），并由后台线程经 `retrieval/faq_index.py` 只重算 faq 索引（~80 条，秒级），完成后清 `get_store` / `get_sparse` 缓存。`scripts/build_index.py` 的 faq 分支复用同一实现。
- `src/rag_agent/config.py` 的 `get_settings()` 是配置唯一真相：从仓库根 `.env` 读取、`lru_cache` 进程级缓存，启动后改配置必须重启。`.env.example` 后半段有大量历史粘贴项，**不要据此判断功能现状**（例如实际读的是 `LANGFUSE_HOST`，不是 `LANGFUSE_BASE_URL`；`LANGFUSE_CAPTURE_CONTENT` 等未被读取）。
- 外部依赖缺失是预期状态：Neo4j / PostgreSQL / 重排 / 联网 / Langfuse 任一不可用时，工具或功能返回可读提示并降级，不允许让问答主流程崩溃。

## 会话记忆

`agent/memory.py`：最近 4 组问答逐字保留；更早的组攒够 3 组后，后台线程合并进 `session_memory` 的滚动摘要，摘要完成前用旧摘要 + 逐字顶上。摘要失败只影响下次能否用摘要，绝不阻断本次问答。

## 前端

- Vue 3 `<script setup>` + Pinia（仅 `auth` store）+ Vue Router（History 模式，守卫在 `router/index.ts`）；路由：`/login` 登录注册、`/chat` 问答、`/admin/qa-list` 维护后台（需管理员）。后台接口由后端 `require_admin` 兜底。
- 常规请求走 `api/http.ts` 的 Axios 拦截器；问答走 `api/chat.ts` 的原生 `fetch` + `ReadableStream` 逐帧解析（POST SSE）。
- `ChatView.vue` 是最重的页面：流式事件分发、来源面板、阶段耗时、深度思考折叠、历史会话、模型选择都在这里。Element Plus 组件由 `unplugin-vue-components` 自动注册。
- `QaListView.vue` 有两个页签：「问答列表」逐条维护；「按簇处理」读取后端聚类（草稿由离线脚本生成，同簇共用），一键确认把簇内未维护记录批量置为已维护。
- Token 存 localStorage；401 统一跳登录。

## 评估

`evals/run_eval.py` 直接调用 `run_agent_stream`（不写问答记录），自动指标（工具命中/关键词/耗时）与 DeepSeek 独立评审（正确性/忠实度/完整性，1-5 分）合并输出 JSONL + Markdown + Excel 到 `evals/reports/`。数据集在 `evals/dataset.jsonl`，加用例直接追加一行。

## 约定与易踩点

- 代码注释、docstring、文档均为中文；改动时保持同样密度与风格，不要把解释性注释删成光秃秃实现。
- 仓库当前没有 pytest / ESLint 配置，验证靠 smoke 脚本、`evals/` 与 `vue-tsc`；技术栈文档已明确不引入 LangChain / LlamaIndex / 向量数据库，除非有明确需求，不要为单个功能引入框架。
- 新增/修改检索参数时同步 `docs/核心算法.md`；新增接口/事件时同步 `docs/开发文档.md` 与 `docs/组件工作机制.md`。
- 起始页与测试账号：`http://localhost:5173/chat`，`admin / admin123`。
- PPT 产物 `docs/产品设计与技术架构.pptx` 由 `uv run --with python-pptx python scripts/make_ppt.py` 生成；`scripts/preview_ppt.py` 用 PowerPoint COM 逐页导出 PNG 质检。
