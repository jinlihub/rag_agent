# 本项目适合增加的 Skills

> Skill = `.claude/skills/<name>/SKILL.md`，把"重复出现、步骤固定、散落着部落知识"的工作流
> 沉淀为一段可被 Claude 按触发词自动加载的操作说明。适合做 Skill 的判据：**步骤超过三步、
> 有前置条件检查、做错有代价、知识只存在于某些文件注释或人的脑子里**。
> 以下按优先级排列，全部基于仓库现有脚本与本次开发中实际踩过的坑。

---

## P0 —— 高频且踩过坑，最值得先做

### 1. `new-agent-tool`（新增 Agent 检索工具）

- **触发**："加一个检索工具 / 接入新数据源 / 给 Agent 加个能力"
- **做什么**：按本仓库固定套路生成完整清单，逐项落地：
  1. `src/rag_agent/tools/rag_tools.py`：Pydantic `args_model`（字段描述写给 LLM 看）+ `BaseTool` 子类
     （`name` / `description` / `source_kind` / `source_title_key` / `empty_hint` / `assess_quality` / `source_items`）
  2. 注册进 `TOOL_REGISTRY`；联网类须加入 `WEB_TOOLS`
  3. 前端三处映射：`types/index.ts`（契约对齐）、`constants/texts.ts` 的 `TOOL_LABELS` + `SOURCE_LABELS`
  4. `scripts/tools_smoke_test.py` 补结构断言
- **编码的部落知识**：`empty_hint` 要写成"给 LLM 的下一步建议"；`assess_quality` 决定空/弱结果的
  换策略行为；工具描述里的"适用于：…"句式直接决定 ReAct 选工具的准确率。

### 2. `rebuild-index`（重建向量索引）

- **触发**："重建索引 / 换了切块参数 / 换了 embedding 模型 / 导入了新语料"
- **做什么**：
  1. **前置检查**（本流程最容易翻车的点）：MySQL 里 `faq_qa_pairs` / `policy_政策全文` / 法条表是否有数；
     **先打一发 1-token embedding 探活**——账户余额耗尽时 embedding 全线 429"暂无可用资源包"
     （2026-10 实际发生过），别等跑到一半 8790 行才炸
  2. `uv run python scripts/build_index.py`
  3. **落成校验**：`data/index/` 三个 npz/meta 行数与库一致；用 2~3 个已知问题抽查
     `VectorStore.search` + `SparseIndex.search`（sparse 与 dense 共用 meta，行号必须对齐）
- **编码的部落知识**：`_CHUNK_SIZE=500/_CHUNK_OVERLAP=80` 改动会使全部向量失效必须重建；
  `data/index/*.meta.jsonl` 的行号是 RRF 融合去重的键，**顺序不能动**。

### 3. `smoke`（分层冒烟测试）

- **触发**："验证一下改动 / 跑冒烟 / 发布前检查"
- **做什么**：按改动层次选择，不盲目全跑：
  - 改了工具层 → `uv run python scripts/tools_smoke_test.py --dry`（不连库不调模型）再全量
  - 改了 agent/提示词 → `uv run python scripts/smoke_test.py "<测试问题>"`（观察事件流）
  - 改了 API/前端契约 → `uv run python scripts/app_smoke_test.py`
  - 改了模型目录/换 key → `uv run python scripts/_probe_models.py`
- **编码的部落知识**：429 资源包、`IndexNotBuilt`、PG 未导入各自的报错长相与处置；
  哪些测试会**真实调用 LLM 花钱**，哪些纯结构断言。

---

## P1 —— 拍板后建，复利明显

### 4. `eval-retrieval`（检索质量评测）

- **触发**："调了 `_PROFILES` / sparse / 重排 / 切块参数后，看看效果"
- **做什么**：维护一份黄金问题集（`data/eval/golden.jsonl`：问题 + 期望命中的法名/FAQ/来源），
  按 `legal / conceptual / general` 三类跑 `SearchBiddingKnowledgeTool`，输出 hit@k 与
  融合参数回显（`retrieval.query_kind`），改参前后对比。
- **为什么值得**：`fusion.py` 的 `_PROFILES`（k=30/80/60、0.4/0.6 等权重）目前是拍的，
  没有评测集就永远只能凭感觉调。

### 5. `import-data`（导入新数据源）

- **触发**："导入了新的 xlsx / 换了一批语料"
- **做什么**：`data/raw → data/processed → import_xlsx_to_mysql.py（清空重导，幂等）→
  to_postgresql.py → rebuild-index skill` 的全链路 + 各表行数核对。
- **编码的部落知识**：xlsx 的 Sheet 约定、字段清洗位置、PG 与 MySQL 的分工
  （bid_subjects 结构化 / knowledge 图谱 / 知识库文本）。

### 6. `docs-sync`（文档同步）

- **触发**："这个功能做完了 / 同步一下文档"
- **做什么**：按本仓库文档制度回写：`开发文档.md` 的 FR 需求编号矩阵与**假设清单**（如 A11
  "结果评价枚举待定"在实现落定后要回写）、`组件工作机制.md` 的链路图与表结构、`技术栈.md` 注意事项。
- **为什么值得**：文档里明确把"假设清单评审结论回写文档"列为制度，但没有任何机制保证执行。

---

## P2 —— 可做可不做

### 7. `api-debug`（不带前端调接口）

- **触发**："验证后端接口 / 前端还没起想先测 API"
- **做什么**：`/api/auth/login` 拿 token → 拼curl 调 SSE `/api/chat`（注意 `data:` 帧解析）、
  `/api/models`、维护接口；SSE 用 `curl -N` 看流。
- 小而顺手，也可并入 `smoke`。

### 8. `db-reset`（重置开发库）

- `init_db.py` 本身幂等，没什么步骤可言；唯一价值是提醒"会清 qa_record/tracking_event"。
  **建议不做**，写进 CLAUDE.md 一句话即可。

---

## 不适合做成 Skill 的

- **`npm run build` / `uv run` 单条命令**：Skill 要解决的是"步骤与判断"，单命令写进 CLAUDE.md 足够。
- **代码风格约定**（中文注释、文案进 `texts.ts`、类型契约对齐）：这是 CLAUDE.md 的职责，不是 Skill。
- **一次性脚本**（如 `_probe_models.py` 自述"用完即删"）：做了 Skill 反而留住垃圾。

---

## 落地方式

每个 Skill 一个目录，`SKILL.md` 带 frontmatter（description 里写清触发词，Claude 据此自动加载）：

```markdown
---
name: rebuild-index
description: 重建知识库向量索引。当用户提到重建索引、改切块/embedding 参数、导入新语料时使用。
---

# 重建向量索引

## 前置检查
1. 确认 MySQL 三张语料表有数据：...
2. embedding 探活（1 token），429 资源包则停止并告知用户：...

## 执行
...

## 落成校验
...
```

建议顺序：先做 `smoke`（当天回本）→ `rebuild-index`、`new-agent-tool` → 有评测集需求再建
`eval-retrieval`。P0 三个互相引用：`import-data` 尾步调 `rebuild-index`，`rebuild-index` 校验用 `smoke`。
