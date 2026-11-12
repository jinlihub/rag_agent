"""Agent 层评测：只评「工具选择 + 参数提取」，不含答案质量与检索召回。

在收到 stage=generating 时中断，不等生成完成——省时间省 token，
也让这一层只对「决策」负责，答案好坏归端到端评测管。

指标：
  工具命中率   期望工具是否被调用（寒暄类期望为空）
  首选工具率   第一个调用的工具是否就是期望工具
  参数命中率   expect_args 的每个键值是否都落在实际参数里
  平均调用次数 越少越好，重复相同调用记为冗余
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from rag_agent.agent.runner import run_agent_stream  # noqa: E402

CASES = Path(__file__).parent / "agent_set.jsonl"
REPORT_DIR = Path(__file__).parent / "reports"


def load_cases(limit: int | None, category: str | None):
    out = []
    with open(CASES, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if category and c.get("category") != category:
                continue
            out.append(c)
    return out[:limit] if limit else out


def collect_calls(question: str, allow_web: bool) -> tuple[list[dict], bool]:
    """跑到开始生成答案就停，收集工具调用；同时记录是否发出了澄清请求。

    clarify 是独立事件类型（不是 tool_call），提示词要求指代不明时用反问
    代替猜测，所以它必须单独统计，否则会被误判成「没调工具」。
    """
    calls: list[dict] = []
    clarified = False
    for ev in run_agent_stream(question, allow_web=allow_web):
        etype = ev.get("type")
        if etype == "clarify":
            clarified = True
            continue
        if etype != "status":
            continue
        stage = ev.get("stage")
        if stage == "tool_call":
            calls.append({"tool": ev.get("tool"), "args": ev.get("args") or {}})
        elif stage == "generating":
            break
    return calls, clarified


def arg_matches(expected: dict, actual: dict) -> tuple[bool, list[str]]:
    """期望的每个键值是否在实际参数里命中（子串匹配，忽略大小写）。"""
    if not expected:
        return True, []
    missing = []
    lower_actual = {k: str(v).lower() for k, v in actual.items()}
    for key, want in expected.items():
        got = lower_actual.get(key)
        if got is None or str(want).lower() not in got:
            missing.append(key)
    return (not missing), missing


def evaluate(case: dict) -> dict:
    calls, clarified = collect_calls(case["question"], bool(case.get("web")))
    tools = [c["tool"] for c in calls]
    expect = case.get("expect_tool")

    # expect_tool 支持字符串、列表（多工具均可）或 null（不应调工具）
    if expect is None:
        expects: list[str] = []
    elif isinstance(expect, str):
        expects = [expect]
    else:
        expects = list(expect)

    # ask_user 通过 clarify 事件实现，不属于 tool_call
    wants_clarify = "ask_user" in expects
    if wants_clarify:
        expects = [e for e in expects if e != "ask_user"]
        tool_hit = clarified
        first_ok = clarified
        arg_ok, missing = True, []
    elif not expects:
        tool_hit = len(calls) == 0
        first_ok = len(calls) == 0
        arg_ok, missing = True, []
    else:
        tool_hit = any(e in tools for e in expects)
        first_ok = bool(tools) and tools[0] in expects
        target = next((c for c in calls if c["tool"] in expects), None)
        arg_ok, missing = arg_matches(case.get("expect_args") or {}, target["args"] if target else {})

    # 冗余：完全相同的 (tool, 参数) 出现多次
    seen = set()
    redundant = 0
    for c in calls:
        sig = (c["tool"], json.dumps(c["args"], sort_keys=True, ensure_ascii=False))
        if sig in seen:
            redundant += 1
        seen.add(sig)

    return {
        "id": case["id"],
        "category": case.get("category", ""),
        "question": case["question"],
        "expect_tool": expect,
        "got_tools": tools,
        "got_args": [c["args"] for c in calls],
        "clarified": clarified,
        "tool_hit": int(tool_hit),
        "first_ok": int(first_ok),
        "arg_ok": int(arg_ok),
        "missing_args": missing,
        "n_calls": len(calls),
        "redundant": redundant,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="只跑前 N 条")
    ap.add_argument("--category", help="只跑某类别")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cases = load_cases(args.limit, args.category)
    print(f"Agent 层评测：{len(cases)} 条\n")

    results = []
    for i, c in enumerate(cases, 1):
        r = evaluate(c)
        results.append(r)
        mark = "✓" if (r["tool_hit"] and r["arg_ok"]) else "✗"
        detail = f"{r['got_tools'] or '(未调工具)'}"
        if r["missing_args"]:
            detail += f"  缺参数:{r['missing_args']}"
        print(f"  {i:>2}/{len(cases)} {mark} {r['id']:8} {detail}")
        if args.verbose and not (r["tool_hit"] and r["arg_ok"]):
            print(f"        期望 {r['expect_tool']} {r.get('expect_args') or ''}")
            print(f"        实得 {r['got_args']}")

    n = len(results)
    tool_hit = sum(r["tool_hit"] for r in results) / n
    first_ok = sum(r["first_ok"] for r in results) / n
    arg_ok = sum(r["arg_ok"] for r in results) / n
    avg_calls = sum(r["n_calls"] for r in results) / n
    redundant = sum(r["redundant"] for r in results)

    print(f"\n{'=' * 56}")
    print(f"工具命中率   {tool_hit * 100:5.1f}%")
    print(f"首选工具率   {first_ok * 100:5.1f}%")
    print(f"参数命中率   {arg_ok * 100:5.1f}%")
    print(f"平均调用次数 {avg_calls:.2f}   冗余调用 {redundant} 次")

    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    print("\n按类别：")
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        m = len(items)
        th = sum(x["tool_hit"] for x in items) / m
        ar = sum(x["arg_ok"] for x in items) / m
        print(f"  {cat:10} n={m:<2} 工具 {th * 100:5.1f}%  参数 {ar * 100:5.1f}%")

    fails = [r for r in results if not (r["tool_hit"] and r["arg_ok"])]
    if fails:
        print(f"\n未通过 {len(fails)} 条：")
        for r in fails:
            print(f"  {r['id']:8} 期望 {r['expect_tool']} {r.get('expect_args') or ''}")
            print(f"           实得 {r['got_tools']} {r['got_args']}")

    REPORT_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md = REPORT_DIR / f"agent_{ts}.md"
    lines = [
        f"# Agent 层评测 {ts}",
        "",
        f"- 用例数：{n}",
        f"- 工具命中率：{tool_hit * 100:.1f}%",
        f"- 首选工具率：{first_ok * 100:.1f}%",
        f"- 参数命中率：{arg_ok * 100:.1f}%",
        f"- 平均调用次数：{avg_calls:.2f}（冗余 {redundant} 次）",
        "",
        "## 明细",
        "",
        "| id | 类别 | 期望工具 | 实得工具 | 工具 | 参数 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['id']} | {r['category']} | {r['expect_tool'] or '(不调)'} | "
            f"{','.join(r['got_tools']) or '(无)'} | "
            f"{'✓' if r['tool_hit'] else '✗'} | {'✓' if r['arg_ok'] else '✗'} |"
        )
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n报告：{md}")


if __name__ == "__main__":
    main()
