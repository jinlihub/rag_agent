"""RRF 参数扫描：用 golden set 找更优的 k 与 dense/sparse 权重组合。

与线上一致地走 dense + sparse + rrf_fuse，只替换融合参数（不含重排）。
每条用例的 dense/sparse 召回只算一次，之后复用做多组融合，避免重复 embedding。
"""

from __future__ import annotations

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
CAP = 15  # 与 rag_tools 一致：min(top_k*3, CANDIDATE_CAP=16)

GRID_K = [10, 20, 30, 40, 60, 80, 100]
GRID_W = [(0.3, 0.7), (0.4, 0.6), (0.5, 0.5), (0.6, 0.4), (0.7, 0.3)]


def load_cases():
    cases = []
    with open(GOLDEN, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def main() -> None:
    cases = load_cases()
    print(f"用例 {len(cases)} 条，top_k={TOP_K}，cap={CAP}\n")

    # 预计算两路召回（每条只算一次）
    cache = []
    for i, c in enumerate(cases, 1):
        store, q = c["target_store"], c["question"]
        dense = get_store(store).search(q, top_k=CAP)
        sparse = get_sparse(store).search(q, top_k=CAP)
        cache.append((c, dense, sparse))
        if i % 10 == 0:
            print(f"  已召回 {i}/{len(cases)}")

    def score(fused_rows: list[int], expected: set[int]) -> tuple[int | None, int, float]:
        first = next((idx for idx, r in enumerate(fused_rows, 1) if r in expected), None)
        return first, (1 if first and first <= TOP_K else 0), (1 / first if first else 0.0)

    results = []
    for k in GRID_K:
        for wd, ws in GRID_W:
            hits1 = hitsk = 0
            mrr = 0.0
            by_group = {}
            for c, dense, sparse in cache:
                fused = rrf_fuse([(dense, wd), (sparse, ws)], k)
                rows = [h["row"] for h in fused]
                first, hk, rr = score(rows, set(c["expected_rows"]))
                hits1 += 1 if first == 1 else 0
                hitsk += hk
                mrr += rr
                g = c["group"]
                by_group.setdefault(g, [0, 0, 0.0])
                by_group[g][0] += 1 if first == 1 else 0
                by_group[g][1] += hk
                by_group[g][2] += rr
            n = len(cache)
            results.append(
                {
                    "k": k,
                    "w": f"{wd:.1f}/{ws:.1f}",
                    "hit1": hits1 / n,
                    f"hit{TOP_K}": hitsk / n,
                    "mrr": mrr / n,
                    "group": {
                        g: (v[0] / sum(1 for c, _, _ in cache if c["group"] == g),
                            v[1] / sum(1 for c, _, _ in cache if c["group"] == g),
                            v[2] / sum(1 for c, _, _ in cache if c["group"] == g))
                        for g, v in by_group.items()
                    },
                }
            )

    results.sort(key=lambda r: (-r[f"hit{TOP_K}"], -r["hit1"], -r["mrr"]))

    print(f"\n{'k':>4}  {'dense/sparse':>13}  {'hit@1':>7}  {f'hit@{TOP_K}':>7}  {'MRR':>6}")
    print("-" * 50)
    for r in results[:12]:
        print(f"{r['k']:>4}  {r['w']:>13}  {r['hit1']*100:>6.1f}%  {r[f'hit{TOP_K}']*100:>6.1f}%  {r['mrr']:>6.3f}")

    best = results[0]
    print(f"\n最优组合：k={best['k']}, dense={best['w']}  "
          f"→ hit@1 {best['hit1']*100:.1f}% / hit@{TOP_K} {best[f'hit{TOP_K}']*100:.1f}% / MRR {best['mrr']:.3f}")
    print("\n按组拆分（最优组合）：")
    for g, (h1, hk, m) in best["group"].items():
        print(f"  {g:6} hit@1 {h1*100:5.1f}%  hit@{TOP_K} {hk*100:5.1f}%  MRR {m:.3f}")

    # 当前线上参数作为对照
    print("\n当前线上参数对照：")
    for label, k, wd, ws in [
        ("legal(法规类)", 30, 0.4, 0.6),
        ("conceptual(概念类)", 80, 0.7, 0.3),
        ("general(通用类)", 60, 0.55, 0.45),
    ]:
        hit1 = hitsk = 0
        mrr = 0.0
        for c, dense, sparse in cache:
            fused = rrf_fuse([(dense, wd), (sparse, ws)], k)
            first, hk, rr = score([h["row"] for h in fused], set(c["expected_rows"]))
            hit1 += 1 if first == 1 else 0
            hitsk += hk
            mrr += rr
        n = len(cache)
        print(f"  {label:20} k={k:>3} {wd}/{ws}  hit@1 {hit1/n*100:5.1f}%  "
              f"hit@{TOP_K} {hitsk/n*100:5.1f}%  MRR {mrr/n:.3f}")


if __name__ == "__main__":
    main()
