"""临时探测：当前智谱 key 实际可调用哪些对话模型（1 token 最小请求）。用完即删。"""

from __future__ import annotations

import sys
import time

from rag_agent.clients.llm_factory import get_llm_client

CANDIDATES = [
    "glm-4.7-flashx",
    "glm-4.7-flash",
    "glm-4.6",
    "glm-4.5",
    "glm-4.5-air",
    "glm-4.5-x",
    "glm-4-flash",
    "glm-4-plus",
    "glm-4-long",
    "glm-4-0520-thinking",
]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    client = get_llm_client()
    for m in CANDIDATES:
        t0 = time.perf_counter()
        try:
            resp = client.chat(
                [{"role": "user", "content": "说一个字"}], model=m, temperature=0.1, timeout=30
            )
            print(f"{m:24s} OK   {time.perf_counter() - t0:5.2f}s  {resp.choices[0].message.content!r:.30}")
        except Exception as e:  # noqa: BLE001
            print(f"{m:24s} FAIL {time.perf_counter() - t0:5.2f}s  {type(e).__name__}: {str(e)[:110]}")
        time.sleep(1.2)


if __name__ == "__main__":
    main()
