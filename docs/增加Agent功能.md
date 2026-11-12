# 招投标问答机器人 — Agent 功能扩展规划

> 基于 `src/rag_agent/agent/agent.py` 现有 ReAct 工具循环架构与产品定位（docs/开发文档.md）梳理，按价值与落地难度分级，供排期参考。
> 最后更新：2026-11-04（补充已完成项与落地现状）。
> 状态图例：✅ 已完成｜🟡 部分完成｜⬜ 未开始

## 现状：Agent 已具备的能力

| 能力 | 现状 |
|---|---|
| 工具循环 | 最多 3 轮 ReAct（`MAX_TOOL_ROUNDS=3`），一轮多工具并行；6 个基础工具（`search_bidding_knowledge` / `search_knowledge_graph` / `search_postgresql` / `graph_query` / `search_web` / `ask_user`）+ 配置 Key 后的 `search_web_exa` |
| 两段式模型 | 工具轮轻量模型（`LLM_TOOL_MODEL`，默认 glm-4.5-air）选工具/拼参数 → 最终作答模型可选（前端 LLM 选择 / `LLM_MODEL`），支持深度思考（`reasoning` 事件） |
| 过程可见 | SSE `status`（thinking / analysis / quality / tool_call / generating）+ `timing` 阶段耗时 + 深度思考 `reasoning` 折叠展示 |
| 来源引用 | `collect_sources` 去重聚合、弱结果过滤、封顶 20 条，回答下方展示来源芯片 |
| 防呆 | 数据覆盖范围注入 prompt、服务端日期夹取（`clamp_date_range`）、结果质量关卡（`ok/empty/weak/error`）、主动澄清（`ask_user` → `clarify`） |
| 会话记忆 | 最近 4 组问答逐字保留，更早的组滚动压缩为会话摘要（`agent/memory.py`） |
| 图表回答 | 聚合查询由代码生成 ECharts option，`chart` SSE 事件 + 前端渲染 |
| 企业画像 | `search_knowledge_graph(relation=all)` 取五类素材 + `wins_summary` 中标汇总，按四节模板输出 |
| B 端维护飞轮 | `scripts/cluster_unmaintained.py` 离线聚类并起草共用回答，管理端「按簇处理」一键确认；确认后的优质问答自动写入 `faq_qa_pairs` 并秒级重建 faq 索引 |
| 评测闭环 | `evals/run_eval.py`：自动指标（工具命中/关键词/耗时）+ DeepSeek 独立评审，输出 JSONL / Markdown / Excel |

主要短板：**查询改写缺失、无语义缓存、无订阅/报告等主动服务、数据仅覆盖 2023-10 快照、无文档级 RAG**。下面的功能按这些缺口排列。

---

## 一、对话与交互增强 —— P0

### 1. 多轮对话记忆 + 查询改写（🟡 部分落地：多轮记忆已上线，查询改写未实现）
- **场景**：用户问"合肥近半年有哪些企业中标？"，接着问"第一家的金额是多少？"——当前每问独立，追问必然答非所问。
- **实现**：请求体携带 `session_id` + 最近几轮历史；`run_agent_stream(question, history)` 把历史拼进 messages；工具轮之前先用 glm-4.5-air 做一次**查询改写**，把指代性追问改写成独立查询（"第一家的金额" → "合肥 2023-10 中标金额第一名"）。
- **改动**：`api/chat.py`（请求模型、按会话取历史）、`agent/agent.py`、`agent/memory.py`、`store.py`、前端 `ChatView.vue`（随请求携带消息数组）。
- **落地情况**：多轮记忆已上线——`api/chat.py` 按 `session_id` 取历史传入 `run_agent_stream`；`agent/memory.py` 最近 4 组逐字保留，更早的组攒够 3 组后台压缩进 `session_memory` 滚动摘要，摘要失败不影响本次问答。**查询改写未实现**：指代性追问依赖模型结合历史自行理解，确实无法解析时由 `ask_user` 主动澄清兜底。
- **工作量**：中（2~3 天）｜这是所有后续对话能力的地基；剩余查询改写约半天。

