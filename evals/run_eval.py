"""Agent 评估体系运行器：评估集 → Agent 实测 → 自动指标 + LLM 评审 → 报告。

数据集 evals/dataset.jsonl，每行一个用例：
    {"id": "kb-001", "category": "知识库", "question": "...", "web": false,
     "expect_tools": ["search_bidding_knowledge"],  # 期望命中的工具（缺省不检查）
     "keywords": ["2%"],                            # 答案或来源标题应含的关键词（缺省不检查）
     "reference": "参考答案要点（给评审用）", "note": "备注"}

评估维度：
    自动 —— 期望工具命中率 / 关键词通过率 / 各阶段与总用时 / 运行错误
    评审 —— DeepSeek 独立打分：正确性 / 忠实度 / 完整性（1-5，见 judge.py）
直接调用 run_agent_stream（不落问答记录），需要 MySQL/PostgreSQL/LLM/Tavily 可用。

用法:
    uv run python evals/run_eval.py                     # 全量评估
    uv run python evals/run_eval.py --limit 3           # 前 3 条冒烟
    uv run python evals/run_eval.py --category 联网      # 只跑某类别
    uv run python evals/run_eval.py --no-judge          # 跳过 LLM 评审
    uv run python evals/run_eval.py --concurrency 4     # 并发数（默认 2）
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

_EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_EVAL_DIR))

from judge import judge_answer, make_judge_client  # noqa: E402
from rag_agent.agent.runner import run_agent_stream  # noqa: E402

_DATASET = _EVAL_DIR / "dataset.jsonl"
_REPORTS = _EVAL_DIR / "reports"
_PASS_SCORE = 3  # 评审各维度及格线


def load_dataset(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for no, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError as e:
            raise SystemExit(f"数据集第 {no} 行不是合法 JSON: {e}")
        if not obj.get("id") or not obj.get("question"):
            raise SystemExit(f"数据集第 {no} 行缺少 id/question")
        cases.append(obj)
    if not cases:
        raise SystemExit(f"数据集为空: {path}")
    return cases


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """跑一个用例：收集事件流 → 回答/工具轨迹/来源/耗时 + 自动指标。"""
    out: dict[str, Any] = {
        "id": case["id"], "category": case.get("category", ""), "question": case["question"],
        "web": bool(case.get("web")), "answer": "", "tools": [], "quality": [],
        "sources": [], "stages": [], "total_seconds": None, "error": "",
        "expect_tools": case.get("expect_tools"), "keywords": case.get("keywords", []),
        "reference": case.get("reference", ""),
    }
    t0 = time.perf_counter()
    try:
        for ev in run_agent_stream(case["question"], allow_web=out["web"]):
            t = ev.get("type")
            if t == "status" and ev.get("stage") == "tool_call":
                out["tools"].append(ev.get("tool", ""))
            elif t == "status" and ev.get("stage") == "quality":
                out["quality"].append({"tool": ev.get("tool"), "verdict": ev.get("verdict")})
            elif t == "delta":
                out["answer"] += ev.get("text", "")
            elif t == "sources":
                out["sources"] = [
                    {"kind": s.get("kind", ""), "title": s.get("title", "")} for s in ev.get("items", [])
                ]
            elif t == "timing":
                out["stages"] = ev.get("stages", [])
                out["total_seconds"] = ev.get("total")
            elif t == "error":
                out["error"] = ev.get("message", "")
    except Exception as e:  # noqa: BLE001 —— 单用例失败不阻断整轮评估
        out["error"] = f"{type(e).__name__}: {e}"
    out["wall_seconds"] = round(time.perf_counter() - t0, 2)
    exp = out["expect_tools"]
    out["tool_hit"] = None if exp is None else bool(set(out["tools"]) & set(exp))
    haystack = _normalize(out["answer"] + "\n" + "\n".join(s["title"] for s in out["sources"]))
    found = [k for k in out["keywords"] if k and _normalize(k) in haystack]
    out["keyword_hits"] = found
    out["keyword_pass"] = None if not out["keywords"] else len(found) == len(out["keywords"])
    return out


def judge_cases(results: list[dict[str, Any]], model: str, concurrency: int) -> None:
    """DeepSeek 并发评审，结果写回各 result["judge"]（失败记 "error"）。"""
    client, judge_model = make_judge_client()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {
            pool.submit(
                judge_answer, client, judge_model,
                r["question"], r.get("reference", ""), [s["title"] for s in r["sources"]], r["answer"],
            ): r
            for r in results
        }
        for fut, r in futs.items():
            try:
                r["judge"] = fut.result()
            except Exception as e:  # noqa: BLE001 —— 评审失败不影响其他用例
                r["judge"] = {"error": str(e)[:200]}


def _normalize(text: str) -> str:
    """关键词匹配前归一化：NFKC 统一全半角 + 去掉所有空白。

    中文里空格差异很常见（"7 个工作日" vs "7个工作日"），裸子串匹配会误判为未命中。
    注意这只能消除格式差异，消除不了"2%"与"百分之二"这类语义等价——关键词指标
    因此只作粗筛，主判据仍是 LLM 评审的三维分数。
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def _fmt(v: Any) -> str:
    return "—" if v is None else str(v)


