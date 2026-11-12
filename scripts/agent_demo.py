"""演示：RAG 能力注册成工具 + Agent 自动调用并作答。

用法：
    PYTHONIOENCODING=utf-8 uv run python scripts/agent_demo.py               # 跑内置示例
    PYTHONIOENCODING=utf-8 uv run python scripts/agent_demo.py "自定义问题"  # 跑单个问题
"""

from __future__ import annotations

import sys
import time

from rag_agent.agent.agent import Agent
from rag_agent.tools import TOOL_REGISTRY

DEMO_QUESTIONS = [
    "供应商提出质疑的时限是多少天？",      # 法规类 → 自动走知识库向量工具（FAQ/法条）
    "合肥最近有哪些企业中标？金额多少？",  # 数据类 → 自动走 PostgreSQL 工具（中标记录）
]


def run(question: str) -> None:
    agent = Agent()
    print(f"\n{'=' * 60}\n问题: {question}\n{'=' * 60}")
    print(f"已注册工具: {', '.join(sorted(TOOL_REGISTRY))}")
    t0 = time.perf_counter()
    answer: list[str] = []
    for ev in agent.run_stream(question):
        if ev["type"] == "status":
            if ev["stage"] == "tool_call":
                print(f"\n[Agent 自动调用] {ev['tool']}({ev['args']})")
            elif ev["stage"] == "generating":
                print("\n[回答]")
        elif ev["type"] == "sources":
            print("[来源]")
            for s in ev["items"]:
                print(f"  · [{s['kind']}] {s['title']}")
        elif ev["type"] == "delta":
            answer.append(ev["text"])
        elif ev["type"] == "error":
            print(f"\n[错误] {ev['message']}")
    print("".join(answer))
    print(f"[耗时 {time.perf_counter() - t0:.1f}s]")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(sys.argv[1])
    else:
        for q in DEMO_QUESTIONS:
            run(q)