### 2. 主动澄清（Ask-user 反问）✅ 已落地（2026-11-04）
- **场景**："帮我查一下那家公司"（指代不明）、同名企业歧义、"最近"但无时间语境——与其瞎猜一个结果，Agent 反问一句更专业。
- **实现**：新增 `ask_user` 工具（参数 `question` + `options`，不查任何数据）；`agent/agent.py` 的 `run_stream` 检测到该调用后立即发出 `clarify` 事件并结束本轮，不生成回答。SSE 契约新增 `{"type":"clarify","question":"…","options":[…]}`；前端渲染成带快捷选项的气泡，点击选项即作为下一问发送。
- **改动**：`tools/ask_user.py`（新增）、`tools/rag_tools.py`（注册）、`agent/agent.py`（追问分支 + 无历史指代兜底 + 分析文本澄清兜底）、`prompt.py`（规则 5：指代不明/实体歧义/时间口径模糊才问）、SSE 契约、前端 `types/index.ts` + `ChatView.vue`。
- **落地情况**：三类触发条件（指代不明、实体歧义、时间口径模糊）均已生效；options 只能来自对话历史或检索结果，没有真实候选时留空，禁止编造企业名/项目名。实测「帮我查一下那家公司」稳定输出澄清气泡，点击快捷选项可作为下一问发送。
- **工作量**：中。

### 3. 意图路由前置（✅ 已落地 2026-11-03）
- **场景**："你好""谢谢"不该进完整工具循环；纯 FAQ 问题不必让模型在 6 个基础工具里挑。
- **实现**：进 Agent 循环前先走轻量路由（`agent/intent.py`）：① 寒暄/致谢/问身份用正则整句匹配 → 不调工具，直接短答；② 其余用工具轮小模型单标签分类，`faq` → 只调一次 `search_bidding_knowledge(scope="faq")` 后直接作答；③ `complex` 及分类失败 → 进完整循环。FAQ 检索无可用结果时自动退回完整循环。
- **改动**：`agent/intent.py`（新增）、`agent/agent.py`（前置分支 + `skip_tools`）、`timing.routing` 耗时键、`STAGE_LABELS`。
- **工作量**：小（1 天）｜直接改善"回答时间长"的体感。

---

## 二、检索与回答质量 —— P0~P1

### 4. 空结果自反思重试（Self-reflection）（🟡 部分落地：质量关卡已上线，未代码级强制重试）
- **场景**：关键词太窄查到 0 条时，现在模型会直接编一句兜底话术结束；应该自动换关键词/放宽条件再试一次。
- **实现**：`execute_tool` 返回 `total==0` 时，向 messages 注入一条系统注记"0 命中，请换更宽泛关键词或减少筛选条件重试（还剩 X 次机会）"，代码级保证至少重试一轮。
- **改动**：`agent/agent.py` + `agent/tools/base.py`（`assess_quality`）。
- **落地情况**：每个工具执行后都会做结果质量判定（`ok/empty/weak/error`），不达标时发 `quality` 事件并把结论回填给模型，提示词规则 3 要求换关键词/换工具/换信息源；空结果最终由 `_EMPTY_NUDGE` 如实告知用户。**尚未做到**代码级强制重试一轮——模型判定信息不足时仍可能直接收束。
- **工作量**：小（半天，补强制重试逻辑）。

