"""对比不同模型的工具调用能力：同一套 prompt + 同一套工具 Schema，只换模型。

只发一次请求、不执行工具——测的是「选工具 + 拼参数」这一层的纯粹能力，
不受工具返回内容与生成质量干扰。

用法（在能访问目标端点的地方执行）：
    # 线上模型（智谱）
    uv run python evals/compare_tool_calling.py --label GLM-4.5-Air

    # 服务器上的本地模型
    uv run python evals/compare_tool_calling.py \
        --label Qwen3-4B --base-url http://127.0.0.1:8081/v1 \
        --model Qwen/Qwen3-4B-Instruct-2507

输出：工具命中率、参数命中率、平均耗时，以及逐条的工具选择明细。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402
from openai import OpenAI  # noqa: E402

load_dotenv(_ROOT / ".env")

from rag_agent.agent.agent import Agent  # noqa: E402
from rag_agent.agent.prompt import build_system_prompt  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CASES = _ROOT / "evals" / "agent_set.jsonl"


def load_cases() -> list[dict]:
    return [json.loads(l) for l in open(CASES, encoding="utf-8") if l.strip()]


def arg_hit(expected: dict, actual: dict) -> bool:
    if not expected:
        return True
    low = {k: str(v).lower() for k, v in actual.items()}
    for k, want in expected.items():
        got = low.get(k)
        if got is None or str(want).lower() not in got:
            return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="model", help="输出里显示的名字")
    ap.add_argument("--base-url", default="https://open.bigmodel.cn/api/paas/v4")
    ap.add_argument("--model", default=os.getenv("LLM_TOOL_MODEL") or "glm-4.5-air")
    ap.add_argument("--api-key", default=os.getenv("LLM_API_KEY") or "dummy")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    client = OpenAI(api_key=args.api_key, base_url=args.base_url)
    _, tools_off = Agent()._tool_views(allow_web=False)
    _, tools_on = Agent()._tool_views(allow_web=True)
    system = build_system_prompt()

    cases = load_cases()
    if args.limit:
        cases = cases[: args.limit]

    print(f"模型 {args.label}（{args.model}）@ {args.base_url}")
    print(f"用例 {len(cases)} 条；不联网时可用工具 {[t.name for t in tools_off.values()]}\n")

    tool_hit = arg_ok = 0
    latencies: list[float] = []
    rows = []

    for i, c in enumerate(cases, 1):
        expect = c.get("expect_tool")
        expects = [] if expect is None else ([expect] if isinstance(expect, str) else list(expect))
        # ask_user 与 talk 工具同名，单独判定「是否调了它」
        wants_clarify = "ask_user" in expects
        expects = [e for e in expects if e != "ask_user"]
        # 联网用例要给联网工具，否则模型只能退而查本地库
        pool = tools_on if c.get("web") else tools_off
        schemas = [t.openai_schema for t in pool.values()]

        t0 = time.perf_counter()
        try:
            resp = client.chat.completions.create(
                model=args.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": c["question"]},
                ],
                tools=schemas,
                temperature=0.2,
                max_tokens=512,
            )
            msg = resp.choices[0].message
            calls = [
                {"name": tc.function.name, "args": json.loads(tc.function.arguments or "{}")}
                for tc in (msg.tool_calls or [])
            ]
            err = ""
        except Exception as e:  # noqa: BLE001
            calls, err = [], f"{type(e).__name__}: {e}"
        latencies.append((time.perf_counter() - t0) * 1000)

        names = [x["name"] for x in calls]
        if wants_clarify:
            hit = "ask_user" in names
            aok = True
        elif not expects:
            hit = len(calls) == 0
            aok = True
        else:
            hit = any(e in names for e in expects)
            target = next((x for x in calls if x["name"] in expects), None)
            aok = bool(target) and arg_hit(c.get("expect_args") or {}, target["args"])

        tool_hit += int(hit)
        arg_ok += int(aok)
        mark = "OK" if (hit and aok) else "NG"
        detail = names or ("(不调工具)" if not expects else "(未调)")
        print(f"  {i:>2}/{len(cases)} {mark} {c['id']:8} {detail}"
              + (f"  {calls[0]['args']}" if calls else "")
              + (f"  ⚠{err[:60]}" if err else ""))
        rows.append({"id": c["id"], "expect": expect, "got": names, "hit": hit, "arg_ok": aok})

    n = len(cases)
    print(f"\n{'=' * 56}")
    print(f"工具命中率  {tool_hit / n * 100:5.1f}%")
    print(f"参数命中率  {arg_ok / n * 100:5.1f}%")
    if latencies:
        print(f"平均耗时    {statistics.mean(latencies):.0f} ms"
              f"（P50 {statistics.median(latencies):.0f} ms）")

    out = _ROOT / "evals" / "reports" / f"toolcalling_{args.label}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "label": args.label,
                "model": args.model,
                "base_url": args.base_url,
                "n": n,
                "tool_hit_rate": round(tool_hit / n, 4),
                "arg_hit_rate": round(arg_ok / n, 4),
                "avg_ms": round(statistics.mean(latencies)) if latencies else None,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"明细：{out}")


if __name__ == "__main__":
    main()
