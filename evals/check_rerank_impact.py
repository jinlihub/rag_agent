"""验证：在线上真实链路（召回 + LLM 重排）下，通用法加权是否还有效。

评测脚本只测到 _hybrid_hits（召回），但线上还有 _rerank_hits（LLM 重排）。
如果 rerank 会把行业办法重新排到前面，那召回阶段的加权就是白做。
"""

import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.tools.rag_tools import _hybrid_hits, _rerank_hits  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GOLDEN = _ROOT / "evals" / "golden_set.jsonl"
TOPK = 5

INDUSTRY = ["铁路", "水利", "公路", "交通", "通信", "民航", "核电", "军工", "农业",
            "石油", "电力", "煤炭", "冶金", "化工", "林业", "港口", "航道"]
GENERAL = ["中华人民共和国招标投标法", "中华人民共和国政府采购法"]
BOOST = 1.1


def boost_general(hits, query):
    if any(k in query for k in INDUSTRY):
        return hits
    out = []
    for h in hits:
        law = h.get("law_name") or ""
        s = h.get("score", 0)
        if any(g in law for g in GENERAL):
            s *= BOOST
        out.append({**h, "score": s})
    return sorted(out, key=lambda x: -x["score"])


def hit_rank(rows, expected):
    return next((i for i, r in enumerate(rows, 1) if r in expected), None)


def main():
    cases = [json.loads(l) for l in open(GOLDEN, encoding="utf-8") if l.strip()]
    cases = [c for c in cases if c["group"] == "legal"]
    print(f"只测法规组 {len(cases)} 条（重排要调 LLM，耗时较长）\n")

    stat = {"recall": [], "recall_boost": [], "rerank": [], "rerank_boost": []}
    t0 = time.time()

    for i, c in enumerate(cases, 1):
        q, exp = c["question"], set(c["expected_rows"])

        hits = _hybrid_hits(q, "legal", TOPK)
        rows_r = [h["row"] for h in hits]
        stat["recall"].append(hit_rank(rows_r, exp))

        hits_b = boost_general(hits, q)
        rows_rb = [h["row"] for h in hits_b]
        stat["recall_boost"].append(hit_rank(rows_rb, exp))

        final = _rerank_hits(q, hits, TOPK, "text")
        stat["rerank"].append(hit_rank([h["row"] for h in final], exp))

        final_b = _rerank_hits(q, hits_b, TOPK, "text")
        stat["rerank_boost"].append(hit_rank([h["row"] for h in final_b], exp))

        print(f"  {i}/{len(cases)} {c['id']} 召回={stat['recall'][-1]} "
              f"召回+boost={stat['recall_boost'][-1]} 重排={stat['rerank'][-1]} "
              f"重排+boost={stat['rerank_boost'][-1]}")

    print(f"\n耗时 {time.time()-t0:.0f}s\n")
    print(f"{'链路':<16} {'hit@1':>7} {'hit@3':>7} {'hit@5':>7} {'MRR':>7}")
    print("-" * 50)
    for name, ranks in stat.items():
        n = len(ranks)
        h1 = sum(1 for r in ranks if r == 1) / n
        h3 = sum(1 for r in ranks if r and r <= 3) / n
        h5 = sum(1 for r in ranks if r and r <= TOPK) / n
        mrr = sum(1 / r if r else 0 for r in ranks) / n
        label = {"recall": "召回", "recall_boost": "召回+boost",
                 "rerank": "召回+重排", "rerank_boost": "召回+boost+重排"}[name]
        print(f"{label:<16} {h1*100:>6.1f}% {h3*100:>6.1f}% {h5*100:>6.1f}% {mrr:>7.3f}")


if __name__ == "__main__":
    main()