### 5. 结果重排（Rerank）✅ 已落地（2026-10-29）
- **场景**：法条/政策向量召回 Top10 里真正相关的往往只有 2~3 条；重排后引用更准、prompt 更短更省 token。
- **实现**：`retrieval/rerank.py` —— 向量过量召回（top_k×3，上限 16 条）→ 二次排序 → 截取 top_k，重排分回填 `score`。后端 `RERANK_BACKEND` 可切换：`llm`（默认，工具轮小模型 listwise 打分，单次 ~1.8s，零新增依赖）/ `api`（Jina/Cohere/SiliconFlow 风格 /rerank 接口，供后续接 bge-reranker）/ `off`（关闭）。失败一律回退向量序。
- **实测**：智谱 /rerank 接口判别度不足（候选分数全 ≈1.0，无关对照 0.92）故不采用；glm-4.5-air 打分判别清晰——「质疑时限」问题中含答案条文全部 10 分并顶到最前，程序性条文 0 分；端到端 14.7s（约 +1s）。

### 6. 语义缓存（⬜ 未实现）
- **场景**：FAQ 类问题重复率高（"质疑时限是多少天"每天都有人问），近似问题直接回放缓存答案，省时省钱。
- **实现**：问题 embedding 与缓存键相似度 > 0.95 且属于 FAQ/法条类 → 直接发 `sources` + 逐字回放；**日期敏感的 SQL 类查询不缓存**（或短 TTL）。
- **工作量**：小~中。

---

## 三、数据分析与企业洞察 —— P1（本项目差异化最大的一块）

### 7. 聚合统计工具 ✅ 已落地（以 `search_postgresql.group_by` 实现，未单开工具）
- **场景**："合肥哪个区中标项目最多？""各行业中标金额占比？"——现有工具只回 Top-N 明细行，答不了统计问题。
- **实现**：新增 `aggregate_bid_stats` 工具：**白名单模板 SQL**（维度：province/city/category/月份；指标：COUNT、SUM(award_amount)），参数化传参防注入，复用 `clamp_date_range` 夹取时间。
- **落地情况**：没有新增独立工具，而是在 `search_postgresql` 上增加 `group_by: category|month` 参数；设置后走分组统计（PG 优先，失败自动降级 MySQL），由代码生成 `{total, rows, chart}`。维度目前支持类别与月份，地域/行业维度的任意组合尚未开放。
- **改动**：`tools/rag_tools.py`（`PostgresqlArgs.group_by` + 两条分组 SQL + `_chart_spec`）、`prompt.py`（统计类问题引导）。
- **工作量**：中。

### 8. 图表化回答 ✅ 已落地
- **场景**：趋势/占比类问题配图远胜纯文字，演示效果最强。
- **实现**：SSE 契约新增 `{"type":"chart","spec":{…}}` 事件（ECharts option 由聚合工具产出），前端 ChatView 引入 echarts 渲染，与来源芯片并列展示。
- **落地情况**：聚合查询（`group_by=category|month`）由代码生成 ECharts option；`chart` 事件在来源之后发出，前端校验 spec 后用 echarts 渲染在回答气泡内。图表完全由数据计算，不经过模型，避免模型编造图形数据。
- **改动**：`tools/rag_tools.py`（`_chart_spec`）、`agent/agent.py`（`chart` 事件）、`frontend/src/types/index.ts`、`ChatView.vue`。
- **工作量**：中。

### 9. 企业画像 Agent ✅ 已落地（2026-11-04）
- **场景**："XX 公司实力怎么样？"——把企业基本信息 + 违规记录 + 中标历史（次数/总金额/主要采购人）聚合成一页画像。
- **实现**：规划型多工具调用（`search_enterprises` + `search_company_violations` + `search_bid_subjects(winner=公司名)`），prompt 加画像模板分节输出（概况/经营状况/中标表现/风险提示）。
- **落地情况**：项目里没有独立的 `search_enterprises` / `search_company_violations` 工具，工商与违规都在 `search_knowledge_graph` 的 `profile` / `violations` 分支。实际做法是：
  1. 模型用 `search_knowledge_graph(entity=公司名, relation=all)` 一次取回工商/中标/采购/代理/违规五类素材；
  2. `wins` 分支新增 `wins_summary`：除前 `limit` 条明细外，另用不带 LIMIT 的聚合 SQL 返回中标总次数、总金额、主要采购人 TOP3；
  3. `prompt.py` 用正则识别"企业主体词 + 实力/背景/靠谱"类问题（排除"哪些公司/如何判断/资质要求"等列表与规则问法），在系统提示词规则 6 与收束模板中要求按「概况 / 经营状况 / 中标表现 / 风险提示」四节输出；某节无数据时写明"本次未检索到 XX 数据"，禁止主观评级与编造。
