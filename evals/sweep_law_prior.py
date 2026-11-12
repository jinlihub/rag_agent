"""实验：给「通用法」加权、给「行业办法」降权，看能否改善召回排序。

规则（仅在用户未提及行业时生效）：
  - 结果来自行业办法（铁路/水利/通信…）→ 分数乘以 penalty
  - 结果来自通用法（招标投标法/政府采购法）→ 分数乘以 boost
这样既符合业务直觉（问通用问题先给通用法），又不会误伤行业提问。
"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.retrieval.fusion import rrf_fuse  # noqa: E402
from rag_agent.retrieval.sparse import get_sparse  # noqa: E402
from rag_agent.retrieval.vector_store import get_store  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

GOLDEN = _ROOT / "evals" / "golden_set.jsonl"
TOP_K = 5
CAP = 15

INDUSTRY = [
    "铁路", "水利", "公路", "交通", "通信", "民航", "核电", "军工", "农业",
    "石油", "电力", "煤炭", "冶金", "化工", "林业", "港口", "航道", "城市建设",
]
GENERAL = ["中华人民共和国招标投标法", "中华人民共和国政府采购法"]

PENALTIES = [1.0, 0.9, 0.85, 0.8, 0.7]
BOOSTS = [1.0, 1.1, 1.2]


def load_cases():
    return [json.loads(l) for l in open(GOLDEN, encoding="utf-8") if l.strip()]


def rerank(fused, query, penalty, boost):
    has_industry = any(k in query for k in INDUSTRY)
    scored = []
    for h in fused:
        law = h.get("law_name") or ""
        s = h["score"]
        if not has_industry and any(k in law for k in INDUSTRY):
            s *= penalty
        if any(law.startswith(g) or g in law for g in GENERAL):
            s *= boost
        scored.append((s, h))
    scored.sort(key=lambda x: -x[0])
    return [h for _, h in scored]


def main() -> None:
    cases = load_cases()
    # 预召回
    cache = []
    for c in cases:
        store, q = c["target_store"], c["question"]
        dense = get_store(store).search(q, top_k=CAP)
        sparse = get_sparse(store).search(q, top_k=CAP)
        cache.append((c, dense, sparse, rrf_fuse([(dense, 0.55), (sparse, 0.45)], 60)))

    print(f"{'penalty':>8} {'boost':>6} {'hit@1':>7} {'hit@3':>7} {'hit@5':>7} {'MRR':>7}  {'legal组hit@1':>12}")
    print("-" * 66)

    best = None
    for penalty in PENALTIES:
        for boost in BOOSTS:
            h1 = h3 = h5 = 0
            mrr = 0.0
            legal_h1 = legal_n = 0
            for c, dense, sparse, fused in cache:
                rows = [h["row"] for h in rerank(fused, c["question"], penalty, boost)]
                exp = set(c["expected_rows"])
                first = next((i for i, r in enumerate(rows, 1) if r in exp), None)
                h1 += 1 if first == 1 else 0
                h3 += 1 if first and first <= 3 else 0
                h5 += 1 if first and first <= TOP_K else 0
                mrr += 1 / first if first else 0.0
                if c["group"] == "legal":
                    legal_n += 1
                    legal_h1 += 1 if first == 1 else 0
            n = len(cache)
            row = (penalty, boost, h1 / n, h3 / n, h5 / n, mrr / n, legal_h1 / max(legal_n, 1))
            print(f"{penalty:>8.2f} {boost:>6.2f} {row[2]*100:>6.1f}% {row[3]*100:>6.1f}% "
                  f"{row[4]*100:>6.1f}% {row[5]:>7.3f}  {row[6]*100:>11.1f}%")
            if best is None or (row[4], row[2], row[5]) > (best[4], best[2], best[5]):
                best = row

    print(f"\n最佳：penalty={best[0]}, boost={best[1]} → "
          f"hit@1 {best[2]*100:.1f}% / hit@3 {best[3]*100:.1f}% / hit@5 {best[4]*100:.1f}% / MRR {best[5]:.3f}")

    # 基线（不加权）
    h1 = h3 = h5 = 0
    mrr = 0.0
    for c, dense, sparse, fused in cache:
        rows = [h["row"] for h in fused]
        exp = set(c["expected_rows"])
        first = next((i for i, r in enumerate(rows, 1) if r in exp), None)
        h1 += 1 if first == 1 else 0
        h3 += 1 if first and first <= 3 else 0
        h5 += 1 if first and first <= TOP_K else 0
        mrr += 1 / first if first else 0.0
    n = len(cache)
    print(f"\n基线（不加权，统一 0.55/0.45 + k=60）：hit@1 {h1/n*100:.1f}% / "
          f"hit@3 {h3/n*100:.1f}% / hit@5 {h5/n*100:.1f}% / MRR {mrr/n:.3f}")


if __name__ == "__main__":
    main()
