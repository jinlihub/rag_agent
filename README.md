# rag-agent · 招投标智能问答机器人

基于 LLM + Agent + RAG 的招投标智能问答服务。C 端对话问答 + B 端维护后台。

文档见 [docs/开发文档.md](docs/开发文档.md)（做什么）、[docs/技术栈.md](docs/技术栈.md)（用什么做）、[docs/部署.md](docs/部署.md)（怎么上线）。

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置环境变量（数据库 / LLM API）
cp .env.example .env   # 然后填写 .env

# 3. 导入训练数据（标的物 8790 条 + 问答对 82 条）到 MySQL
uv run python scripts/import_xlsx_to_mysql.py

# 4. 初始化应用表（user_account / qa_record / tracking_event，并播种管理员 admin/admin123）
uv run python scripts/init_db.py

# 5. 构建知识库向量索引（法条 / 政策 / 问答对，需 LLM embedding 可用）
uv run python scripts/build_index.py

# 6. 启动服务（一键脚本，同时拉起前后端，就绪后自动打开浏览器）
bash start.sh              # 另有: bash start.sh status | stop | restart

#    或只启后端（手动方式，前端见下一节）
uv run uvicorn rag_agent.api.main:app --host 127.0.0.1 --port 8000 --reload --reload-dir src

# 7. 冒烟测试
uv run python scripts/smoke_test.py "近半年安徽合肥区域有哪些企业中标？"        # RAG 能力层（免登录）
uv run python scripts/app_smoke_test.py                                   # 应用层全链路（注册/问答/后台维护）
```

## 前端（Vue 3 + Element Plus）

```bash
cd frontend
npm install        # 首次
npm run dev        # http://localhost:5173（/api 代理到 127.0.0.1:8000）
npm run build      # 类型检查 + 产物构建
```

账号：测试管理员 `admin / admin123`（scripts/init_db.py 播种）；C 端在登录页注册。

| 路由 | 页面 |
| --- | --- |
| `/login` | 登录 / 注册 |
| `/chat` | C 端问答（SSE 流式渲染、来源引用、发送埋点） |
| `/admin/qa-list` | B 端维护后台（筛选 / 标记正确 / 编辑 / 不需要维护 / 分页） |