- **改动**：`tools/rag_tools.py`（`_wins_summary`）、`agent/prompt.py`（识别 + 模板）、`agent/agent.py`（画像问题收束）、前端 `.answer-md` 标题样式。
- **工作量**：小~中。

---

## 四、主动服务 —— P1~P2

### 10. 订阅与告警 Agent（⬜ 未实现）
- **场景**：企业用户订阅"安徽省 + 信息化类"新公告，每日摘要推送——典型的 B 端付费点。
- **实现**：新表 `subscription(criteria_json, channel, last_sent_at)`；APScheduler 每日跑一次检索、按 `project_no` 去重、站内信/邮件推送 glm-4.5-air 生成的摘要。
- **前提**：公告数据能持续入库（依赖 16）。
- **工作量**：大。

### 11. 分析报告生成 Agent（⬜ 未实现）
- **场景**："生成合肥市近半年中标情况分析报告"——先规划、多轮取数、再写成长报告（总体态势/区域分布/行业分布/重点企业/风险提示），支持导出 Word。
- **实现**：deep 模式（`MAX_TOOL_ROUNDS` 提到 10 + 先出大纲再逐节写）；markdown→docx 导出；配合 7/8 的聚合与图表数据。
- **工作量**：大。

---

## 五、B 端运营飞轮 —— P1（让"维护"从人工变成人机协同）

### 12. 未维护问题聚类 + 答案草稿 ✅ 已落地（2026-11-04）
- **场景**：B 端管理员面对几百条"未维护"无从下手；Agent 先聚类、起草，人只做确认。
- **实现**：离线脚本 `scripts/cluster_unmaintained.py` —— 拉未维护 question → `embed_texts` 向量化 → 余弦 ≥0.85 的「种子 + 质心归并」贪心聚类（纯 numpy，不引 sklearn）→ 每簇起草一条 `answer_draft` 写回簇内全部记录。管理端 `GET /api/admin/clusters` 按草稿归簇展示（问题样例/条数/草稿/qa_ids），`POST /api/admin/clusters/{id}/approve` 批量置为「已维护」；`QaListView.vue` 新增「按簇处理」视图。
- **约束处理**：`qa_record.sources` 只有来源标题、没有完整检索结果，因此起草只用 question + 标题，prompt 明确要求「不确定的细节不写」，不能假装读过项目数据。簇身份 = 草稿内容相同（不新增簇表），簇 id 取簇内最小 `qa_record.id`。
- **改动**：`scripts/cluster_unmaintained.py`（新增）、`scripts/init_db.py`（`answer_draft` 幂等 ALTER）、`store.py`（拉取/写回/归簇/批量确认）、`api/admin.py`、前端 `types/index.ts` + `api/admin.ts` + `QaListView.vue`。
- **实测**：5 条相似问题 + 1 条不相似 → 聚成 2 簇（5/1），草稿写回正确；真实积压 67 条 dry-run 聚成 24 簇。
- **工作量**：中。

