"""验证意图路由与检索范围：确认知识类问题能查到法规，而不是只查 FAQ。"""

import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.agent.runner import run_agent_stream  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

QUESTIONS = [
    ("法规-公告", "公开招标的公告要发在哪些地方？公告里必须写哪些内容？"),
    ("实务-保证金", "投标保证金最晚什么时候退？"),
    ("概念-招标方式", "公开招标和邀请招标到底有什么区别？"),
    ("实务-质疑时限", "质疑、询问的答复期限各是多少？"),
]

for label, q in QUESTIONS:
    print("=" * 78)
    print(f"[{label}] {q}")

    intent, tools, kinds, answer = "", [], Counter(), ""
    for ev in run_agent_stream(q, allow_web=False):
        t = ev.get("type")
        if t == "status":
            stage = ev.get("stage")
            if stage == "tool_call":
                tools.append(ev.get("tool", ""))
            elif stage == "analysis":
                txt = str(ev.get("text") or "")
                if "意图识别" in txt:
                    intent = txt.replace("意图识别：", "").strip()
        elif t == "delta":
            answer += ev.get("text", "")
        elif t == "sources":
            for s in ev.get("items", []):
                kinds[s.get("kind", "?")] += 1

    print(f"  意图: {intent or '(未输出)'}")
    print(f"  工具: {tools}")
    print(f"  来源: {dict(kinds) or '(无)'}")
    print(f"  答案: {' '.join(answer.split())[:110]}")
    print()
