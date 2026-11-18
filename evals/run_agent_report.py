"""Agent 综合评估报告：跑一遍评估集，把工具选择、RAGAS 三维、延迟压成一页文本报告。

与 `run_eval.py` 的分工：
  - `run_eval.py` 是明细型评估（14 条 × 正确性/忠实度/完整性 1-5 分，出 JSONL + Markdown + Excel）；
  - 本脚本是汇报型：同一套用例、同一个 `run_agent_stream`，但按 RAGAS 口径给
    Faithfulness / Relevancy / Recall 三个 0~1 分，合成「综合评分」与「Agent 评分」，
    直接写出 `Agent评估报告.txt`。适合贴进周报、交给老师看。

指标口径：
  工具选择准确率 = 声明了 expect_tools 的用例中，实际调用命中期望工具的占比
  Faithfulness   = 回答里的事实断言能否被检索来源支撑（编造即低分）
  Relevancy      = 回答是否直接回应问题（不跑题、不空泛）
  Recall         = 检索来源是否覆盖回答所需的关键信息（对照参考要点）
  综合评分        = 三个 RAG 维度全部有效值的均值
  Agent 评分      = 0.6 × 综合评分 + 0.4 × 工具选择准确率

评审维度解析失败时该维度记 None、不计入有效值，用例列入「失败用例」，不影响其他用例——
这一条沿用评分报告的常见约定，避免一次 JSON 抖动把整轮指标带偏。

用法：
    uv run python evals/run_agent_report.py                # 全量，写 Agent评估报告.txt
    uv run python evals/run_agent_report.py --limit 3      # 冒烟
    uv run python evals/run_agent_report.py --no-judge     # 只跑自动指标
    uv run python evals/run_agent_report.py --out x.txt    # 指定输出文件
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

_EVAL_DIR = Path(__file__).resolve().parent
_ROOT = _EVAL_DIR.parent
sys.path.insert(0, str(_EVAL_DIR))
sys.path.insert(0, str(_ROOT / "src"))

import run_eval  # noqa: E402 —— 复用 load_dataset / run_case / _normalize
from judge import RAG_DIMENSIONS, judge_rag_answer, make_judge_client  # noqa: E402
from rag_agent.tools.base import BaseTool  # noqa: E402
from rag_agent.tools.rag_tools import TOOL_REGISTRY  # noqa: E402

_REPORTS = _EVAL_DIR / "reports"
_DEFAULT_OUT = _ROOT / "Agent评估报告.txt"
_DIM_LABEL = {"faithfulness": "Faith", "relevancy": "Relevancy", "recall": "Recall"}

# ── 工具结果采集 ────────────────────────────────────────────────────────
# 报告要判「回答有没有被来源支撑」，但 SSE 的 sources 事件只带标题与元数据。
# 这里在评测进程内挂一层 execute 钩子，把工具原文节选收下来喂给评审——
# 只改评测进程，不动应用代码；threading.local 保证并发用例互不串味。
_TLS = threading.local()
_ORIGINAL_EXECUTE = BaseTool.execute


def _recording_execute(self: BaseTool, raw_args: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _ORIGINAL_EXECUTE(self, raw_args)
    buf = getattr(_TLS, "records", None)
    if buf is not None:
        args = {k: v for k, v in (raw_args or {}).items() if v not in (None, "", [])} if isinstance(raw_args, dict) else {}
        buf.append((self.name, args, result))
    return result


def _install_recorder() -> None:
    if BaseTool.execute is not _recording_execute:
        BaseTool.execute = _recording_execute  # noqa: B010 —— 仅评测进程内生效


def _result_rows(name: str, result: dict[str, Any]) -> list[Any]:
    """取工具结果的条目列表：优先走工具自己的 source_items。

    各工具返回结构并不统一——知识库/联网是 `matches`，PG 是 `rows`，
    图谱是嵌套的 `edges`（按关系分组）。统一走 source_items 才不会漏采。
    """
    tool = TOOL_REGISTRY.get(name)
    rows = tool.source_items(result) if tool is not None else None
    if rows is None:
        rows = result.get("rows") or result.get("matches") or []
    return rows


def _render_row(row: Any) -> str:
    """单条结果 → 一行紧凑文本。

    结构化的行（PG 记录、图谱边）字段多且顺序不定，直接 json.dumps 再截断会把
    金额、时间这些关键字段切掉，评审因此判回答「编造」（实测 pg-002 掉到 0.00）。
    这里先抽文本字段，其余按 `键=值` 压平，保证关键信息都留在截断范围内。
    """
    if not isinstance(row, dict):
        return f"- {row}"[:400]
    text = row.get("text") or row.get("content") or row.get("question")
    title = row.get("title") or row.get("law_name") or ""
    if text:
        return (f"- {title}：{text}" if title else f"- {text}")[:400]
    bits = [f"{k}={str(v)[:80]}" for k, v in row.items() if v not in (None, "", [])]
    return ("- " + "；".join(bits))[:400] if bits else "- {}"


def _format_context(records: list[tuple[str, dict, Any]], limit_rows: int = 12) -> str:
    """工具执行记录 → 给评审看的上文（每条结果 400 字，总量由调用方截断）。

    limit_rows 不能太小：PG 一次返回几十行，回答常列出十余条，只给前 5 行会让评审
    把真实记录判成编造（实测 pg-003 的 Faithfulness 因此被压到 0.10）。
    """
    parts: list[str] = []
    for name, args, result in records:
        if not isinstance(result, dict) or result.get("error"):
            continue
        rows = _result_rows(name, result)
        if not rows:
            continue
        parts.append(f"## 工具 {name}（参数 {json.dumps(args, ensure_ascii=False)[:120]}）")
        parts.extend(_render_row(row) for row in rows[:limit_rows])
    return "\n".join(parts)


def run_case_traced(case: dict[str, Any]) -> dict[str, Any]:
    """跑一个用例并附带工具原文；run_case 自身已把异常折叠成 error 字段。"""
    _TLS.records = []
    try:
        r = run_eval.run_case(case)
    finally:
        records = getattr(_TLS, "records", [])
        _TLS.records = None
    # expect_tools 允许写成字符串，set("abc") 会按字符切分，这里统一成列表再判
    exp = r.get("expect_tools")
    if isinstance(exp, str):
        exp = [exp]
    r["expect_tools"] = exp
    r["tool_hit"] = None if exp is None else bool(set(r["tools"]) & set(exp))
    r["tool_records"] = [{"tool": n, "args": a} for n, a, _ in records]
    r["context"] = _format_context(records)
    return r


# ── 评审 ────────────────────────────────────────────────────────────────


def judge_all(results: list[dict[str, Any]], model: str, concurrency: int) -> None:
    """并发调用 RAGAS 三维评审，写回 r["rag"]；运行失败的用例直接跳过评审。"""
    client, judge_model = make_judge_client()
    target = [r for r in results if not r["error"]]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = {
            pool.submit(
                judge_rag_answer, client, model or judge_model,
                r["question"], r.get("reference", ""), r.get("context", ""), r["answer"],
            ): r
            for r in target
        }
        for fut, r in futs.items():
            try:
                r["rag"] = fut.result()
            except Exception as e:  # noqa: BLE001 —— 单条评审失败不影响其他用例
                r["rag"] = {**{d: None for d in RAG_DIMENSIONS}, "comment": "", "error": str(e)[:200]}
    for r in results:
        if r["error"]:
            r["rag"] = {**{d: None for d in RAG_DIMENSIONS}, "comment": "", "error": "用例运行失败，已跳过评审"}
        elif not r["tools"]:
            # 寒暄/无关类不调工具，没有检索来源可言——Recall 记「不适用」而不是 0 分，
            # 否则「如实拒答」会被按检索失败扣分，拖低整轮 RAG 得分。
            r["rag"]["recall"] = None
            note = "未检索，Recall 不适用"
            r["rag"]["comment"] = f"{r['rag'].get('comment') or ''}（{note}）"


# ── 统计 ────────────────────────────────────────────────────────────────


def _pct(n: int, d: int) -> str:
    return f"{n / d * 100:.1f}%" if d else "n/a"


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def _latency(r: dict[str, Any]) -> float:
    """单用例延迟：优先 Agent 自报的 timing.total，缺失时用墙钟。"""
    t = r.get("total_seconds")
    return float(t) if isinstance(t, (int, float)) else float(r.get("wall_seconds") or 0.0)


def _applicable(r: dict[str, Any], dim: str) -> bool:
    """Recall 只在真的有检索来源时才有意义；Faithfulness/Relevancy 始终可评。"""
    return dim != "recall" or bool(r["tools"])


def _dim_values(results: list[dict[str, Any]], dim: str) -> list[float]:
    vals = []
    for r in results:
        if not _applicable(r, dim):
            continue
        v = (r.get("rag") or {}).get(dim)
        if isinstance(v, (int, float)):
            vals.append(float(v))
    return vals


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    checked = [r for r in results if r["tool_hit"] is not None]
    tool_hits = sum(1 for r in checked if r["tool_hit"])
    tool_acc = tool_hits / len(checked) if checked else None

    dim_stats = {d: _dim_values(results, d) for d in RAG_DIMENSIONS}
    dim_avg = {d: _mean(v) for d, v in dim_stats.items()}
    all_vals = [v for vals in dim_stats.values() for v in vals]
    rag_score = _mean(all_vals)
    agent_score = (
        round(0.6 * rag_score + 0.4 * tool_acc, 2)
        if rag_score is not None and tool_acc is not None else None
    )

    latencies = [_latency(r) for r in results]
    failures = []
    for i, r in enumerate(results, start=1):
        reasons = []
        if r["error"]:
            reasons.append(f"运行错误：{r['error'][:80]}")
        else:
            rag = r.get("rag") or {}
            for d in RAG_DIMENSIONS:
                if rag.get(d) is None and _applicable(r, d):
                    reasons.append(f"{_DIM_LABEL[d]} 评分解析失败")
            if rag.get("error") and not reasons:
                reasons.append(rag["error"])
        if reasons:
            failures.append((i, r, "；".join(dict.fromkeys(reasons))))

    # 未声明 expect_tools 的用例（寒暄/无关/违规）不适合算准确率，单独看有没有误调用
    free_cases = [r for r in results if r.get("expect_tools") is None]
    return {
        "checked": len(checked),
        "tool_hits": tool_hits,
        "tool_acc": tool_acc,
        "dim_stats": dim_stats,
        "dim_avg": dim_avg,
        "rag_score": rag_score,
        "agent_score": agent_score,
        "latencies": latencies,
        "failures": failures,
        "free_cases": free_cases,
        "free_misused": sum(1 for r in free_cases if r["tools"]),
        "recall_applicable": sum(1 for r in results if r["tools"]),
    }


# ── 报告渲染 ────────────────────────────────────────────────────────────


def _w(s: str) -> int:
    """显示宽度：中文按 2 列算，保证等宽字体下表格不歪。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _w(s))


