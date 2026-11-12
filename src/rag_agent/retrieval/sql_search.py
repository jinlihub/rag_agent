"""结构化数据的参数化查询（招标 / 企业）。全部走占位符传参，防注入。"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from rag_agent.database import get_conn

_DATE_FALLBACK_SPAN = 180  # 请求范围完全超出覆盖时，改查覆盖内最近的天数


def _like(keyword: str) -> str:
    """转义 LIKE 通配符后包上 %%。"""
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _to_date(s: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        return None


def clamp_date_range(
    cur: DictCursor,
    table: str,
    col: str,
    date_from: str | None,
    date_to: str | None,
) -> tuple[str | None, str | None, str | None]:
    """把请求时间范围对齐到表内实际数据覆盖，杜绝模型拿错范围空查。

    与覆盖有交集时原样返回（交集外本就查不到东西）；完全无交集时改查覆盖内
    最近的等长时段，并返回给模型的说明（note），让回答能向用户解释。
    """
    if not (date_from or date_to):
        return date_from, date_to, None
    cur.execute(f"SELECT MIN({col}) AS lo, MAX({col}) AS hi FROM {table}")  # noqa: S608 —— table/col 为白名单常量
    row = cur.fetchone()
    lo_d, hi_d = _to_date(str(row["lo"])), _to_date(str(row["hi"]))
    if lo_d is None or hi_d is None:
        return date_from, date_to, None
    req_from, req_to = _to_date(date_from) if date_from else None, _to_date(date_to) if date_to else None

    has_from_before_hi = req_from is None or req_from <= hi_d
    has_to_after_lo = req_to is None or req_to >= lo_d
    if has_from_before_hi and has_to_after_lo:
        return date_from, date_to, None  # 有交集，无需处理

    # 完全超出覆盖：按请求的等长时段贴齐最近的边界
    if req_from is not None and req_to is not None:
        span = (req_to - req_from).days
    else:
        span = _DATE_FALLBACK_SPAN
    span = max(span, 1)
    coverage = f"{lo_d.isoformat()} ~ {hi_d.isoformat()}"
    if req_from is not None and req_from > hi_d:
        new_to, new_from = hi_d, max(lo_d, hi_d - datetime.timedelta(days=span))
        reason = "请求的时间比现有数据更新"
    else:
        new_from, new_to = lo_d, min(hi_d, lo_d + datetime.timedelta(days=span))
        reason = "请求的时间早于现有数据"
    note = f"请求时间范围超出数据覆盖（{coverage}，{reason}），已自动改查 {new_from.isoformat()} ~ {new_to.isoformat()}"
    return new_from.isoformat(), new_to.isoformat(), note


def _sanitize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """date/datetime/Decimal → JSON 可序列化类型。"""
    out = []
    for row in rows:
        clean = {}
        for k, v in row.items():
            if isinstance(v, (datetime.datetime, datetime.date)):
                clean[k] = str(v)
            elif isinstance(v, Decimal):
                clean[k] = float(v)
            else:
                clean[k] = v
        out.append(clean)
    return out


def _build_where(where: list[str], params: list[Any]) -> str:
    return (" WHERE " + " AND ".join(where)) if where else ""


# ── 标的物全量记录（bid_subjects，导入自训练数据 xlsx，含中标结果）───────────


def search_bid_subjects(
    keyword: str | None = None,
    province: str | None = None,
    city: str | None = None,
    category: str | None = None,
    only_awarded: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    order: str = "time",
    limit: int = 8,
) -> dict[str, Any]:
    """检索招标采购标的物记录（含中标人/中标金额）。"""
    where: list[str] = []
    params: list[Any] = []
    if keyword:
        like = _like(keyword)
        where.append(
            "(title LIKE %s OR project_name LIKE %s OR purchaser LIKE %s OR winner LIKE %s)"
        )
        params += [like, like, like, like]
    if province:
        where.append("province LIKE %s")
        params.append(f"%{province}%")
    if city:
        where.append("city LIKE %s")
        params.append(f"%{city}%")
    if category:
        where.append("category = %s")
        params.append(category)
    if only_awarded:
        where.append("winner IS NOT NULL")
    date_col = "award_time" if only_awarded else "publish_time"
    clamp_note: str | None = None

    with get_conn() as conn, conn.cursor() as cur:
        if date_from or date_to:
            date_from, date_to, clamp_note = clamp_date_range(
                cur, "bid_subjects", date_col, date_from, date_to
            )
        if date_from:
            where.append(f"{date_col} >= %s")
            params.append(date_from)
        if date_to:
            where.append(f"{date_col} <= %s")
            params.append(f"{date_to} 23:59:59")
        clause = _build_where(where, params)
        order_sql = "award_amount DESC" if order == "amount" else f"{date_col} DESC"
        limit = max(1, min(int(limit or 8), 10))

        cur.execute(f"SELECT COUNT(*) AS c FROM bid_subjects{clause}", params)
        total = cur.fetchone()["c"]
        cur.execute(
            f"""SELECT title, category, province, city, county, project_no, project_name,
                       purchaser, agency, budget, winner, award_amount, award_time, publish_time
                FROM bid_subjects{clause} ORDER BY {order_sql} LIMIT {limit}""",
            params,
        )
        rows = _sanitize(list(cur.fetchall()))

    for r in rows:
        if r.get("award_amount") is not None:
            r["award_amount_wan"] = round(r["award_amount"] / 10000, 2)  # 元 → 万元
    result = {"total": total, "rows": rows}
    if clamp_note:
        result["note"] = clamp_note
    return result


# ── 招标项目记录（bid_招标项目记录，招标公告/项目层，无中标信息）────────────


def search_tender_projects(
    keyword: str | None = None,
    province: str | None = None,
    city: str | None = None,
    district: str | None = None,
    category: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """检索招标项目/公告记录（项目名、发布时间、地域、类别）。"""
    where: list[str] = []
    params: list[Any] = []
    if keyword:
        where.append("project_name LIKE %s")
        params.append(_like(keyword))
    if province:
        where.append("province LIKE %s")
        params.append(f"%{province}%")
    if city:
        where.append("city LIKE %s")
        params.append(f"%{city}%")
    if district:
        where.append("district LIKE %s")
        params.append(f"%{district}%")
    if category:
        where.append("category = %s")
        params.append(category)
    clamp_note: str | None = None

    with get_conn() as conn, conn.cursor() as cur:
        if date_from or date_to:
            date_from, date_to, clamp_note = clamp_date_range(
                cur, "`bid_招标项目记录`", "publish_date", date_from, date_to
            )
        if date_from:
            where.append("publish_date >= %s")
            params.append(date_from)
        if date_to:
            where.append("publish_date <= %s")
            params.append(date_to)
        clause = _build_where(where, params)
        limit = max(1, min(int(limit or 8), 10))

        cur.execute(f"SELECT COUNT(*) AS c FROM `bid_招标项目记录`{clause}", params)
        total = cur.fetchone()["c"]
        cur.execute(
            f"""SELECT project_name, publish_date, category, source, province, city, district
                 FROM `bid_招标项目记录`{clause} ORDER BY publish_date DESC LIMIT {limit}""",
            params,
        )
        rows = _sanitize(list(cur.fetchall()))
    result = {"total": total, "rows": rows}
    if clamp_note:
        result["note"] = clamp_note
    return result


# ── 企业 ────────────────────────────────────────────────────────────────────


def search_enterprises(
    keyword: str | None = None,
    business_status: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """按名称关键词检索企业基本信息。"""
    where: list[str] = []
    params: list[Any] = []
    if keyword:
        where.append("company_name LIKE %s")
        params.append(_like(keyword))
    if business_status:
        where.append("business_status = %s")
        params.append(business_status)
    clause = _build_where(where, params)
    limit = max(1, min(int(limit or 8), 10))

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM enterprise_企业信息{clause}", params)
        total = cur.fetchone()["c"]
        cur.execute(
            f"""SELECT company_name, legal_person, credit_rating, registered_capital,
                       establish_date, business_status
                 FROM enterprise_企业信息{clause} ORDER BY id LIMIT {limit}""",
            params,
        )
        rows = _sanitize(list(cur.fetchall()))
    return {"total": total, "rows": rows}


def search_company_violations(keyword: str, limit: int = 5) -> dict[str, Any]:
    """按企业名称检索违法违规记录。"""
    limit = max(1, min(int(limit or 5), 10))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT company_name, credit_code, penalty_date, publish_deadline, law_enforcement_unit
                 FROM enterprise_违法违规记录 WHERE company_name LIKE %s LIMIT {limit}""",
            (_like(keyword),),
        )
        rows = _sanitize(list(cur.fetchall()))
    return {"total": len(rows), "rows": rows}


# ── 政策文件名匹配（政策全文的向量检索在 agent/tools.py 中）─────────────────


def search_policy_files(keyword: str, limit: int = 5) -> list[dict[str, Any]]:
    """按名称关键词匹配政策文件（返回名称/日期/来源链接）。"""
    limit = max(1, min(int(limit or 5), 10))
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT policy_name, publish_date, source_url
                 FROM policy_政策文件 WHERE policy_name LIKE %s
                 ORDER BY publish_date DESC LIMIT {limit}""",
            (_like(keyword),),
        )
        return _sanitize(list(cur.fetchall()))
