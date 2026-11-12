"""统计「标的物」列中每个标的物出现的频次（交易频次），写入目标 xlsx。

从输入 xlsx（默认 data/processed/招标采购标的物信息提取训练数据_2_标的物.xlsx）
读取「标的物」列，统计每个标的物出现的次数（交易频次），按频次降序
（同频次按名称升序）写入目标 xlsx（默认 data/processed/标的物_交易频次.xlsx）
的「标的物」「交易频次」两列。目标已存在则就地填充「交易频次」列：按
「标的物」匹配重填，输入中已不存在的旧条目原样保留，新增标的物追加表尾。

用法:
    uv run python batch/统计数据_插交易频次.py
    uv run python batch/统计数据_插交易频次.py --input 源.xlsx --output 目标.xlsx
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INPUT = _ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据_2_标的物.xlsx"
_DEFAULT_OUTPUT = _ROOT / "data" / "processed" / "标的物_交易频次.xlsx"

_COLUMN = "标的物"
_FREQ = "交易频次"


def _load_sheet(path: Path, sheet: str | None) -> tuple[str, list[Any], list[list[Any]]]:
    """读 xlsx → (sheet名, 表头, 数据行)。整行全空跳过；行长度对齐表头。"""
    wb = load_workbook(path, read_only=True, data_only=True)
    if sheet:
        if sheet not in wb.sheetnames:
            wb.close()
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
    width = len(header)
    rows = []
    for r in all_rows[1:]:
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in r):
            continue
        row = list(r)
        if len(row) < width:
            row += [None] * (width - len(row))
        rows.append(row[:width])
    return name, header, rows


def _count(header: list[Any], rows: list[list[Any]]) -> Counter[str]:
    """统计「标的物」列各非空值的出现次数（首尾去空白）。"""
    names = [str(h).strip() if h is not None else "" for h in header]
    if _COLUMN not in names:
        raise SystemExit(f"输入表没有「{_COLUMN}」列，现有列: {', '.join(n for n in names if n)}")
    col = names.index(_COLUMN)
    counter: Counter[str] = Counter()
    for row in rows:
        v = row[col]
        s = str(v).strip() if v is not None else ""
        if s:
            counter[s] += 1
    if not counter:
        raise SystemExit(
            f"「{_COLUMN}」列没有非空值，无法统计。"
            "若批量提取尚未完成，请先运行 batch/提数据_插标的物.py"
        )
    return counter


def _write_new(path: Path, sheet: str | None, items: list[tuple[str, int]]) -> dict[str, int]:
    """新建仅含「标的物」「交易频次」两列的频次表。"""
    wb = Workbook()
    ws = wb.active
    ws.title = (sheet or "标的物交易频次")[:31]
    ws.append([_COLUMN, _FREQ])
    for name, n in items:
        ws.append([name, n])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return {"写入条目": len(items)}


def _fill_existing(
    path: Path, sheet: str | None, items: list[tuple[str, int]]
) -> dict[str, int]:
    """目标已存在：按「标的物」匹配就地填充「交易频次」列，新增标的物追加表尾。"""
    wb = load_workbook(path, data_only=True)
    if sheet and sheet in wb.sheetnames:
        ws = wb[sheet]
    else:
        ws = wb.active
    header = [c.value for c in ws[1]]
    names = [str(h).strip() if h is not None else "" for h in header]
    if _COLUMN not in names:
        wb.close()
        raise SystemExit(f"目标表已有内容但没有「{_COLUMN}」列，现有列: {', '.join(n for n in names if n)}")
    name_col = names.index(_COLUMN) + 1
    if _FREQ in names:
        freq_col = names.index(_FREQ) + 1
        note = "就地重填"
    else:
        freq_col = len(names) + 1
        ws.cell(row=1, column=freq_col, value=_FREQ)
        note = f"末尾追加「{_FREQ}」列"
    freq = dict(items)
    filled = kept = appended = 0
    seen: set[str] = set()
    for r in range(2, ws.max_row + 1):
        v = ws.cell(row=r, column=name_col).value
        s = str(v).strip() if v is not None else ""
        if not s:
            continue
        if s in freq:
            ws.cell(row=r, column=freq_col, value=freq[s])
            seen.add(s)
            filled += 1
        else:
            kept += 1  # 输入中已不存在的旧条目，保留原频次值
    r = ws.max_row + 1
    for name, n in items:
        if name in seen:
            continue
        ws.cell(row=r, column=name_col, value=name)
        ws.cell(row=r, column=freq_col, value=n)
        r += 1
        appended += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    wb.close()
    return {"填充方式": note, "匹配填充": filled, "旧行保留": kept, "新增追加": appended}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="统计标的物交易频次并写入 xlsx")
    ap.add_argument("--input", type=Path, default=_DEFAULT_INPUT,
                    help="含「标的物」列的源 xlsx（默认 %(default)s）")
    ap.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT,
                    help="频次结果 xlsx（默认 %(default)s）")
    ap.add_argument("--sheet", help="数据所在 sheet 名（默认取第一个有数据的 sheet）")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"输入文件不存在: {args.input}")
    sheet_name, header, rows = _load_sheet(args.input, args.sheet)
    freq = _count(header, rows)
    items = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))

    if args.output.exists():
        stat = _fill_existing(args.output, args.sheet, items)
        note = "已存在，就地填充"
    else:
        stat = _write_new(args.output, args.sheet, items)
        note = "新建"

    print(f"输入: {args.input}（sheet「{sheet_name}」，数据行 {len(rows)}）")
    print(f"  非空标的物: {sum(freq.values())} 行，去重后 {len(freq)} 种")
    print(f"输出: {args.output}（{note}）")
    for k, v in stat.items():
        print(f"  {k}: {v}")
    print("  频次 Top5:")
    for name, n in items[:5]:
        print(f"    {name}: {n}")


if __name__ == "__main__":
    main()
