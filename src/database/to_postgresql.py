"""把标的物 xlsx 数据注入 PostgreSQL（可重复执行，先清空再全量导入）。

选择 data/processed/招标采购标的物信息提取训练数据_2_标的物.xlsx
（原 17 列 + 「标的物」列，后者暂缺时存 NULL），写入 POSTGRES_HOST
（默认 localhost）上的 bid_subjects 表：建表（如缺）→ 清空 → 分批插入 → 回读计数核对。

连接参数读环境变量（可写入 .env，均有默认值）:
    POSTGRES_HOST / POSTGRES_PORT / POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB

用法:
    uv run python src/database/to_postgresql.py                 # 全量注入
    uv run python src/database/to_postgresql.py --dry-run       # 只解析 xlsx 不连库
    uv run python src/database/to_postgresql.py --input 其他.xlsx --table 其他表
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from openpyxl import load_workbook

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_INPUT = _ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据_2_标的物.xlsx"

_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # 表名白名单，防注入 DDL

_SUBJECT_HEADER = "标的物"
_INDEXES = (
    ("idx_province_city", "(province, city)"),
    ("idx_publish", "(publish_time)"),
    ("idx_award_time", "(award_time)"),
    ("idx_winner", "(winner)"),
)


def _stripped(v: Any) -> Any:
    """字符串去首尾空白，空串归一为 None；其余类型原样。"""
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _num(v: Any) -> float | None:
    v = _stripped(v)
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _dt(v: Any) -> datetime.datetime | None:
    v = _stripped(v)
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v
    if isinstance(v, datetime.date):
        return datetime.datetime.combine(v, datetime.time())
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(str(v), fmt)
        except ValueError:
            continue
    return None


# xlsx 表头 → (PG 列名, 类型, 清洗函数)；「标的物」为可选列
_COLUMNS: list[tuple[str, str, str, Callable[[Any], Any]]] = [
    ("标题", "title", "VARCHAR(512)", _stripped),
    ("类别", "category", "VARCHAR(64)", _stripped),
    ("来源", "source", "VARCHAR(64)", _stripped),
    ("发布时间", "publish_time", "TIMESTAMP", _dt),
    ("省份", "province", "VARCHAR(64)", _stripped),
    ("市区", "city", "VARCHAR(64)", _stripped),
    ("县城", "county", "VARCHAR(64)", _stripped),
    ("项目编号", "project_no", "VARCHAR(128)", _stripped),
    ("项目名称", "project_name", "VARCHAR(512)", _stripped),
    ("采购人", "purchaser", "VARCHAR(256)", _stripped),
    ("代理机构", "agency", "VARCHAR(256)", _stripped),
    ("预算", "budget", "NUMERIC(18,2)", _num),
    ("项目地址", "project_address", "VARCHAR(512)", _stripped),
    ("周期", "duration", "VARCHAR(128)", _stripped),
    ("中标人", "winner", "VARCHAR(256)", _stripped),
    ("中标金额", "award_amount", "NUMERIC(18,2)", _num),
    ("中标时间", "award_time", "TIMESTAMP", _dt),
    ("标的物", "subject", "VARCHAR(512)", _stripped),
]


def _load_rows(
    path: Path, sheet: str | None
) -> tuple[list[tuple[Any, ...]], bool, list[str]]:
    """读 xlsx 并按 _COLUMNS 变换 → (数据行, 是否含标的物列, 未识别的表头)。"""
    wb = load_workbook(path, read_only=True, data_only=True)
    if sheet:
        if sheet not in wb.sheetnames:
            raise SystemExit(f"找不到 sheet「{sheet}」，现有: {', '.join(wb.sheetnames)}")
        ws = wb[sheet]
    else:
        ws = next((s for s in wb.worksheets if s.max_row and s.max_row > 1), wb.active)
    all_rows = list(ws.iter_rows(values_only=True))
    title = ws.title
    wb.close()
    if not all_rows:
        raise SystemExit(f"sheet「{title}」没有内容")

    header = [str(h).strip() if h is not None else "" for h in all_rows[0]]
    known = {zh for zh, *_rest in _COLUMNS}
    missing = [zh for zh, *_rest in _COLUMNS if zh != _SUBJECT_HEADER and zh not in header]
    if missing:
        raise SystemExit(f"表头缺少必需列: {'、'.join(missing)}（实际表头: {header}）")
    has_subject = _SUBJECT_HEADER in header
    unknown = [h for h in header if h and h not in known]

    idx_of = {zh: header.index(zh) for zh in known if zh in header}
    rows: list[tuple[Any, ...]] = []
    for r in all_rows[1:]:
        if all(_stripped(v) is None for v in r):
            continue
        rows.append(
            tuple(
                _COLUMNS[j][3](r[idx_of[zh]]) if zh in idx_of else None
                for j, (zh, *_rest) in enumerate(_COLUMNS)
            )
        )
    return rows, has_subject, unknown


def _connect():
    import psycopg2

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    dbname = os.getenv("POSTGRES_DB", "postgres")
    try:
        return psycopg2.connect(host=host, port=port, user=user, password=password,
                                dbname=dbname, connect_timeout=5)
    except Exception as e:  # noqa: BLE001 —— 连接失败给出可操作的提示
        raise SystemExit(
            f"连接 PostgreSQL 失败（{host}:{port}, db={dbname}, user={user}）: {e}\n"
            "提示: 确认服务已启动，并在 .env 配置 POSTGRES_HOST/PORT/USER/PASSWORD/DB"
        )


def _ensure_table(cur, table: str) -> None:
    cols = ",\n      ".join(f"{name} {typ}" for _zh, name, typ, _fn in _COLUMNS)
    cur.execute(
        f"CREATE TABLE IF NOT EXISTS {table} (\n      id BIGSERIAL PRIMARY KEY,\n      {cols}\n    )"
    )
    for _zh, name, _typ, _fn in _COLUMNS:
        cur.execute(f"COMMENT ON COLUMN {table}.{name} IS %s", (_zh,))
    for idx_name, idx_cols in _INDEXES:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} {idx_cols}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(_ROOT / ".env")
    ap = argparse.ArgumentParser(description="选择 xlsx 并注入 PostgreSQL")
    ap.add_argument("--input", type=Path, default=_DEFAULT_INPUT,
                    help="输入 xlsx（默认 %(default)s）")
    ap.add_argument("--table", default="bid_subjects",
                    help="目标表名（默认 %(default)s）")
    ap.add_argument("--sheet", help="数据所在 sheet 名（默认取第一个有数据的 sheet）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只解析 xlsx 并统计，不连接数据库")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"输入文件不存在: {args.input}")
    if not _TABLE_RE.match(args.table):
        raise SystemExit(f"表名不合法（只允许字母/数字/下划线）: {args.table}")

    rows, has_subject, unknown = _load_rows(args.input, args.sheet)
    n_subject = sum(1 for r in rows if r[-1] is not None)
    print(f"输入: {args.input}")
    print(f"  数据行数: {len(rows)}，标的物非空: {n_subject}"
          + ("" if has_subject else "（源表暂无「标的物」列，该列将为空）"))
    if unknown:
        print(f"  未识别列（跳过）: {'、'.join(unknown)}")
    if args.dry_run:
        print("--dry-run 完成，未连接数据库")
        return

    from psycopg2.extras import execute_values

    conn = _connect()
    try:
        with conn:  # 事务：成功提交，异常回滚
            with conn.cursor() as cur:
                _ensure_table(cur, args.table)
                cur.execute(f"TRUNCATE TABLE {args.table} RESTART IDENTITY")
                cols_sql = ", ".join(name for _zh, name, _typ, _fn in _COLUMNS)
                sql = f"INSERT INTO {args.table} ({cols_sql}) VALUES %s"
                for i in range(0, len(rows), 500):
                    execute_values(cur, sql, rows[i:i + 500], page_size=500)
                cur.execute(f"SELECT COUNT(*) AS total, COUNT(subject) AS subj FROM {args.table}")
                total, subj = cur.fetchone()
    finally:
        conn.close()
    print(f"注入完成: 表 {args.table} 共 {total} 行，其中标的物非空 {subj} 行")


if __name__ == "__main__":
    main()
