"""诊断单个问题走了哪条路径：意图判定 → 是否有澄清 → 调了哪些工具。

用于查「该反问却直接作答」「该查工具却没查」这类路径问题。
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.agent.runner import run_agent_stream  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ap = argparse.ArgumentParser()
ap.add_argument("questions", nargs="+", help="要诊断的问题（可多个）")
args = ap.parse_args()

for q in args.questions:
    print("=" * 78)
    print(f"问题：{q}")

    intent = ""
    events = []
    answer = ""
    for ev in run_agent_stream(q, allow_web=False):
        t = ev.get("type")
        if t == "status":
            stage = ev.get("stage")
            if stage == "analysis":
                txt = str(ev.get("text") or "")
                if "意图识别" in txt:
                    intent = txt
                events.append(f"analysis: {txt[:60]}")
            elif stage == "tool_call":
                events.append(f"tool_call: {ev.get('tool')} {ev.get('args') or ''}")
            elif stage == "quality":
                events.append(f"quality: {ev.get('tool')} → {ev.get('verdict')}")
            elif stage in ("thinking", "generating"):
                events.append(f"{stage}")
        elif t == "clarify":
            events.append(f"★ clarify: {ev.get('question')} options={ev.get('options')}")
        elif t == "delta":
            answer += ev.get("text", "")
        elif t == "done":
            break

    print(f"  意图: {intent or '(无意图事件)'}")
    print("  事件流:")
    for e in events:
        print(f"    - {e}")
    print(f"  答案: {' '.join(answer.split())[:100]}")
    print()