### 13. FAQ 自动扩充闭环 ✅ 已落地（2026-11-04）
- **场景**：FAQ 目前只有 80 条；高频未命中问题应沉淀为新 FAQ——系统越用越准。
- **实现**：12 的延伸。管理端三个确认动作（编辑保存 / 标记正确 / 按簇确认）完成后自动调用 `rag_agent/faq_expansion.py`：粗筛合格问答对 → 写入 `faq_qa_pairs`（同问题覆盖更新，天然幂等）→ 后台线程经 `retrieval/faq_index.py` 只重算 faq 一个库（~80 条向量，秒级），并清掉 `get_store` / `get_sparse` 内存缓存，下一次检索即生效。按簇确认只沉淀一条（簇代表问题 + 共用草稿），不按成员数重复插入。
- **粗筛规则**：问题 ≥6 字、非寒暄、含疑问特征；回答 ≥20 字且不是「本次未能检索到…」这类兜底话术——避免把「你好」「问题三」和失败话术写进 FAQ。
- **改动**：`src/rag_agent/faq_expansion.py`（新增）、`src/rag_agent/retrieval/faq_index.py`（新增，`scripts/build_index.py` 的 faq 分支复用）、`api/admin.py`、`store.py`（`qa_record_exists`，顺带修掉「已是目标状态时 rowcount=0 被误判 404」）。
- **实测**：编辑保存 → FAQ 81 条并出现在 `/api/chat` 来源中；重复标记正确 → unchanged；按簇确认 → 只插一条且答案=草稿；寒暄/失败回答 → 不入库；清理后恢复 80 条。
- **工作量**：小（依赖 12）。

### 14. 离线评测与回归 ✅ 已落地（以 `evals/` 实现，未用 `scripts/eval_regression.py`）
- **场景**：改 prompt、换模型、加工具之后，怎么保证没有把原来答对的改错？
- **实现**：`scripts/eval_regression.py`：golden 集 20 题（含两道验收题）+ 断言（预期工具、来源命中、关键信息出现）+ LLM-as-judge 忠实度打分，输出通过率报告；每次调优后跑一遍。
- **落地情况**：`evals/run_eval.py` 直接调用 `run_agent_stream`（不写问答记录），自动指标为期望工具命中率、关键词通过率、各阶段耗时与运行错误；`evals/judge.py` 用 DeepSeek 做独立评审（正确性/忠实度/完整性，1-5 分），输出 JSONL + Markdown + Excel 到 `evals/reports/`。数据集在 `evals/dataset.jsonl`，加用例追加一行即可。
- **改动**：`evals/run_eval.py`、`evals/judge.py`、`evals/dataset.jsonl`、`evals/README.md`。
- **工作量**：小~中｜**每次大改前后都跑一遍**。

---

## 六、知识面与数据扩展 —— P2

### 15. 招标文件上传问答（文档级 RAG）（⬜ 未实现；当前仅有图片解析）
- **场景**：用户上传某招标文件 PDF，问"资质要求是什么？评分标准怎么算？"——能力从"查库"扩展到"查文件"。
- **实现**：`/api/documents` 上传 → 解析分块 → embedding 存独立命名空间（`index_dir/doc/{doc_id}`）；会话内新增工具 `search_uploaded_docs`（仅上传者可见）；来源引用带页码。
- **工作量**：大。

### 16. 公告抽取入库 Agent（数据新鲜度的根）（⬜ 未实现）
- **场景**：`bid_subjects` 目前仅覆盖 2023-10-09 ~ 2023-10-20 一个窗口；订阅、报告、聚合分析的真实价值都卡在数据更新上——这是所有分析类功能的**根问题**。
- **实现**：参考训练数据 xlsx 的 17 字段 schema，用 glm-4.6 结构化抽取公告正文（项目名/采购人/中标人/金额/时间…）→ 人工抽检确认 → 写入 `bid_subjects`；上游对接爬虫或公共资源交易平台。
- **工作量**：大（抽取本身 2~3 天，管道另计）。

