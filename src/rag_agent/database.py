"""MySQL 连接与查询辅助。"""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

import pymysql
from pymysql.cursors import DictCursor

from rag_agent.config import get_settings


@lru_cache(maxsize=1)
def _connect_kwargs() -> dict[str, Any]:
    s = get_settings()
    return dict(
        host=s.db_host,
        port=s.db_port,
        user=s.db_user,
        password=s.db_password,
        database=s.db_name,
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=5,
    )


@contextmanager
def get_conn() -> Iterator[pymysql.connections.Connection]:
    """短连接：用完即关。MVP 阶段查询频率低，最省心。"""
    conn = pymysql.connect(**_connect_kwargs())
    try:
        yield conn
    finally:
        conn.close()


def query_all(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())
