"""打印失败用例的检索内容，判断是「真没找到」还是「命中相邻条款」。"""

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.tools.rag_tools import _hybrid_hits  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

IDX = _ROOT / "data" / "index"
TOP_K = 5


def load_meta(store):
    rows = {}
    with open(IDX / f"{store}.meta.jsonl", encoding="utf-8") as f:
        for i, line in enumerate(f):
            rows[i] = json.loads(line)
    return rows


def brief(d, n=110):
    title = d.get("law_name") or d.get("question") or d.get("title") or ""
    body = d.get("text") or d.get("answer") or ""
    return f"{title[:28]} | {' '.join(body.split())[:n]}"


cases = [json.loads(l) for l in open(_ROOT / "evals" / "golden_set.jsonl", encoding="utf-8") if l.strip()]
metas = {"legal": load_meta("legal"), "faq": load_meta("faq")}

fails = []
for c in cases:
    hits = _hybrid_hits(c["question"], c["target_store"], TOP_K)
    rows = [h["row"] for h in hits]
    exp = set(c["expected_rows"])
    first = next((i for i, r in enumerate(rows, 1) if r in exp), None)
    if not first or first > TOP_K:
        fails.append((c, rows[:TOP_K], first))

print(f"失败 {len(fails)} 条（含排名 > {TOP_K} 的）\n")

for c, got, first in fails:
    meta = metas[c["target_store"]]
    print("=" * 76)
    print(f"[{c['id']}] {c['question']}")
    print(f"  期望行 {c['expected_rows']}：")
    for r in c["expected_rows"]:
        print(f"    → {brief(meta.get(r, {}), 150)}")
    print(f"  实得 Top-{TOP_K}（最佳命中位：{first or '无'}）：")
    for i, r in enumerate(got, 1):
        print(f"    {i}. [{r}] {brief(meta.get(r, {}))}")
    print()