def write_reports(results: list[dict[str, Any]], run_id: str) -> tuple[Path, Path, Path]:
    """写 JSONL 明细 + summary.md + summary.xlsx，返回三个路径。"""
    _REPORTS.mkdir(parents=True, exist_ok=True)
    jsonl_path = _REPORTS / f"run_{run_id}.jsonl"
    md_path = _REPORTS / f"run_{run_id}_summary.md"
    xlsx_path = _REPORTS / f"run_{run_id}_summary.xlsx"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ── 聚合 ──
    latencies = [r["total_seconds"] for r in results if isinstance(r["total_seconds"], (int, float))]
    tool_counter = Counter(t for r in results for t in r["tools"])
    checked = [r for r in results if r["tool_hit"] is not None]
    tool_hit = sum(1 for r in checked if r["tool_hit"])
    kw_checked = [r for r in results if r["keyword_pass"] is not None]
    kw_pass = sum(1 for r in kw_checked if r["keyword_pass"])
    judged = [r for r in results if isinstance(r.get("judge"), dict) and "error" not in r["judge"]]
    dims = ("correctness", "faithfulness", "completeness")
    dim_avg = {d: round(statistics.mean(r["judge"][d] for r in judged), 2) for d in dims} if judged else {}
    passed = sum(
        1 for r in judged
        if not r["error"] and all(r["judge"][d] >= _PASS_SCORE for d in dims)
    )

    lines = [
        f"# Agent 评估报告 {run_id}",
        "",
        f"- 用例 {len(results)} · 运行错误 {sum(1 for r in results if r['error'])}",
        f"- 总用时：平均 {round(statistics.mean(latencies), 1) if latencies else '—'}s ·"
        f" 中位 {round(statistics.median(latencies), 1) if latencies else '—'}s",
        f"- 工具调用分布：{' · '.join(f'{k}×{v}' for k, v in tool_counter.most_common()) or '—'}",
        f"- 期望工具命中 {tool_hit}/{len(checked)} · 关键词通过 {kw_pass}/{len(kw_checked)}",
        f"- 评审（{len(judged)} 例）："
        + " · ".join(f"{d} {v}" for d, v in dim_avg.items())
        + f" · 通过率 {passed}/{len(judged)}（各维 ≥ {_PASS_SCORE}）",
        "",
        "| id | 类别 | 问题 | 工具 | 用时s | 工具命中 | 关键词 | 正确性 | 忠实度 | 完整性 | 评审意见 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        j = r.get("judge") or {}
        judge_cells = (
            "ERR"
            if "error" in j
            else " / ".join(_fmt(j.get(d)) for d in dims) + f" {j.get('comment', '')[:40]}"
        ) if j else "未评"
        lines.append(
            f"| {r['id']} | {r['category']} | {r['question'][:24]} | "
            f"{('·'.join(r['tools']) or '无工具')[:40]} | {_fmt(r['total_seconds'])} | "
            f"{_fmt(r['tool_hit'])} | {_fmt(r['keyword_pass'])} | {judge_cells} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    header = ["id", "类别", "问题", "web", "工具轨迹", "用时s", "工具命中", "关键词通过", "关键词命中",
              "正确性", "忠实度", "完整性", "评审意见", "运行错误", "回答"]
    ws.append(header)
    for r in results:
        j = r.get("judge") or {}
        ws.append([
            r["id"], r["category"], r["question"], r["web"], " · ".join(r["tools"]),
            r["total_seconds"], _fmt(r["tool_hit"]), _fmt(r["keyword_pass"]),
            " ".join(r["keyword_hits"]),
            j.get("correctness", ""), j.get("faithfulness", ""), j.get("completeness", ""),
            j.get("comment", "") if "error" not in j else f"评审失败: {j.get('error')}",
            r["error"], r["answer"][:2000],
        ])
    ws2 = wb.create_sheet("汇总")
    ws2.append(["指标", "值"])
    ws2.append(["用例数", len(results)])
    ws2.append(["平均总用时s", round(statistics.mean(latencies), 1) if latencies else ""])
    ws2.append(["中位总用时s", round(statistics.median(latencies), 1) if latencies else ""])
    ws2.append(["期望工具命中", f"{tool_hit}/{len(checked)}"])
    ws2.append(["关键词通过", f"{kw_pass}/{len(kw_checked)}"])
    for d, v in dim_avg.items():
        ws2.append([f"评审平均·{d}", v])
    ws2.append(["评审通过率", f"{passed}/{len(judged)}"])
    ws2.append(["工具调用分布", json.dumps(dict(tool_counter), ensure_ascii=False)])
    wb.save(xlsx_path)
    return jsonl_path, md_path, xlsx_path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Agent 评估运行器")
    ap.add_argument("--dataset", type=Path, default=_DATASET, help="评估集 JSONL（默认 %(default)s）")
    ap.add_argument("--limit", type=int, help="只跑前 N 条（冒烟）")
    ap.add_argument("--category", help="只跑指定类别")
    ap.add_argument("--no-judge", action="store_true", help="跳过 LLM 评审")
    ap.add_argument("--judge-model", default="", help="评审模型（默认 deepseek-chat）")
    ap.add_argument("--concurrency", type=int, default=2, help="并发数（默认 %(default)s）")
    args = ap.parse_args()

    cases = load_dataset(args.dataset)
    if args.category:
        cases = [c for c in cases if c.get("category") == args.category]
    if args.limit:
        cases = cases[: args.limit]
    print(f"评估用例 {len(cases)} 条（concurrency={args.concurrency}，judge={'off' if args.no_judge else 'on'}）")

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for i, r in enumerate(pool.map(run_case, cases), start=1):
            flag = "✗" if r["error"] else "✓"
            print(f"[{i}/{len(cases)}] {flag} {r['id']} 用时 {_fmt(r['total_seconds'])}s "
                  f"工具 {'·'.join(r['tools']) or '无'}")
            results.append(r)

    if not args.no_judge:
        print("LLM 评审中（DeepSeek）…")
        try:
            judge_cases(results, args.judge_model or "deepseek-chat", args.concurrency)
        except RuntimeError as e:
            print(f"跳过评审: {e}")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path, md_path, xlsx_path = write_reports(results, run_id)
    print(f"\n报告已生成：\n  明细 {jsonl_path}\n  摘要 {md_path}\n  Excel {xlsx_path}")


if __name__ == "__main__":
    main()
