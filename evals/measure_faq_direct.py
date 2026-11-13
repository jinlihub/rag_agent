"""FAQ 直达率评测：知识类问题是否被路由判成 faq，且单次检索质量达标。

「直达」沿用主链路的定义（`agent/agent.py` 阶段零）：路由给出 faq → 只查一次
`search_bidding_knowledge(scope="all", top_k=4)` → `assess_quality` 为 ok → 直接作答，
不再进 ReAct 循环。三步任一不满足就算未直达（退回复杂循环或误判成别的意图）。

评测集取两处，故意分开统计：
  - `golden_set.jsonl` 的 faq 组（20 条，问题原文即 FAQ 索引问题，偏乐观）
  - `dataset.jsonl` 的知识库类（3 条，用户口吻，偏真实）

用法：
    uv run python evals/measure_faq_direct.py            # 路由 + 单次检索（不生成，约 30 秒）
    uv run python evals/measure_faq_direct.py --e2e      # 跑完整 Agent，统计真实端到端耗时
    uv run python evals/measure_faq_direct.py --limit 5  # 冒烟
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.agent.intent import INTENT_FAQ, route_intent  # noqa: E402
from rag_agent.clients.llm_factory import get_client_for  # noqa: E402
from rag_agent.clients.model_catalog import provider_of  # noqa: E402
from rag_agent.config import get_settings  # noqa: E402
from rag_agent.tools.rag_tools import TOOL_REGISTRY  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_set.jsonl"
DATASET = Path(__file__).parent / "dataset.jsonl"
REPORT_DIR = Path(__file__).parent / "reports"
TOOL_NAME = "search_bidding_knowledge"


def load_cases(limit: int | None) -> list[dict]:
    """取标注为知识类的问题：golden faq 组 + dataset 知识库类。"""
    cases: list[dict] = []
    with open(GOLDEN, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if c.get("group") == "faq":
                cases.append({"id": c["id"], "set": "golden", "question": c["question"]})
    with open(DATASET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if c.get("category") == "知识库":
                cases.append({"id": c["id"], "set": "dataset", "question": c["question"]})
    # 同一问题只测一次（两个集合可能有重合）
    seen: set[str] = set()
    uniq = []
    for c in cases:
        if c["question"] in seen:
            continue
        seen.add(c["question"])
        uniq.append(c)
    return uniq[:limit] if limit else uniq


def measure_route(case: dict, client, tool_model: str, thinking: str | None) -> dict:
    """路由 + 单次检索：判断这一步是否具备直达条件。"""
    t0 = time.perf_counter()
    intent = route_intent(case["question"], client, tool_model, thinking)
    t_route = time.perf_counter() - t0

    verdict = "-"
    t_tool = 0.0
    if intent == INTENT_FAQ:
        tool = TOOL_REGISTRY[TOOL_NAME]
        args = {"query": case["question"], "scope": "all", "top_k": 4}
        t1 = time.perf_counter()
        result = tool.execute(args)
        t_tool = time.perf_counter() - t1
        verdict = tool.assess_quality(result)["verdict"]

    return {
        **case,
        "intent": intent,
        "verdict": verdict,
        "direct": intent == INTENT_FAQ and verdict == "ok",
        "route_s": round(t_route, 2),
        "tool_s": round(t_tool, 2),
    }


def measure_e2e(case: dict) -> dict:
    """跑完整 Agent，以 timing 里有没有 analysis 阶段判断是否走了 ReAct 循环。"""
    from rag_agent.agent.runner import run_agent_stream

    t0 = time.perf_counter()
    timing: dict = {}
    error = ""
    for event in run_agent_stream(case["question"]):
        if event.get("type") == "timing":
            timing = {s["key"]: s["seconds"] for s in event.get("stages", [])}
        elif event.get("type") == "error":
            error = str(event.get("message") or event)
    total = round(time.perf_counter() - t0, 2)
    # faq 快路径跳过 ReAct 轮，因此不会有 analysis 阶段
    direct = "analysis" not in timing and not error
    return {
        **case,
        "intent": "faq" if direct else "complex",
        "verdict": "-",
        "direct": direct,
        "total_s": total,
        "timing": timing,
        "error": error,
    }


def pct(n: int, d: int) -> str:
    return f"{n / d * 100:5.1f}%" if d else "  n/a"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="只跑前 N 条")
    ap.add_argument("--e2e", action="store_true", help="跑完整 Agent，统计端到端耗时")
    args = ap.parse_args()

    cases = load_cases(args.limit)
    if not cases:
        raise SystemExit("评测集为空")

    settings = get_settings()
    client = get_client_for(provider_of(settings.llm_tool_model) or settings.llm_provider)
    tool_model = settings.llm_tool_model or settings.llm_model

    print(f"评测 {len(cases)} 条 · 模式 {'端到端' if args.e2e else '路由+检索'} "
          f"· 工具模型 {tool_model}\n")
    print(f"{'id':<12} {'集合':<8} {'意图':<8} {'质量':<6} {'直达':<4} 问题")
    print("-" * 96)

    results = []
    for case in cases:
        r = measure_e2e(case) if args.e2e else measure_route(
            case, client, tool_model, settings.llm_tool_thinking
        )
        results.append(r)
        mark = "✓" if r["direct"] else "✗"
        print(f"{r['id']:<12} {r['set']:<8} {r['intent']:<8} {r['verdict']:<6} {mark:<4} "
              f"{r['question'][:40]}")

    n = len(results)
    direct = sum(r["direct"] for r in results)
    faq_routed = sum(r["intent"] == INTENT_FAQ for r in results if not args.e2e)

    print(f"\n{'=' * 96}")
    if args.e2e:
        times = [r["total_s"] for r in results]
        dt = [r["total_s"] for r in results if r["direct"]]
        ct = [r["total_s"] for r in results if not r["direct"]]
        print(f"FAQ 直达率            {direct}/{n} = {pct(direct, n)}"
              f"（端到端口径，未见 analysis 阶段）")
        print(f"平均耗时              {statistics.mean(times):.1f}s"
              f" · 中位 {statistics.median(times):.1f}s")
        if dt:
            print(f"  直达样本           平均 {statistics.mean(dt):.1f}s · 中位 {statistics.median(dt):.1f}s")
        if ct:
            print(f"  退回复杂循环       平均 {statistics.mean(ct):.1f}s · 中位 {statistics.median(ct):.1f}s")
        errors = [r for r in results if r["error"]]
        if errors:
            print(f"运行错误              {len(errors)} 条")
    else:
        ok_q = sum(r["verdict"] == "ok" for r in results)
        route_t = [r["route_s"] for r in results]
        tool_t = [r["tool_s"] for r in results if r["tool_s"] > 0]
        print(f"路由判为 faq          {faq_routed}/{n} = {pct(faq_routed, n)}")
        print(f"判为 faq 且质量 ok    {ok_q}/{n} = {pct(ok_q, n)}")
        print(f"**FAQ 直达率**        {direct}/{n} = {pct(direct, n)}")
        print(f"路由平均耗时          {statistics.mean(route_t):.2f}s")
        if tool_t:
            print(f"单次检索平均耗时      {statistics.mean(tool_t):.2f}s")

    for group in ("golden", "dataset"):
        items = [r for r in results if r["set"] == group]
        if not items:
            continue
        d = sum(r["direct"] for r in items)
        print(f"  分组 {group:<8} n={len(items):>2}  直达 {pct(d, len(items))}")

    misses = [r for r in results if not r["direct"]]
    if misses:
        print("\n未直达明细：")
        for r in misses:
            why = "非 faq 意图" if r["intent"] != INTENT_FAQ else f"质量 {r['verdict']}"
            print(f"  {r['id']:<12} {why:<10} {r['question'][:52]}")

    REPORT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md = REPORT_DIR / f"faq_direct_{ts}.md"
    lines = [
        f"# FAQ 直达率评测 {ts}",
        "",
        f"- 用例数：{n}（golden faq 组 + dataset 知识库类，已去重）",
        f"- 模式：{'端到端（run_agent_stream）' if args.e2e else '路由 + 单次检索'}",
        f"- 工具模型：`{tool_model}`",
        f"- **FAQ 直达率 {pct(direct, n).strip()}**",
        "",
        "| id | 集合 | 意图 | 质量 | 直达 | 问题 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['id']} | {r['set']} | {r['intent']} | {r['verdict']} | "
            f"{'✓' if r['direct'] else '✗'} | {r['question'][:36]} |"
        )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告：{md}")


if __name__ == "__main__":
    main()
