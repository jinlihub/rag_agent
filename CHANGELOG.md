# 变更记录

> 按时间倒序。每条写清「改了什么、为什么、影响哪里」——改多了记不住时看这里。
> 新增改动时在本文件顶部追加一节，格式保持一致。

## 2026-11-13

### 新增：FAQ 直达率评测 + 检索基线更新

- **背景**：汇报要用三个数字（hit@k、平均耗时、FAQ 直达率），前两个取材于现有 `evals/`，但「FAQ 直达率」没有现成指标——路由结果只发 SSE 事件、不落库，无法从线上回算。
- **改动**：
  - 新增 `evals/measure_faq_direct.py`：口径与 `agent/agent.py` 阶段零一致（路由判 `faq` → 只查一次 `search_bidding_knowledge(scope="all", top_k=4)` → `assess_quality` 为 `ok` 才算直达）；用例取 golden faq 组 20 条 + dataset 知识库类 3 条，按问题去重共 23 条；`--e2e` 跑完整 `run_agent_stream`，以 timing 中是否出现 `analysis` 阶段判断有没有退回复杂循环。
  - `evals/README.md`：新增「FAQ 直达率评测」一节；检索基线更新为 2026-11-13 实测值，并标注旧基线（`_prefer_general_law` 加权前）已失效。
- **实测**：
  - 检索（40 条，top_k=5）：整体 hit@1 85.0% / hit@3 95.0% / hit@5 95.0% / MRR 0.893；FAQ 组 100%/100%；法规组 70.0%/90.0%（旧基线整体 70.0%/87.5%、法规 40.0%/75.0%）。
  - FAQ 直达率：路由+检索口径 22/23 = **95.7%**（唯一未直达 `gs-faq-01` 判为 complex）；端到端复跑 23/23 = 100%，差异来自路由模型输出抖动。路由平均 0.38 s，单次检索平均 5.47 s，端到端平均 11.4 s（中位 10.4 s）。
- **已知口径**：直达率分母是「标注为知识类的问题」，不是全部线上流量；要得到流量口径需在 `qa_record` / `tracking_event` 落库 intent 与是否直达。
- **测试**：`uv run pytest` **116 个通过**（仅新增评测脚本，未改应用代码）。

### 新增：项目级 Git MCP 配置（Claude Code）

- **背景**：本机未安装 Git，只有 `D:\workbuddy\resources\vendor\PortableGit` 便携版，且其 `git.exe` 还依赖同一目录 `usr/bin` 下的 Unix 工具。MCP server 在父进程之外拉起子进程时拿不到完整 PATH，直接调 `git` 会「找不到命令」。
- **改动**：
  - `.mcp.json`：注册名为 `git` 的 MCP server，`command` 写 `uvx` 绝对路径，`args` 为 `mcp-server-git -r D:/rag_agent`；`env.PATH` 按顺序显式注入 `PortableGit\mingw64\bin`、`PortableGit\usr\bin`、uvx 所在目录、`System32`、`Windows`。
  - `.mcp.example.json`：把本机绝对路径换成占位符的模板，供换机后复制成 `.mcp.json`。
  - `.gitignore`：新增 `.mcp.json`（含本机绝对路径，别人 clone 后无效），模板照常入库。
- **验证**：按配置真实拉起 server，stdin 发 `initialize` 得到 `serverInfo.name = "mcp-git"`（版本 2026.11.11，协议 2024-11-05）；`tools/list` 返回 **14 个**工具（`git_status` / `git_diff*` / `git_commit` / `git_add` / `git_reset` / `git_log` / `git_create_branch` / `git_checkout` / `git_merge` / `git_show` / `git_branch` / `git_remote`）。`git check-ignore -v .mcp.json` 确认已被忽略。
- **影响**：仅本地开发工具配置，不涉及应用代码与运行时行为；Claude Code 重启会话后生效（首次会弹授权）。
- **约束**：未安装 Git，继续使用便携版。
- **测试**：`uv run pytest` **116 个通过**（未改应用代码，无新增用例）。

## 2026-11-12

### 新增：多 provider 路由（前端可混选智谱与 DeepSeek）

