"""命令行冒烟测试：直接跑 agent 事件流（不经 HTTP），观察工具调用与流式回答。

用法: uv run python scripts/smoke_test.py "近半年安徽合肥区域有哪些企业中标？"
      uv run python scripts/smoke_test.py --web "近半年合肥有哪些企业中标？"   # 开启联网搜索
      uv run python scripts/smoke_test.py --deep "法条竞合时如何适用？"        # 开启深度思考

意图路由回归（观察 [分析] 意图识别 与后续工具/耗时）：
      uv run python scripts/smoke_test.py "你好"                              # chitchat：不调工具
      uv run python scripts/smoke_test.py "供应商提出质疑的时限是多少天？"      # faq：只查一次 FAQ
      uv run python scripts/smoke_test.py "近半年安徽合肥区域有哪些企业中标？"  # complex：完整 ReAct
"""

from __future__ import annotations

import json
import sys
import time

from rag_agent.agent.runner import run_agent_stream


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = [a for a in sys.argv[1:] if a not in ("--web", "--deep")]
    allow_web = "--web" in sys.argv
    deep = "--deep" in sys.argv
    question = argv[0] if argv else "近半年安徽合肥区域有哪些企业中标？"
    print(f"问题: {question}（联网搜索：{'开' if allow_web else '关'}；深度思考：{'开' if deep else '关'}）\n")
    t0 = time.perf_counter()
    in_reasoning = False
    for ev in run_agent_stream(question, allow_web=allow_web, deep_thinking=deep):
        t = ev["type"]
        if t == "delta":
            if in_reasoning:
                print("\n[回答]\n", end="")
                in_reasoning = False
            print(ev["text"], end="", flush=True)
        elif t == "reasoning":
            if not in_reasoning:
                print("\n[思考] ", end="")
                in_reasoning = True
            print(ev["text"], end="", flush=True)
        elif t == "status":
            if ev["stage"] == "analysis":
                print(f"\n[分析] {ev.get('text', '')}")
            elif ev["stage"] == "quality":
                print(f"\n[质量] {ev.get('tool')} → {ev.get('verdict')}：{ev.get('text', '')}")
            else:
                suffix = f" {ev['tool']}({json.dumps(ev.get('args', ''), ensure_ascii=False)})" if ev.get("tool") else ""
                print(f"\n[{ev['stage']}]{suffix}")
        elif t == "clarify":
            print(f"\n[澄清] {ev['question']}")
            for o in ev.get("options", []):
                print(f"   · {o}")
        elif t == "sources":
            print(f"\n-- 来源 {len(ev['items'])} 条:")
            for s in ev["items"][:5]:
                print(f"   · [{s['kind']}] {s['title']}")
        elif t == "timing":
            stages = " · ".join(f"{s.get('tool') or s['key']} {s['seconds']}s" for s in ev["stages"])
            print(f"\n[timing] {stages} | 总用时 {ev['total']}s")
        elif t == "error":
            print(f"\n[error] {ev['message']}")
    print(f"\n[耗时 {time.perf_counter() - t0:.1f}s]")


if __name__ == "__main__":
    main()
