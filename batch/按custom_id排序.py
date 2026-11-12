"""按「custom_id」对批量接口 JSONL 排序，确保递增。

批量接口返回的结果文件行序不保证与请求一致，本工具按 custom_id 排回递增序，
便于后续按序号回填 xlsx（序号即数据行序）。排序采用自然序：数字段按数值比较，
task-10 会正确排在 task-9 之后；行内容原样保留，不重新序列化。

用法:
    uv run python batch/按custom_id排序.py                        # 默认输入 data/raw/核心标的物提取_batch.jsonl
    uv run python batch/按custom_id排序.py --input 结果.jsonl     # 排序批量结果文件
    uv run python batch/按custom_id排序.py --input a.jsonl --output a.jsonl   # 原地覆盖
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INPUT = _ROOT / "data" / "raw" / "核心标的物提取_batch.jsonl"


def _nat_key(cid: str) -> tuple[tuple[int, int, str], ...]:
    """自然序键：数字段按数值比较，避免 task-10 排到 task-9 之前。"""
    return tuple(
        (1, int(p), "") if p.isdigit() else (0, 0, p)
        for p in re.split(r"(\d+)", cid)
    )


def _read(path: Path) -> list[str]:
    """读入非空行并逐行校验 JSON 与 custom_id（字符串），出错报行号。"""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for no, ln in enumerate(lines, start=1):
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError as e:
            raise SystemExit(f"第 {no} 行不是合法 JSON: {e}")
        if not isinstance(obj, dict) or not isinstance(obj.get("custom_id"), str):
            raise SystemExit(f"第 {no} 行缺少字符串类型的 custom_id: {ln[:120]}…")
    return lines


def _ids(lines: list[str]) -> list[str]:
    return [json.loads(ln)["custom_id"] for ln in lines]


def _keys(ids: list[str]) -> list[tuple[tuple[int, int, str], ...]]:
    return [_nat_key(c) for c in ids]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="按 custom_id 排序 JSONL，确保递增")
    ap.add_argument("--input", type=Path, default=_DEFAULT_INPUT,
                    help="输入 JSONL（默认 %(default)s）")
    ap.add_argument("--output", type=Path,
                    help="输出 JSONL（默认与输入同目录，文件名追加 _排序）")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"输入文件不存在: {args.input}")
    output = args.output or args.input.with_name(f"{args.input.stem}_排序.jsonl")

    lines = _read(args.input)
    if not lines:
        raise SystemExit(f"输入文件为空: {args.input}")
    ids = _ids(lines)
    dup = len(ids) - len(set(ids))
    keys = _keys(ids)
    already = all(keys[i] < keys[i + 1] for i in range(len(keys) - 1))

    lines.sort(key=lambda ln: _nat_key(json.loads(ln)["custom_id"]))  # 稳定排序，重复 id 保持原相对顺序
    with open(output, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    # 回读输出复核（与排序同用自然序比较）：非降序成立；无重复时即严格递增
    out_ids = _ids(_read(output))
    after = _keys(out_ids)
    ordered = all(after[i] <= after[i + 1] for i in range(len(after) - 1))
    if not ordered:  # 理论不可达，防御排序实现回归
        raise SystemExit("排序后仍存在乱序，请检查 _nat_key")

    print(f"输入: {args.input}")
    print(f"  行数: {len(lines)}（重复 custom_id: {dup} 个）")
    print(f"  排序前: {'已递增，无需调整' if already else '乱序 → 已按 custom_id 排序'}")
    print(f"  custom_id 范围: {out_ids[0]} ~ {out_ids[-1]}")
    if dup:
        seen: set[str] = set()
        dups: list[str] = []
        for c in out_ids:
            if c in seen and c not in dups:
                dups.append(c)
            seen.add(c)
        print(f"  注意: 存在重复 custom_id {dups[:5]}{'…' if len(dups) > 5 else ''}，已保留全部行")
    print(f"输出: {output}（复核: {'严格递增 ✓' if dup == 0 else '非降序 ✓（含重复）'})")


if __name__ == "__main__":
    main()
