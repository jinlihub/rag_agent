"""检索召回评测：用 golden set 算 hit@1/3/5 与 MRR。

只评「召回」这一段（dense + sparse + RRF），不含 LLM 重排与生成——
召回没命中的东西，后面任何环节都救不回来，所以这是最该单独盯住的指标。

用法：
    uv run python evals/run_retrieval_eval.py                 # 全量 40 条
    uv run python evals/run_retrieval_eval.py --group legal   # 只跑法规组
    uv run python evals/run_retrieval_eval.py --top-k 8       # 看更深的召回
    uv run python evals/run_retrieval_eval.py --verbose       # 打印每条详情
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.tools.rag_tools import _hybrid_hits, _prefer_general_law  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_set.jsonl"
REPORT_DIR = Path(__file__).parent / "reports"


def load_cases(group: str | None, limit: int | None) -> list[dict]:
    cases = []
    with open(GOLDEN, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if group and c.get("group") != group:
                continue
            cases.append(c)
    return cases[:limit] if limit else cases


def evaluate(case: dict, top_k: int) -> dict:
    hits = _hybrid_hits(case["question"], case["target_store"], top_k)
    if case["target_store"] == "legal":
        # 与工具内部一致：法规检索会做通用法加权
        hits = _prefer_general_law(hits, case["question"])
    rows = [h["row"] for h in hits]
    expected = set(case["expected_rows"])

    first = next((i for i, r in enumerate(rows, 1) if r in expected), None)
    return {
        "id": case["id"],
        "group": case["group"],
        "category": case.get("category", ""),
        "question": case["question"],
        "first_rank": first,
        "hit@1": 1 if first == 1 else 0,
        "hit@3": 1 if first and first <= 3 else 0,
        f"hit@{top_k}": 1 if first and first <= top_k else 0,
        "mrr": round(1 / first, 4) if first else 0.0,
        "retrieved_rows": rows[:top_k],
        "expected_rows": sorted(expected),
    }


def summarize(results: list[dict], top_k: int) -> dict:
    n = len(results)
    if not n:
        return {}
    return {
        "n": n,
        "hit@1": sum(r["hit@1"] for r in results) / n,
        "hit@3": sum(r["hit@3"] for r in results) / n,
        f"hit@{top_k}": sum(r[f"hit@{top_k}"] for r in results) / n,
        "mrr": sum(r["mrr"] for r in results) / n,
    }


def fmt(v: float) -> str:
    return f"{v * 100:5.1f}%"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=["legal", "faq"], help="只评某一组")
    ap.add_argument("--top-k", type=int, default=5, help="召回深度，默认 5")
    ap.add_argument("--limit", type=int, help="只跑前 N 条")
    ap.add_argument("--verbose", action="store_true", help="打印每条命中名次")
    args = ap.parse_args()

    cases = load_cases(args.group, args.limit)
    if not cases:
        raise SystemExit("golden set 为空")

    print(f"评估 {len(cases)} 条，top_k={args.top_k}\n")

    results = []
    for i, case in enumerate(cases, 1):
        r = evaluate(case, args.top_k)
        results.append(r)
        if args.verbose:
            mark = "✓" if r["first_rank"] else "✗"
            rank = f"第 {r['first_rank']} 位" if r["first_rank"] else "未命中"
            print(f"  {mark} {r['id']:14} {rank:8} {r['question'][:38]}")

    overall = summarize(results, args.top_k)
    print(f"\n{'=' * 56}")
    print(f"整体  n={overall['n']}  hit@1={fmt(overall['hit@1'])}  "
          f"hit@3={fmt(overall['hit@3'])}  hit@{args.top_k}={fmt(overall[f'hit@{args.top_k}'])}  "
          f"MRR={overall['mrr']:.3f}")

    print(f"\n按组：")
    by_group = defaultdict(list)
    for r in results:
        by_group[r["group"]].append(r)
    for g, items in sorted(by_group.items()):
        s = summarize(items, args.top_k)
        print(f"  {g:8} n={s['n']:>3}  hit@1={fmt(s['hit@1'])}  "
              f"hit@{args.top_k}={fmt(s[f'hit@{args.top_k}'])}  MRR={s['mrr']:.3f}")

    print(f"\n按类别（未命中率高的优先排查）：")
    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    rows = sorted(
        ((c, summarize(v, args.top_k)) for c, v in by_cat.items()),
        key=lambda kv: kv[1][f"hit@{args.top_k}"],
    )
    for c, s in rows:
        if s["n"] < 2:
            continue
        print(f"  {c:10} n={s['n']:>2}  hit@{args.top_k}={fmt(s[f'hit@{args.top_k}'])}  MRR={s['mrr']:.2f}")

    misses = [r for r in results if not r["first_rank"]]
    low = [r for r in results if r["first_rank"] and r["first_rank"] > args.top_k]
    if misses or low:
        print(f"\n未达 top@{args.top_k}：完全未命中 {len(misses)} 条，排名超出 {len(low)} 条")
        for r in misses + low:
            rank = f"第 {r['first_rank']} 位" if r["first_rank"] else "未命中"
            print(f"  {r['id']:14} {rank:8} 期望 {r['expected_rows']}  实得 {r['retrieved_rows']}")
            print(f"      {r['question'][:60]}")

    REPORT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md = REPORT_DIR / f"retrieval_{ts}.md"
    lines = [
        f"# 检索召回评测 {ts}",
        "",
        f"- 用例数：{overall['n']}",
        f"- 召回深度：top_k={args.top_k}",
        f"- **hit@1 {fmt(overall['hit@1'])}｜hit@3 {fmt(overall['hit@3'])}｜hit@{args.top_k} {fmt(overall[f'hit@{args.top_k}'])}｜MRR {overall['mrr']:.3f}**",
        "",
        "## 分组",
        "",
        "| 组 | n | hit@1 | hit@" + str(args.top_k) + " | MRR |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for g, items in sorted(by_group.items()):
        s = summarize(items, args.top_k)
        lines.append(
            f"| {g} | {s['n']} | {fmt(s['hit@1'])} | {fmt(s[f'hit@{args.top_k}'])} | {s['mrr']:.3f} |"
        )
    lines += ["", "## 未命中明细", ""]
    if misses:
        lines += ["| id | 问题 | 期望行 | 实得行 |", "| --- | --- | --- | --- |"]
        for r in misses:
            lines.append(
                f"| {r['id']} | {r['question'][:36]} | {r['expected_rows']} | {r['retrieved_rows']} |"
            )
    else:
        lines.append("无——全部命中。")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告：{md}")


if __name__ == "__main__":
    main()
