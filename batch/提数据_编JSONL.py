"""提取标的物训练数据的所有「项目名称」，生成批量接口（Batch API）请求 JSONL。

每行一个 chat/completions 请求，采用智谱批量接口格式（官方文档示例）：
    {"custom_id": "request-1", "method": "POST", "url": "/v4/chat/completions",
     "body": {"model": "...", "messages": [...]}}
「项目名称」嵌入用户提问模板；custom_id 按 task-000001 起递增编号，
序号即数据行序（xlsx 数据行号 = 序号 + 1），批量结果可按 custom_id 回填。

用法:
    uv run python batch/提数据_编JSONL.py              # 全量生成
    uv run python batch/提数据_编JSONL.py --limit 5    # 先小批量试跑，验证格式
    uv run python batch/提数据_编JSONL.py --unique     # 相同项目名称只保留首行
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INPUT = _ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据.xlsx"
_DEFAULT_OUTPUT = _ROOT / "data" / "raw" / "核心标的物提取_batch.jsonl"

# 用户提问模板：项目名称嵌入 {name} 处（只输出字段值本身）
_PROMPT = ("请从以下项目名称中，提取一个字段：核心标的物"
           "（只输出具体的商品或服务名称，不要包含公司名）。项目名称：{name}")


def _load_names(path: Path, sheet: str | None) -> list[str]:
    """按行序读出「项目名称」列的非空值。"""
    wb = load_workbook(path, read_only=True, data_only=True)
    if sheet:
        if sheet not in wb.sheetnames:
            raise SystemExit(f"找不到 sheet「{sheet}」，现有: {', '.join(wb.sheetnames)}")
        ws = wb[sheet]
    else:
        ws = next((s for s in wb.worksheets if s.max_row and s.max_row > 1), wb.active)
    rows = list(ws.iter_rows(values_only=True))
    title = ws.title
    wb.close()
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    if "项目名称" not in header:
        raise SystemExit(f"表头缺少「项目名称」列（实际表头: {header}）")
    col = header.index("项目名称")
    names = [r[col] for r in rows[1:] if r[col] is not None and str(r[col]).strip()]
    print(f"读取 {path.name}（sheet「{title}」）：项目名称 {len(names)} 条")
    return names


def build_request(custom_id: str, name: str, args: argparse.Namespace) -> dict[str, Any]:
    """组装一行批量请求。thinking 关闭：字段抽取无需推理，直接给答案。"""
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": args.url,
        "body": {
            "model": args.model,
            "messages": [{"role": "user", "content": _PROMPT.format(name=name)}],
            "temperature": args.temperature,
            "thinking": {"type": "disabled"},
        },
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="提取项目名称并编写批量请求 JSONL")
    ap.add_argument("--input", type=Path, default=_DEFAULT_INPUT,
                    help="输入 xlsx（默认 %(default)s）")
    ap.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT,
                    help="输出 JSONL（默认 %(default)s）")
    ap.add_argument("--model", default="glm-4.5-air",
                    help="批量请求用的模型（默认 %(default)s，轻量抽取够用）")
    ap.add_argument("--url", default="/v4/chat/completions",
                    help="批量请求的 url 路径（默认 %(default)s）")
    ap.add_argument("--temperature", type=float, default=0.1,
                    help="采样温度（默认 %(default)s）")
    ap.add_argument("--sheet", help="数据所在 sheet 名（默认取第一个有数据的 sheet）")
    ap.add_argument("--limit", type=int, help="只生成前 N 条（小批量试跑用）")
    ap.add_argument("--unique", action="store_true", help="相同项目名称只保留首次出现")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"输入文件不存在: {args.input}")

    names = _load_names(args.input, args.sheet)
    seen: set[str] = set()
    uniq_skipped = 0
    total = len(names)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        for name in names:
            if args.unique:
                key = str(name).strip()
                if key in seen:
                    uniq_skipped += 1
                    continue
                seen.add(key)
            n += 1
            f.write(json.dumps(build_request(f"task-{n:06d}", str(name).strip(), args),
                               ensure_ascii=False) + "\n")
            if args.limit and n >= args.limit:
                break

    size_kb = args.output.stat().st_size / 1024
    print(f"输入项目名称: {total} 条" + (f"（相同名称跳过 {uniq_skipped} 条）" if args.unique else ""))
    print(f"输出请求数: {n} 条，custom_id: task-000001 ~ task-{n:06d} 递增")
    print(f"输出: {args.output}（{size_kb:.0f} KB）")
    with open(args.output, encoding="utf-8") as f:
        first = json.loads(f.readline())
    print("首行预览:", json.dumps(first, ensure_ascii=False)[:200], "…")


if __name__ == "__main__":
    main()