### 17. 联网检索工具 ✅ 已落地
- **场景**："最新的政府采购法修订了吗？"这类超出本地语料的问题。
- **实现**：新增 `web_search` 工具（Tavily/博查等 API），结果与来源一并引用；注意只采信权威来源白名单，并做合规提示。
- **落地情况**：已接入两家引擎——`search_web`（Tavily REST）与 `search_web_exa`（Exa MCP，配置 `EXA_API_KEY` 才注册）；前端「联网搜索」开关控制工具视图增删。开启联网但模型未联网时，代码会强制补一次检索，保证"本地 + 联网"双源作答。来源统一归为 `web`。
- **改动**：`tools/rag_tools.py`、`tools/mcp_tools.py`、`agent/agent.py`（强制补查）、`prompt.py`（双源规范）、前端联网开关。
- **工作量**：小~中。

---

## 路线图总览

| # | 功能 | 价值 | 工作量 | 优先级 | 状态 |
|---|---|---|---|---|---|
| 1 | 多轮对话记忆 + 查询改写 | ★★★★★ | 中 | **P0（收尾）** | 🟡 记忆已完成，查询改写未做 |
| 4 | 空结果自反思重试 | ★★★★ | 小 | **P0（收尾）** | 🟡 质量关卡已驱动，未强制重试 |
| 3 | 意图路由直达 | ★★★★ | 小 | 完成 | ✅ 2026-11-03 |
| 7 | 聚合统计工具 | ★★★★★ | 中 | 完成 | ✅ 以 `group_by` 落地 |
| 8 | 图表化回答 | ★★★★ | 中 | 完成 | ✅ |
| 9 | 企业画像 | ★★★★ | 小~中 | 完成 | ✅ 2026-11-04 |
| 12+13 | B 端维护飞轮 | ★★★★ | 中 | 完成 | ✅ 12/13 均完成 2026-11-04 |
| 14 | 离线评测回归 | ★★★★ | 小~中 | 完成 | ✅ `evals/` |
| 2 | 主动澄清 | ★★★ | 中 | 完成 | ✅ 2026-11-04 |
| 5 | Rerank | ★★★ | 小~中 | 完成 | ✅ 2026-10-29 |
| 6 | 语义缓存 | ★★★ | 小~中 | P2 | ⬜ 未开始 |
| 10 | 订阅告警 | ★★★★ | 大 | P2 | ⬜ 未开始 |
| 11 | 报告生成 | ★★★★ | 大 | P2 | ⬜ 未开始 |
| 15 | 文档上传问答 | ★★★ | 大 | P2 | ⬜ 未开始 |
| 16 | 公告抽取入库 | ★★★★★ | 大 | P2（决定 7/10/11 的上限） | ⬜ 未开始 |
| 17 | 联网检索 | ★★★ | 小~中 | 完成 | ✅ Tavily + Exa MCP |

## 落地建议（2026-11-04 盘点）

**已落地**：3（意图路由）、5（Rerank）、2（主动澄清）、7（聚合统计）、8（图表化）、9（企业画像）、12（未维护问题聚类 + 草稿）、13（FAQ 自动扩充）、14（离线评测）、17（联网检索）全部可用；1 的多轮会话记忆、4 的结果质量关卡已上线。

**下一步收尾**：
1. **1 的查询改写**：把"第一家的金额"这类指代性追问改写成独立查询，减少对 `ask_user` 兜底的依赖（约半天）。
2. **4 的强制重试**：空结果时由代码保证至少换参重试一轮，而不是只靠模型自觉（约半天）。

**再往后**：
1. 语义缓存（6）——FAQ 重复率高，收益直接、实现轻。
2. 主动服务（10/11）——依赖数据更新与订阅表，建议在 12/13 之后启动。
3. 文档级 RAG（15）——有真实招标文件问答需求时再做。

**数据提醒**：10/11/7/16 的真实价值依赖数据持续更新。`bid_subjects` 目前仍只覆盖 2023-10 的窗口，建议尽早启动 16 的抽取入库管道，否则所有分析类功能都停留在这一快照上。