- **背景**：原来一个 `LLM_BASE_URL` 只对应一家厂商，前端下拉只能列出当前 provider 的模型。
- **改动**：
  - `clients/llm_factory.py`：新增 `get_client_for(provider)`，按厂商缓存客户端实例；`get_llm_client()` 保留为兼容包装。
  - `clients/model_catalog.py`：`ChatModel` 加 `provider` 字段；`_BUILTIN` 改为扁平四元组（每项带厂商）；新增 `provider_of(model_id)`；探活按模型所属厂商取 client；`LLM_MODEL_CHOICES` 支持 `[provider:]id:标签:说明`（3 段取默认厂商，4 段显式指定）。
  - `agent/agent.py`：工具轮与最终作答两处，从「固定 client」改为按模型路由。
- **配置**：`.env` 填入 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`，`LLM_MODEL_CHOICES` 追加 `deepseek-flash`、`deepseek-v4-pro`。
- **验证**：前端下拉 6 项（智谱 4 + DeepSeek 2），两家各调通一次（本地 `evals/check_providers.py`）。
- **测试**：新增 `tests/test_model_catalog.py` 12 个用例（清单形状、`provider_of` 映射、client 路由与缓存、探活按厂商取 client），全套 **114 个通过**。
- **踩坑**：服务器 `.env` 里出现两行 `LLM_MODEL_CHOICES`，且新行行尾带 `\r`，导致 `python-dotenv` 报「could not parse statement starting at line 15」并跳过该行——表现为「`.env` 明明有 deepseek，接口却只返回 4 个模型」。修法：删除重复行 + 整值用双引号包裹 + `sed -i 's/\r$//'`。

### 新增：pytest 单元测试（任务书 三.1）

- **规模**：3 个测试文件、**102 个测试**，全部通过，耗时约 1.3 秒。
- **覆盖**（只测纯逻辑，不连库、不调 LLM，本地随时可跑）：

  | 文件 | 被测对象 | 用例数 |
  | --- | --- | ---: |
  | `tests/test_fusion.py` | `classify_query` 分类、`profile_for` 参数、`rrf_fuse` 融合去重与归一化 | 45 |
  | `tests/test_intent.py` | `is_chitchat` 寒暄正则、`_parse_label` 标签解析 | 47 |
  | `tests/test_rag_tools.py` | `_prefer_general_law` 通用法加权（11-11 新增功能） | 10 |

- **重点固定的边界**：
  - `classify_query` 排除「方法/做法/想法/说法」的误报；
  - 法规特征优先于概念特征（「废标的含义」判 legal，属有意取舍）；
  - 带业务内容的句子不得判成寒暄（否则用户问题会被当客套话敷衍）；
  - `rrf_fuse` 的权重叠加、去重、k 值对头部的影响、缺 `row` 字段跳过；
  - 通用法加权**不修改入参**、用户提行业时不干预排序。
- **过程记录**：首轮 2 条失败是**测试用例选错**（「废标的含义」含法规词「废标」，按设计应判 legal），非代码 bug；第 3 条失败是把 `0.7×1.1=0.77 > 0.8` 算错，已修正断言。
- **配置**：`pyproject.toml` 加 `[tool.pytest.ini_options]`（`testpaths` + `--strict-markers`），`pytest>=9.2.0` 入 dev 依赖。
- **运行**：`uv run pytest`

## 2026-11-11

### 新增：开源模型调研与工具调用能力实测（任务书 二.1 + 二.2）

- **产出**：`docs/调研-开源模型与工具调用.md`（242 行）。
- **部署**：vLLM 0.33.0 + Qwen3-4B-Instruct-2507 在 L20（48 GB）跑通，显存约 19 GB，二次启动 40 秒。
- **实测对比**（同一套 prompt + 工具 Schema，只换模型端点）：

  | 指标 | GLM-4.5-Air（API） | Qwen3-4B（本地） |
  | --- | ---: | ---: |
  | 工具命中率 | 95.0% | 70.0% |
  | 参数命中率 | 95.0% | 80.0% |
  | 平均耗时 | 3840 ms | 1456 ms |
  | P50 耗时 | 3134 ms | 672 ms |

- **关键结论**：4B 慢不了反快 2.6 倍，但工具命中率低 25 点；失败集中表现为「该查却没查」而非「选错工具」，属行为倾向问题而非能力问题。建议继续用 API 承担工具轮，4B 可作离线/降级方案，若要提升优先改提示词。
- **未完成项**：深度思考能力未实测（Qwen3 的 thinking 与 GLM 的 API 参数机制不同，难公平对比），已在文档中标注。
- **新增脚本**：`evals/compare_tool_calling.py`（同 prompt 同工具、只换端点，只发一次请求不执行工具）。
- **踩坑**（已写入文档 §八）：首次启动 13 分钟实为下载权重无进度条；hf-mirror 429 限流；`pkill -9` 破坏 FlashInfer 缓存导致启动必崩（解法 `VLLM_USE_FLASHINFER_SAMPLER=0`）；vLLM 默认关闭 function calling（需 `--enable-auto-tool-choice` + `--tool-call-parser`）；后台启动不继承 PATH。

### 新增：embedding 与向量库选型文档（任务书 二.3）

- **产出**：`docs/选型-embedding与向量库.md`（175 行），含实测数据而非印象对比。
- **实测**（`evals/bench_retrieval.py`）：索引 5680 条 × 2048 维 / 40.2 MB；纯向量检索 **P50 2.25 ms**；embedding API 调用 **平均 450 ms**。
- **关键占比**：单次检索 452 ms 中，向量检索仅 **0.50%**，瓶颈在 embedding 调用。
- **结论一（向量库）**：保持 numpy，不引入向量数据库。给出容量拐点——语料超 10 万条或 P95 > 50 ms 才值得换；需要复杂联合过滤时提前换 pgvector。
- **结论二（embedding）**：线上保持 API（450 ms 相对端到端 26 s 仅 1.7%，不值得绑 GPU）；离线批处理应本地化——重建全量索引 5677 次调用约 42 分钟，本地模型可降到 2 分钟。
- **留白**：bge-m3 与当前 embedding-3 的效果差异未验证，换模型必须重跑 golden set 才能下结论。

### 修复：PG 不可用时数据覆盖范围为空，导致「最近/近半年」类问题全部查空

- **问题**：问「合肥市近半年的工程类中标项目」，模型按当前日期（2026-05 至 2026-11）筛选，与 2023-10 的数据零交集，三次查询全空。
- **根因**：`get_data_coverage()` 只查 PostgreSQL，PG 不可用时返回 `{}`，提示词里注入成「未知」；而工具本身支持降级到 MySQL，两者不一致。
- **改动**：`agent/prompt.py` 在 PG 失败时从 MySQL 兜底取 `MIN(publish_time) / MAX(award_time)`。
- **效果**：同一问题注入了 `2023-10-09 至 2023-10-20`，模型自动换算为 `date_from=2023-05-10, date_to=2023-10-20`，回答从「未检索到」变为「共 92 条」。
- **影响**：所有含「最近 / 最新 / 近半年 / 近期」的问法。

### 新增：Agent 层评测（分层评测的第二层）

- **目的**：把「工具选得对不对」与「检索准不准」分开评，避免端到端评测只能看到「答案不对」却分不清原因。
- **用例**：`evals/agent_set.jsonl` 20 条，标注期望工具与关键参数，覆盖标的物、企业、条件筛选、统计、法规、联网、无需工具、指代澄清八类。
- **脚本**：`evals/run_agent_eval.py`，收到 `stage=generating` 即中断，不等生成完成——省时间省 token，且让这一层只对决策负责。
- **基线**：工具命中率 95.0% / 首选工具率 90.0% / 参数命中率 95.0% / 平均调用 1.00 次。
- **过程中修掉两个评测自身的 bug**：
  1. 未识别 `clarify` 事件，把正常触发的反问误判成「没调工具」——`ask_user` 是独立事件类型，不属于 `tool_call`；
  2. ag-003 要求 `keyword` 参数，但图谱工具用 `entity`，两个工具参数名不同，改为只考工具选择。

### 数据事实：项目数据只覆盖 12 天

- `bid_subjects` 共 8789 条，`publish_time` 范围为 **2023-10-09 至 2023-10-20**。
- 影响：①「近半年」这类问法的答案必然集中在这 12 天；② 问「2024 年」「最新」时可能无数据，只能如实说明；③ 时间类评测用例需按此范围设计，否则永远失败。
- 这是数据集本身的限制，不是代码问题。对外说明时应主动交代，避免被误认为系统查不到数据。

### 意图路由：FAQ 分支扩大检索范围

- **问题**：用户问「公开招标的公告要发在哪些地方」，回答成「采购需求包含哪些内容」，参考来源只有 1 条「实务问答」。
- **根因**：意图判定为 `faq` 后，只查 `scope="faq"`（83 条实务问答），完全没有查 4954 条法规。
- **改动**：`agent/agent.py` 的 FAQ 分支 `scope: "faq"` → `"all"`。
- **效果**：同一问题的来源变为「legal 4 + policy 1」，答案给出《招标投标法》第十六条的「国家指定的报刊、信息网络或者其他媒介」。
- **影响**：所有被判为 FAQ 的知识性问题；耗时从约 1.6s 增至 3~4s。

### 检索：通用法优先

- **问题**：问通用法规问题时，前几条常是行业办法（铁路/水利/通信等），《招标投标法》《政府采购法》被挤到十几位。
- **改动**：`tools/rag_tools.py` 新增 `_prefer_general_law()`，用户未提行业词时给通用法 score ×1.1。
- **效果**（golden set 20 条法规题）：hit@1 50% → 70%，MRR 0.669 → 0.787。
- **注意**：用户提了行业（如「铁路项目」）时不干预，保持原序。

### 新增：检索评测工具链

| 文件 | 用途 |
| --- | --- |
| `evals/golden_set.jsonl` | 40 条用例（20 法规 + 20 FAQ），标注可接受答案与理由 |
| `evals/run_retrieval_eval.py` | hit@1/3/5 与 MRR |
| `evals/agent_set.jsonl` | 20 条 Agent 层用例（期望工具与参数） |
| `evals/run_agent_eval.py` | 工具命中率 / 首选工具率 / 参数命中率 / 调用次数 |
| `evals/diagnose_agent_path.py` | 单条问题走了哪条路径（意图→澄清→工具） |
| `evals/diagnose_one.py` | 单条问题：召回→加权→重排逐步看 |
| `evals/sweep_rrf_params.py` | RRF 的 k 与权重扫描 |
| `evals/sweep_law_prior.py` | 通用法加权系数扫描 |
| `evals/check_rerank_impact.py` | 召回 vs 重排的链路对比 |
| `evals/check_query_kind.py` | 查询分类分布诊断 |
| `evals/inspect_failures.py` | 失败案例的实际内容核查 |
| `evals/check_one_query.py` | 单条查询看加权前后顺序 |
| `evals/verify_intent_fix.py` | 意图路由与检索范围的端到端验证 |

两层基线：RAG（40 条）hit@1 85.0% / hit@5 95.0% / MRR 0.893；Agent（20 条）工具 95.0% / 首选 90.0% / 参数 95.0%。

### 新增：部署脚本

- `deploy.ps1`：打包代码（排除环境与产物）→ scp 上传，并打印服务器端执行命令。

## 2026-11-10

### 部署上线

- 服务器：阿里云 ECS（16 vCPU / 123 GiB / NVIDIA L20 48G），Ubuntu 24.04。
- 数据库：MySQL 8.0 与 PostgreSQL 18 跑在 Docker，卷名为 `xingshuai-*` 前缀。
- 应用：systemd 服务 `rag-agent-xingshuai`（开机自启，崩溃 5 秒后重启）。
- 前端：Nginx 8080 托管 `frontend/dist`，`/api/` 反代到 8000。
- 详细步骤与踩坑见 `docs/部署.md`。

### 数据迁移

- 法规/政策/企业共 6 张表不在代码仓库中，从原库导出 JSONL 再导入（`_export/`）。
- MySQL 导入后：`bid_subjects` 8789 条、`faq_qa_pairs` 80 条。
- 索引：legal 4954 / policy 643 / faq 80。

## 2026-11-05 及之前

### 修复：检索结果为空时的回答策略

- **问题**：查到相关数据但条件不完全匹配时，模型直接回答「未找到」，丢弃了已查到的内容。
- **改动**：`agent/agent.py` 的 `_FINAL_NUDGE` 与 `_LIMITED_NUDGE` 增加「部分匹配也要先给数据并注明局限」。
- **影响**：问「EPC 项目计划」时，会先列出中标记录并说明这不是计划信息，而不是直接说没找到。

### 新增：Langfuse 可观测性

- `observability/langfuse_tracer.py`，在问答结束后一次性上报，失败静默降级。
- `.env`：`LANGFUSE_ENABLED` + 三个连接参数，日本区 host 为 `jp.cloud.langfuse.com`。

### 修复：PostgreSQL 不可用时的降级

- `tools/rag_tools.py`：PG 连接失败自动转查 MySQL，`subject` 降级为标题关键词匹配。

### 配置迁移：DeepSeek 模型 ID

- `deepseek-chat` / `deepseek-reasoner` 已退役 → `deepseek-flash` / `deepseek-v4-pro`。
- 涉及 `clients/model_catalog.py`，否则调用返回 400。
