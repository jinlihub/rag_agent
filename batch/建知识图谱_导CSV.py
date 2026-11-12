"""生成知识图谱用数据副本，并把两个 xlsx 导出为 CSV。

读取 data/processed/招标采购标的物信息提取训练数据_2_标的物.xlsx，仅保留
「标的物」「采购人」「代理机构」「中标人」「中标金额」「市区」六列，重命名为
「标的物」「采购商」「代理机构」「供应商」「交易额」「所在地」后另存为
招标采购标的物信息提取训练数据_2_知识图谱.xlsx（已存在则覆盖）；再把该文件
与 标的物_交易频次.xlsx 各导出一份同名 CSV（默认 UTF-8 带 BOM，Excel 可直接
双击打开；如需 Excel「ANSI」效果可用 --encoding gbk）。

用法:
    uv run python batch/建知识图谱_导CSV.py
    uv run python batch/建知识图谱_导CSV.py --input 源.xlsx --output 知识图谱.xlsx
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INPUT = _ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据_2_标的物.xlsx"
_DEFAULT_OUTPUT = _ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据_2_知识图谱.xlsx"
_DEFAULT_FREQ = _ROOT / "data" / "processed" / "标的物_交易频次.xlsx"

# 源列 → 知识图谱列（保持此顺序）
_COLUMN_MAP = {
    "标的物": "标的物",
    "采购人": "采购商",
    "代理机构": "代理机构",
    "中标人": "供应商",
    "中标金额": "交易额",
    "市区": "所在地",
}


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


def _build_kg(header: list[Any], rows: list[list[Any]]) -> list[list[Any]]:
    """按 _COLUMN_MAP 顺序抽取六列，列名重命名为实体角色名。"""
    names = [str(h).strip() if h is not None else "" for h in header]
    missing = [src for src in _COLUMN_MAP if src not in names]
    if missing:
        raise SystemExit(
            f"输入表缺少列: {', '.join(missing)}，"
            f"现有列: {', '.join(n for n in names if n)}"
        )
    cols = [names.index(src) for src in _COLUMN_MAP]
    return [[row[c] for c in cols] for row in rows]


def _save_kg(path: Path, rows: list[list[Any]]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "知识图谱"
    ws.append(list(_COLUMN_MAP.values()))
    for row in rows:
        ws.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _export_csv(xlsx: Path, encoding: str) -> tuple[Path, int]:
    """xlsx 首个有数据的 sheet → 同名 CSV（None 写空串）。返回 (CSV 路径, 含表头行数)。"""
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    ws = next((s for s in wb.worksheets if s.max_row and s.max_row > 1), wb.active)
    csv_path = xlsx.with_suffix(".csv")
    n = 0
    with open(csv_path, "w", encoding=encoding, newline="") as f:
        w = csv.writer(f)
        for row in ws.iter_rows(values_only=True):
            w.writerow(["" if v is None else v for v in row])
            n += 1
    wb.close()
    return csv_path, n


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="生成知识图谱 xlsx 并导出 CSV")
    ap.add_argument("--input", type=Path, default=_DEFAULT_INPUT,
                    help="含六列源数据的 xlsx（默认 %(default)s）")
    ap.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT,
                    help="知识图谱 xlsx（默认 %(default)s）")
    ap.add_argument("--freq", type=Path, default=_DEFAULT_FREQ,
                    help="交易频次 xlsx，仅导出 CSV（默认 %(default)s）")
    ap.add_argument("--sheet", help="数据所在 sheet 名（默认取第一个有数据的 sheet）")
    ap.add_argument("--encoding", default="utf-8-sig",
                    help="CSV 编码（默认 %(default)s，Excel 可直接打开）")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"输入文件不存在: {args.input}")
    sheet_name, header, rows = _load_sheet(args.input, args.sheet)
    kg_rows = _build_kg(header, rows)
    note = "已覆盖" if args.output.exists() else "新建"
    _save_kg(args.output, kg_rows)
    print(f"知识图谱: {args.output}（{note}，六列 {len(kg_rows)} 行，sheet「知识图谱」）")

    csv_kg, n_kg = _export_csv(args.output, args.encoding)
    print(f"  导出 CSV: {csv_kg}（{n_kg} 行，编码 {args.encoding}）")

    if args.freq.exists():
        csv_freq, n_freq = _export_csv(args.freq, args.encoding)
        print(f"频次表 CSV: {csv_freq}（{n_freq} 行，编码 {args.encoding}）")
    else:
        print(f"频次表 CSV: 跳过，文件不存在: {args.freq}")


if __name__ == "__main__":
    main()
