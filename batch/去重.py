"""按「项目编号 + 中标金额」去重标的物训练数据。

同一（项目编号, 中标金额）组合出现多条时，保留整行空值（None/空白串）最少的一条，
并列时保留先出现的；两列键都为空的行无法认定是否重复，原样保留。
输出按原始行序写出，除剔除重复行外不改动任何单元格内容。

用法:
    uv run python batch/去重.py                    # 输入默认 data/raw/招标采购标的物信息提取训练数据_s.xlsx
    uv run python batch/去重.py --input <xlsx> [--output <xlsx>] [--sheet <名称>]

输出默认与输入同目录，文件名追加「_去重」。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INPUT = _ROOT / "data" / "raw" / "招标采购标的物信息提取训练数据_s.xlsx"

_KEY_COLS = ("项目编号", "中标金额")


def _is_null(v: Any) -> bool:
    """None、空串、纯空白串都计为空值。"""
    return v is None or (isinstance(v, str) and not v.strip())


def _norm_no(v: Any) -> str | None:
    """项目编号键：去首尾空白。"""
    return None if _is_null(v) else str(v).strip()


def _norm_amt(v: Any) -> float | str | None:
    """中标金额键：统一为数值，让 366500 / 366500.0 / '366,500.00' 视为同一键。"""
    if _is_null(v):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v).strip().replace(",", "")
    try:
        return round(float(s), 2)
    except ValueError:
        return s


def _load(
    path: Path, sheet: str | None
) -> tuple[str, list[Any], list[tuple[Any, ...]], int]:
    """读 xlsx：返回 (sheet名, 原始表头, 数据行, 跳过的空行数)。

    sheet 缺省时取第一个有数据的 sheet；整行全空的行跳过；短行补 None 对齐表头。
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    if sheet:
        if sheet not in wb.sheetnames:
            raise SystemExit(f"找不到 sheet「{sheet}」，现有: {', '.join(wb.sheetnames)}")
        ws = wb[sheet]
    else:
        ws = next((s for s in wb.worksheets if s.max_row and s.max_row > 1), wb.active)
    all_rows = list(ws.iter_rows(values_only=True))
    name = ws.title
    wb.close()
    if not all_rows:
        raise SystemExit(f"sheet「{name}」没有内容")
    header = list(all_rows[0])
    missing = [c for c in _KEY_COLS if c not in {str(h).strip() for h in header}]
    if missing:
        raise SystemExit(f"表头缺少关键列: {'、'.join(missing)}（实际表头: {header}）")
    width = len(header)
    rows: list[tuple[Any, ...]] = []
    skipped = 0
    for r in all_rows[1:]:
        if all(_is_null(v) for v in r):
            skipped += 1
            continue
        rows.append(tuple(r) + (None,) * (width - len(r)) if len(r) < width else tuple(r[:width]))
    return name, header, rows, skipped


def dedup(
    rows: list[tuple[Any, ...]], i_no: int, i_amt: int
) -> tuple[list[tuple[Any, ...]], dict[str, int]]:
    """组内保留空值最少的行（并列取先出现的），返回 (保留的行, 统计)。"""
    groups: dict[tuple[Any, Any], list[int]] = {}
    null_key = 0
    for idx, r in enumerate(rows):
        key = (_norm_no(r[i_no]), _norm_amt(r[i_amt]))
        if key == (None, None):
            null_key += 1  # 键全空，无法认定重复，原样保留
            continue
        groups.setdefault(key, []).append(idx)

    keep = [True] * len(rows)
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        best = min(idxs, key=lambda i: sum(_is_null(v) for v in rows[i]))
        for i in idxs:
            if i != best:
                keep[i] = False
    kept = [r for i, r in enumerate(rows) if keep[i]]
    stat = {
        "输入行数": len(rows),
        "重复组": sum(1 for v in groups.values() if len(v) > 1),
        "剔除行数": len(rows) - len(kept),
        "键全空原样保留": null_key,
        "保留行数": len(kept),
    }
    return kept, stat


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="按「项目编号+中标金额」去重，保留空值最少的一条")
    ap.add_argument("--input", type=Path, default=_DEFAULT_INPUT,
                    help="输入 xlsx（默认 %(default)s）")
    ap.add_argument("--output", type=Path,
                    help="输出 xlsx（默认与输入同目录，文件名追加 _去重）")
    ap.add_argument("--sheet", help="数据所在 sheet 名（默认取第一个有数据的 sheet）")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"输入文件不存在: {args.input}")
    output = args.output or args.input.with_name(f"{args.input.stem}_去重.xlsx")

    sheet_name, header, rows, skipped = _load(args.input, args.sheet)
    idx = {str(h).strip(): i for i, h in enumerate(header)}
    kept, stat = dedup(rows, idx["项目编号"], idx["中标金额"])

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(header)
    for r in kept:
        ws.append(list(r))
    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)

    print(f"输入: {args.input}（sheet「{sheet_name}」）")
    if skipped:
        print(f"  跳过空行: {skipped}")
    for k, v in stat.items():
        print(f"  {k}: {v}")
    print(f"输出: {output}")


if __name__ == "__main__":
    main()
