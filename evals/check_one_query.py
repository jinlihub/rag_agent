"""单条查询检查：对比「通用法加权」前后的排序，确认改动生效。

用法：
    uv run python evals/check_one_query.py "公开招标的公告要发在哪些地方？"
    uv run python evals/check_one_query.py "某某问题" --store faq
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.tools.rag_tools import _hybrid_hits, _prefer_general_law  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
ap.add_argument("question", help="要查询的问题")
ap.add_argument("--store", default="legal", choices=["legal", "policy", "faq"])
ap.add_argument("--top-k", type=int, default=5)
args = ap.parse_args()

raw = _hybrid_hits(args.question, args.store, args.top_k)
final = _prefer_general_law(raw, args.question) if args.store == "legal" else raw


def show(title, hits):
    print(f"\n{title}")
    for i, h in enumerate(hits[: args.top_k], 1):
        title_ = h.get("law_name") or h.get("question") or h.get("title") or ""
        art = h.get("article_title") or ""
        print(f"  {i}. [{h.get('row')}] {str(title_)[:30]} {('· ' + art) if art else ''}")


print(f"问题：{args.question}")
show("加权前（纯召回）：", raw)
if args.store == "legal":
    show("加权后（通用法优先）：", final)

    changed = [h["row"] for h in raw[: args.top_k]] != [h["row"] for h in final[: args.top_k]]
    print(f"\n排序是否变化：{'是' if changed else '否（未提行业但顺序相同，或本就无通用法命中）'}")