def _clip(s: str, width: int) -> str:
    """按显示宽度截断并补省略号，防止长工具名把整行挤歪。"""
    if _w(s) <= width:
        return s
    out, w = "", 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > width - 1:
            break
        out += ch
        w += cw
    return out + "…"


def _num(v: float | None, nd: int = 2) -> str:
    return "n/a" if v is None else f"{v:.{nd}f}"


def render(results: list[dict[str, Any]], stats: dict[str, Any], dataset: Path, run_ts: str) -> str:
    n = len(results)
    lw = 18  # 指标名一列的统一显示宽度（「（另）无需工具用例」= 18 列，最宽）
    out: list[str] = []
    bar = "=" * 59
    out.append(bar)
    out.append("  Agent 综合评估报告")
    out.append(bar)
    out.append(f"  {_pad('生成时间', lw)}: {run_ts}")
    out.append(f"  {_pad('评测集', lw)}: {dataset.name}")
    out.append(f"  {_pad('测试用例', lw)}: {n}")
    out.append(f"  {_pad('工具选择准确率', lw)}: {stats['tool_hits']}/{stats['checked']} "
               f"({_pct(stats['tool_hits'], stats['checked'])})")
    if stats["free_cases"]:
        out.append(f"  {_pad('（另）无需工具用例', lw)}: {len(stats['free_cases'])} 条，误调用 "
                   f"{stats['free_misused']} 条")
    for d in RAG_DIMENSIONS:
        vals = stats["dim_stats"][d]
        label = {"faithfulness": "Faithfulness", "relevancy": "Relevancy", "recall": "Recall"}[d]
        total = stats["recall_applicable"] if d == "recall" else n
        skipped = f"，{n - total} 条未检索不适用" if d == "recall" and total < n else ""
        out.append(f"  {_pad(label, lw)}: {_num(stats['dim_avg'][d])}  "
                   f"[有效 {len(vals)}/{total}{skipped}]")
    lats = stats["latencies"]
    if lats:
        out.append(f"  {_pad('平均延迟', lw)}: {statistics.mean(lats):.1f}s "
                   f"(min {min(lats):.1f}s, max {max(lats):.1f}s, 中位 {statistics.median(lats):.1f}s)")
    out.append(f"  {_pad('综合评分', lw)}: {_num(stats['rag_score'])} / 1.00")
    out.append(f"  {_pad('Agent评分', lw)}: {_num(stats['agent_score'])} "
               f"(RAG权重0.6 + 工具权重0.4)")
    out.append("")

    if stats["failures"]:
        out.append(f"  ⚠️ 失败用例 {len(stats['failures'])} 条 (已跳过, 不影响其他用例):")
        for idx, r, why in stats["failures"]:
            out.append(f"    [{idx}] {r['id']} {r['question']} — {why}")
    else:
        out.append("  ✓ 全部用例完成，评审各维度均有效")
    out.append("")

    # 逐条明细
    out.append("  ── 逐条明细 " + "─" * 40)
    header = (f"  {_pad('id', 10)} {_pad('类别', 10)} {_pad('工具', 24)} "
              f"{_pad('用时s', 7)} {_pad('Faith', 6)} {_pad('Relev', 6)} {_pad('Recall', 6)} 备注")
    out.append(header)
    for r in results:
        rag = r.get("rag") or {}
        tools = "·".join(r["tools"]) or "无工具"
        note = "运行错误" if r["error"] else ""
        out.append(
            f"  {_pad(r['id'], 10)} {_pad(r.get('category', ''), 10)} {_pad(_clip(tools, 24), 24)} "
            f"{_pad(f'{_latency(r):.1f}', 7)} {_pad(_num(rag.get('faithfulness')), 6)} "
            f"{_pad(_num(rag.get('relevancy')), 6)} {_pad(_num(rag.get('recall')), 6)} {note}"
        )
    out.append("")

    # 分类别汇总
    categories = list(dict.fromkeys(r.get("category", "") for r in results))
    out.append("  ── 分类别 " + "─" * 42)
    out.append(f"  {_pad('类别', 12)} {_pad('条数', 5)} {_pad('工具命中', 9)} "
               f"{_pad('Faith', 6)} {_pad('Relev', 6)} {_pad('Recall', 6)} {_pad('平均延迟', 9)}")
    for cat in categories:
        items = [r for r in results if r.get("category", "") == cat]
        hits = [r for r in items if r["tool_hit"] is not None]
        hit_txt = f"{sum(1 for r in hits if r['tool_hit'])}/{len(hits)}" if hits else "—"
        dims = [_mean(_dim_values(items, d)) for d in RAG_DIMENSIONS]
        avg_lat = statistics.mean([_latency(r) for r in items]) if items else 0.0
        out.append(
            f"  {_pad(cat, 12)} {_pad(str(len(items)), 5)} {_pad(hit_txt, 9)} "
            f"{_pad(_num(dims[0]), 6)} {_pad(_num(dims[1]), 6)} {_pad(_num(dims[2]), 6)} "
            f"{avg_lat:.1f}s"
        )
    out.append("")

    out.extend([
        "  ── 口径说明 " + "─" * 40,
        "  · 工具选择准确率只看声明了 expect_tools 的用例；寒暄/无关/违规类不参与，单列误调用数。",
        "  · Faithfulness / Relevancy / Recall 为 DeepSeek 独立评审的 0~1 分（RAGAS 口径），",
        "    评审上下文是工具返回的原文节选，不只是标题。解析失败记 None 并列入失败用例。",
        "  · 综合评分 = 三维有效值均值；Agent 评分 = 0.6 × 综合评分 + 0.4 × 工具选择准确率。",
        "  · 延迟为端到端墙钟（含意图路由、检索、重排与流式生成），并发 2 时排队会略微抬高。",
        "  · 用例直接调用 run_agent_stream，不写 qa_record，不污染线上数据。",
        "",
        "  复现：uv run python evals/run_agent_report.py",
        bar,
    ])
    return "\n".join(out) + "\n"


