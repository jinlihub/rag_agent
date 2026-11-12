"""把仓库根目录的两份 xlsx 导入 MySQL（可重复执行，先清空再全量导入）：

- 招标采购标的物信息提取训练数据.xlsx（Sheet2，8790 行×17 字段）→ bid_subjects
- 问题答案样例数据0113.xlsx（Sheet1，82 条问答对）→ faq_qa_pairs

用法: uv run python scripts/import_xlsx_to_mysql.py
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from rag_agent.database import get_conn

_ROOT = Path(__file__).resolve().parents[1]

_BID_XLSX = _ROOT / "招标采购标的物信息提取训练数据.xlsx"
_FAQ_XLSX = _ROOT / "问题答案样例数据0113.xlsx"

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS bid_subjects (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      title VARCHAR(512) NULL COMMENT '标题',
      category VARCHAR(64) NULL COMMENT '类别',
      source VARCHAR(64) NULL COMMENT '来源',
      publish_time DATETIME NULL COMMENT '发布时间',
      province VARCHAR(64) NULL COMMENT '省份',
      city VARCHAR(64) NULL COMMENT '市区',
      county VARCHAR(64) NULL COMMENT '县城',
      project_no VARCHAR(128) NULL COMMENT '项目编号',
      project_name VARCHAR(512) NULL COMMENT '项目名称',
      purchaser VARCHAR(256) NULL COMMENT '采购人',
      agency VARCHAR(256) NULL COMMENT '代理机构',
      budget DECIMAL(18,2) NULL COMMENT '预算(元)',
      project_address VARCHAR(512) NULL COMMENT '项目地址',
      duration VARCHAR(128) NULL COMMENT '周期',
      winner VARCHAR(256) NULL COMMENT '中标人',
      award_amount DECIMAL(18,2) NULL COMMENT '中标金额(元)',
      award_time DATETIME NULL COMMENT '中标时间',
      INDEX idx_province_city (province, city),
      INDEX idx_publish (publish_time),
      INDEX idx_award_time (award_time),
      INDEX idx_winner (winner)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='招标采购标的物全量记录(含中标结果)'
    """,
    """
    CREATE TABLE IF NOT EXISTS faq_qa_pairs (
      id BIGINT AUTO_INCREMENT PRIMARY KEY,
      question TEXT NOT NULL COMMENT '问',
      answer MEDIUMTEXT NOT NULL COMMENT '答'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='招投标实务高频问答对'
    """,
]


def _clean(v: Any) -> Any:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _num(v: Any) -> float | None:
    v = _clean(v)
    if v is None:
        return None
    try:
        return round(float(str(v).replace(",", "")), 2)
    except ValueError:
        return None


def _dt(v: Any) -> datetime.datetime | None:
    v = _clean(v)
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


def _rows_of(path: Path, sheet: str | None = None) -> list[tuple[Any, ...]]:
    """读取 xlsx 为元组列表（跳过表头，空串归一为 None）。"""
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header, data = rows[0], rows[1:]
    print(f"  读取 {path.name}: 表头={header}，数据 {len(data)} 行")
    return data


def import_bid_subjects() -> int:
    print(f"[1/2] 导入标的物数据 → bid_subjects")
    data = _rows_of(_BID_XLSX, sheet="Sheet2")
    records = [
        (
            _clean(title), _clean(category), _clean(source), _dt(publish),
            _clean(province), _clean(city), _clean(county), _clean(no),
            _clean(name), _clean(purchaser), _clean(agency), _num(budget),
            _clean(address), _clean(duration), _clean(winner), _num(amount), _dt(award),
        )
        for title, category, source, publish, province, city, county, no,
             name, purchaser, agency, budget, address, duration, winner, amount, award in data
    ]
    sql = """INSERT INTO bid_subjects
             (title, category, source, publish_time, province, city, county, project_no,
              project_name, purchaser, agency, budget, project_address, duration,
              winner, award_amount, award_time)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE bid_subjects")
        for i in range(0, len(records), 500):
            cur.executemany(sql, records[i : i + 500])
        conn.commit()
        cur.execute("SELECT COUNT(*) AS c, SUM(winner IS NOT NULL) AS awarded FROM bid_subjects")
        stat = cur.fetchone()
    print(f"  完成: 共 {stat['c']} 条，其中含中标结果 {stat['awarded']} 条")
    return stat["c"]


def import_faq() -> int:
    print(f"[2/2] 导入问答对 → faq_qa_pairs")
    data = _rows_of(_FAQ_XLSX)
    records = [(str(q).strip(), str(a).strip()) for q, a in data if _clean(q) and _clean(a)]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE faq_qa_pairs")
        cur.executemany("INSERT INTO faq_qa_pairs (question, answer) VALUES (%s, %s)", records)
        conn.commit()
        cur.execute("SELECT COUNT(*) AS c FROM faq_qa_pairs")
        count = cur.fetchone()["c"]
    print(f"  完成: 共 {count} 条")
    return count


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for ddl in _DDL:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(ddl)
            conn.commit()
    n1, n2 = import_bid_subjects(), import_faq()
    print(f"\n导入完成: bid_subjects={n1}, faq_qa_pairs={n2}")


if __name__ == "__main__":
    main()
