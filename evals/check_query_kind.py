"""看 golden set 的 40 条问题被 classify_query 判成哪类，以及各类的实际召回表现。"""

import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.retrieval.fusion import classify_query, profile_for, rrf_fuse  # noqa: E402
from rag_agent.retrieval.sparse import get_sparse  # noqa: E402
from rag_agent.retrieval.vector_store import get_store  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

cas = [json.loads(l) for l in open(_ROOT / "evals" / "golden_set.jsonl", encoding="utf-8") if l.strip()]
TOP_K = 5

stat: dict[str, list] = {}
print(f"{'组':<6} {'分类':<11} {'命中位':<7} 问题")
print("-" * 78)
for c in cas:
    kind = classify_query(c["question"])
    p = profile_for(c["question"])
    dense = get_store(c["target_store"]).search(c["question"], top_k=15)
    sparse = get_sparse(c["target_store"]).search(c["question"], top_k=15)
    fused = rrf_fuse([(dense, p["dense"]), (sparse, p["sparse"])], p["k"])
    rows = [h["row"] for h in fused]
    exp = set(c["expected_rows"])
    first = next((i for i, r in enumerate(rows, 1) if r in exp), None)

    ok = 1 if first and first <= TOP_K else 0
    stat.setdefault(kind, []).append((1 if first == 1 else 0, ok, 1 / first if first else 0.0))
    mark = f"{first}" if first else "未命中"
    print(f"{c['group']:<6} {kind:<11} {mark:<7} {c['question'][:44]}")

print("\n分类分布与表现：")
for kind, vals in sorted(stat.items()):
    n = len(vals)
    print(f"  {kind:<11} n={n:<3} hit@1 {sum(v[0] for v in vals)/n*100:5.1f}%  "
          f"hit@{TOP_K} {sum(v[1] for v in vals)/n*100:5.1f}%  MRR {sum(v[2] for v in vals)/n:.3f}")

print("\n分组 × 分类：")
combo = Counter((c["group"], classify_query(c["question"])) for c in cas)
for (g, k), n in sorted(combo.items()):
    print(f"  {g:<6} → {k:<11} {n} 条")