# ── 入口 ────────────────────────────────────────────────────────────────


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="生成 Agent 综合评估报告（文本）")
    ap.add_argument("--dataset", type=Path, default=run_eval._DATASET, help="评估集 JSONL")
    ap.add_argument("--limit", type=int, help="只跑前 N 条（冒烟）")
    ap.add_argument("--concurrency", type=int, default=2, help="并发数（默认 2，防限流）")
    ap.add_argument("--no-judge", action="store_true", help="跳过 LLM 评审，只出自动指标")
    ap.add_argument("--judge-model", default="", help="评审模型（默认 judge.py 的 deepseek-flash）")
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="报告输出路径")
    ap.add_argument("--from-jsonl", type=Path, help="不重跑评测，用既有明细 JSONL 重新渲染报告")
    args = ap.parse_args()

    results: list[dict[str, Any]] = []
    if args.from_jsonl:
        results = [
            json.loads(ln)
            for ln in args.from_jsonl.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        print(f"复用明细 {args.from_jsonl}（{len(results)} 条），跳过评测与评审")
    else:
        cases = run_eval.load_dataset(args.dataset)
        if args.limit:
            cases = cases[: args.limit]
        print(f"评估用例 {len(cases)} 条（concurrency={args.concurrency}，"
              f"judge={'off' if args.no_judge else 'on'}）")

        _install_recorder()
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            for i, r in enumerate(pool.map(run_case_traced, cases), start=1):
                flag = "✗" if r["error"] else "✓"
                print(f"[{i}/{len(cases)}] {flag} {r['id']} 用时 {_latency(r):.1f}s "
                      f"工具 {'·'.join(r['tools']) or '无'}")
                results.append(r)

        if args.no_judge:
            for r in results:
                r["rag"] = {**{d: None for d in RAG_DIMENSIONS}, "comment": "", "error": ""}
        else:
            print("LLM 评审中（DeepSeek，RAGAS 三维）…")
            try:
                judge_all(results, args.judge_model, args.concurrency)
            except RuntimeError as e:
                print(f"跳过评审: {e}")
                for r in results:
                    r["rag"] = {**{d: None for d in RAG_DIMENSIONS}, "comment": "", "error": ""}

    stats = summarize(results)
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = render(results, stats, args.dataset, run_ts)
    args.out.write_text(text, encoding="utf-8")
    print("\n" + text)
    print(f"报告已写入：{args.out}")

    if not args.from_jsonl:
        # 明细留档（gitignore 目录），方便复盘单条用例；也支持 --from-jsonl 重渲染
        _REPORTS.mkdir(parents=True, exist_ok=True)
        detail = _REPORTS / f"agent_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        with detail.open("w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps({**r, "context": (r.get("context") or "")[:1000]},
                                   ensure_ascii=False) + "\n")
        print(f"明细已写入：{detail}")


if __name__ == "__main__":
    main()
