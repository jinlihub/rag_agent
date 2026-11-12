"""单条问题完整链路诊断：召回 → 通用法加权 → LLM 重排，逐步看排序与分数。

用于复现「召回命中但对不上」的情况，判断问题出在哪一环。
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.tools.rag_tools import (  # noqa: E402
    _hybrid_hits,
    _prefer_general_law,
    _rerank_hits,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
ap.add_argument("question")
ap.add_argument("--store", default="legal", choices=["legal", "policy", "faq"])
ap.add_argument("--top-k", type=int, default=4)
args = ap.parse_args()


def show(label, hits):
    print(f"\n{label}")
    for i, h in enumerate(hits, 1):
        name = h.get("law_name") or h.get("question") or h.get("title") or ""
        art = h.get("article_title") or ""
        score = h.get("score")
        print(f"  {i}. [{h.get('row')}] score={score}  {str(name)[:26]} {('· ' + art) if art else ''}")
        body = " ".join(str(h.get("text") or "")[:80].split())
        print(f"     {body}")


q = args.question
print(f"问题：{q}\n" + "=" * 70)

raw = _hybrid_hits(q, args.store, args.top_k)
show(f"① 纯召回（top-{args.top_k}）", raw[: args.top_k])

if args.store == "legal":
    boosted = _prefer_general_law(raw, q)
    show("② 通用法加权后", boosted[: args.top_k])
else:
    boosted = raw

final = _rerank_hits(q, boosted, args.top_k, "text" if args.store == "legal" else "question")
show("③ LLM 重排后（线上实际返回）", final)

low = [h for h in final if h.get("score", 1) < 0.35]
print(f"\n低于 0.35 阈值（前端会过滤掉）：{len(low)}/{len(final)} 条")
