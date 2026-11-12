"""从批量接口结果 JSONL 提取「标的物」，按行序插入目标 xlsx 的「标的物」列。

结果行 custom_id 中的行序号（task-000001 → 第 1 条数据行）决定对齐位置，
与结果文件行序无关；缺失/失败请求对应的行留空并在报告中说明。
目标文件已存在则就地填充其中的「标的物」列；不存在则由源 xlsx
（默认 data/processed/招标采购标的物信息提取训练数据.xlsx）复制并追加该列后另存。

用法:
    uv run python batch/提数据_插标的物.py
    uv run python batch/提数据_插标的物.py --input 结果.jsonl --output 目标.xlsx
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INPUT = _ROOT / "data" / "batch" / "batch_results_processed.jsonl"
_DEFAULT_OUTPUT = _ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据_2_标的物.xlsx"
_DEFAULT_SOURCE = _ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据.xlsx"

_COLUMN = "标的物"
# 结果行被预处理成扁平结构时，依次尝试这些键
_FLAT_KEYS = (_COLUMN, "content", "output", "result")


def _extract_content(obj: dict[str, Any]) -> str | None:
    """标准批量结果行取 response.body.choices[0].message.content；扁平行取 _FLAT_KEYS。"""
    resp = obj.get("response")
    if isinstance(resp, dict):
        if resp.get("status_code") not in (None, 200):
            return None  # 请求失败（限流/报错等）
        body = resp.get("body")
        if isinstance(body, dict):
            choices = body.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                msg = choices[0].get("message") or {}
                content = msg.get("content")
                if content is not None and str(content).strip():
                    return str(content)
    for key in _FLAT_KEYS:
        v = obj.get(key)
        if v is not None and str(v).strip():
            return str(v)
    return None


def _parse_results(path: Path) -> tuple[dict[int, str], dict[str, int]]:
    """解析结果 JSONL → ({数据行序号: 标的物}, 统计)。行序号取自 custom_id 结尾数字。"""
    values: dict[int, str] = {}
    stat = {"结果行数": 0, "提取成功": 0, "失败或空": 0, "重复跳过": 0}
    for no, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError as e:
            raise SystemExit(f"第 {no} 行不是合法 JSON: {e}")
        if not isinstance(obj, dict):
            raise SystemExit(f"第 {no} 行不是 JSON 对象")
        stat["结果行数"] += 1
        cid = obj.get("custom_id")
        m = re.search(r"(\d+)$", cid) if isinstance(cid, str) else None
        if not m:
            raise SystemExit(f"第 {no} 行 custom_id 无法解析出行序号: {cid!r}")
        content = _extract_content(obj)
        if content is None:
            stat["失败或空"] += 1
            continue
        idx = int(m.group(1))
        if idx in values:
            stat["重复跳过"] += 1  # 同一行序号多次出现，保留首次结果
            continue
        values[idx] = content.strip()
        stat["提取成功"] += 1
    return values, stat


def _load_sheet(path: Path, sheet: str | None) -> tuple[str, list[Any], list[list[Any]]]:
    """读 xlsx → (sheet名, 表头, 数据行)。整行全空跳过；行长度对齐表头。"""
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


def _fill(
    header: list[Any], rows: list[list[Any]], values: dict[int, str]
) -> tuple[dict[str, int], bool]:
    """把 values 按行序写进「标的物」列（列已存在则就地填充，否则追加在末尾）。"""
    names = [str(h).strip() if h is not None else "" for h in header]
    appended = _COLUMN not in names
    col = names.index(_COLUMN) if not appended else len(header)
    if appended:
        header.append(_COLUMN)
    filled = blank = oob = 0
    for i, row in enumerate(rows, start=1):
        if len(row) < len(header):
            row += [None] * (len(header) - len(row))
        row[col] = values.get(i)
        if i in values:
            filled += 1
        else:
            blank += 1
    oob = sum(1 for idx in values if idx > len(rows))
    return {"数据行数": len(rows), "写入标的物": filled, "无结果留空": blank,
            "行号超出范围": oob}, appended


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="从批量结果 JSONL 提取标的物并插入 xlsx")
    ap.add_argument("--input", type=Path, default=_DEFAULT_INPUT,
                    help="批量结果 JSONL（默认 %(default)s）")
    ap.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT,
                    help="目标 xlsx（默认 %(default)s）")
    ap.add_argument("--source", type=Path, default=_DEFAULT_SOURCE,
                    help="目标不存在时复制源数据的 xlsx（默认 %(default)s）")
    ap.add_argument("--sheet", help="数据所在 sheet 名（默认取第一个有数据的 sheet）")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"输入文件不存在: {args.input}")
    values, stat = _parse_results(args.input)

    if args.output.exists():
        sheet_name, header, rows = _load_sheet(args.output, args.sheet)
        note = "已存在，就地填充「标的物」列"
    else:
        if not args.source.exists():
            raise SystemExit(f"目标文件不存在，且源文件也不存在: {args.source}")
        sheet_name, header, rows = _load_sheet(args.source, args.sheet)
        note = f"新建（复制自 {args.source.name}，末尾追加「{_COLUMN}」列）"
    fill_stat, appended = _fill(header, rows, values)

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(header)
    for row in rows:
        ws.append(row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.output)

    print(f"输入: {args.input}")
    for k, v in stat.items():
        print(f"  {k}: {v}")
    print(f"目标: {args.output}（{note}）")
    for k, v in fill_stat.items():
        print(f"  {k}: {v}")
    names = [str(h).strip() for h in header]
    j_name = names.index("项目名称") if "项目名称" in names else 0
    j_col = names.index(_COLUMN)
    for i, row in enumerate(rows[:3], start=1):
        print(f"  预览 第{i}行: {row[j_name]} → 标的物={row[j_col]}")


if __name__ == "__main__":
    main()
