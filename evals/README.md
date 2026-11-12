# Agent 评估体系

对问答 Agent 做可重复的量化评估：跑评估集 → 自动指标 + LLM 独立评审 → 三格式报告（JSONL 明细 / Markdown 摘要 / Excel 汇总）。

## 目录结构

```
evals/
├── README.md          # 本文件
├── dataset.jsonl      # 评估数据集（每行一个用例，手工维护）
├── judge.py           # LLM-as-judge（DeepSeek 独立评审，与被评 Agent 的 GLM 不同厂商）
├── run_eval.py        # 运行器 CLI
└── reports/           # 每轮评估的报告产物（gitignore）
```

## 检索召回评测（golden set）

与上面的端到端评测互补：**只评向量召回这一段**，看正确答案有没有被检索出来——召回没命中的，后面重排和生成都救不回来。

| 文件 | 作用 |
|---|---|
| `golden_set.jsonl` | 40 条用例：20 条法规（口语化改写自法条）+ 20 条 FAQ（问题即索引问题） |
| `run_retrieval_eval.py` | 算 hit@1 / hit@3 / hit@5 / MRR，按组与类别汇总，未命中列明细 |

每条用例标注 `target_store` 与 `expected_rows`（正确内容在索引中的行号），评测直接调 `_hybrid_hits`，不含重排与生成。

```bash
uv run python evals/run_retrieval_eval.py                            # 全量 40 条
uv run python evals/run_retrieval_eval.py --group legal --verbose    # 只看法规组
uv run python evals/run_retrieval_eval.py --top-k 8                  # 看更深的召回
```

**基线（2026-11-11，top_k=5）**

| 组 | n | hit@1 | hit@5 | MRR |
| --- | ---: | ---: | ---: | ---: |
| 整体 | 40 | 70.0% | 87.5% | 0.781 |
| FAQ | 20 | 100.0% | 100.0% | 1.000 |
| 法规 | 20 | 40.0% | 75.0% | 0.561 |

FAQ 组 100% 属预期（问题原文即索引里的问题），价值在于**回归**——指标下降说明索引或切块出了问题。法规组 40% 是真实水平：用户的口语化提问与法条原文措辞差距大，是本项目检索的主要难点。

调 RRF 参数、切块粒度、embedding 模型后，重跑本脚本对比同一批用例即可判断是否真的变好。

## 评估维度

| 维度 | 来源 | 说明 |
|---|---|---|
| 期望工具命中率 | 自动 | 用例声明的 `expect_tools` 是否真的被调用（工具选择是否正确） |
| 关键词通过率 | 自动 | `keywords` 是否出现在回答或来源标题（低成本事实校验） |
| 正确性 / 忠实度 / 完整性 | DeepSeek 评审 | 1-5 分；忠实度考有无来源外编造（幻觉），通过线各维 ≥3 |
| 用时 | 自动 | 复用 Agent 的 timing 事件：各阶段耗时 + 总用时 |
| 运行错误 | 自动 | Agent 流程异常（工具报错、超时等） |

## 用例格式（dataset.jsonl 每行一个 JSON）

```json
{"id": "kb-001", "category": "知识库", "question": "供应商提出质疑的时限是多少天？",
 "web": false, "expect_tools": ["search_bidding_knowledge"], "keywords": ["7个工作日"],
 "reference": "参考要点（给评审用）", "note": "备注"}
```

- `web`：是否开联网搜索（对应前端「联网搜索」开关）
- `expect_tools` / `keywords`：缺省时该项不检查
- 类别：知识库 / 中标记录 / 知识图谱 / 联网 / 鲁棒性（可自由扩展）

## 运行

```bash
uv run python evals/run_eval.py                     # 全量（14 用例，约 3-5 分钟）
uv run python evals/run_eval.py --limit 3           # 冒烟
uv run python evals/run_eval.py --category 联网      # 只跑某类别
uv run python evals/run_eval.py --no-judge          # 只跑 Agent 不评审
uv run python evals/run_eval.py --concurrency 4     # 提高并发（默认 2，防限流）
```

前置：MySQL / PostgreSQL / 智谱 LLM /（联网用例）Tavily 可用，即后端能正常启动即可。
评审需 `.env` 配置 `DEEPSEEK_API_KEY`。用例直接调 `run_agent_stream`，**不产生问答记录**（不污染线上库）。

## 报告

每轮生成三份产物（`evals/reports/run_<时间戳>*`）：

- `run_x.jsonl` —— 每用例完整轨迹：回答全文、工具轨迹、来源、timing 明细、评审分数
- `run_x_summary.md` —— 聚合指标表 + 每用例速览，可直接贴进文档/周报
- `run_x_summary.xlsx` —— 明细 sheet + 汇总 sheet，供筛选排序

## 扩展

- **加用例**：`dataset.jsonl` 追加一行即可；建议每类保持 ≥3 条，回归时对比同 id 的分数变化
- **换评审模型**：`--judge-model deepseek-reasoner`（推理型评审更严但更慢）
- **加自动指标**：在 `run_case` 里追加计算字段，`write_reports` 的表头同步加列
- **回归基线**：保留历史 `reports/`，对比两次 run 的 summary.md 观察指标漂移
