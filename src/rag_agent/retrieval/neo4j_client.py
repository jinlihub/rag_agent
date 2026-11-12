"""Neo4j 图数据库查询客户端：GraphRAG 的数据源之一。

图模型（节点标签 / 关系类型）：
    节点  Item(标的物)  Purchaser(采购商)  Supplier(供应商)
          Agency(代理机构)  Location(所在地)
    关系  采购 (Purchaser)-[:采购]->(Item)，含属性 amount(元)
          中标 (Supplier)-[:中标]->(Item)，含属性 amount(元)
          委托 (Purchaser)-[:委托]->(Agency)
          位于 (Item)-[:位于]->(Location)

客户端只做两件事：建立/复用驱动连接、执行受限的 Cypher 查询。
查询能力由 tools/graph_tools.py 里的预定义模板约束，模型不能直接传 Cypher。
"""

from __future__ import annotations

import threading
from typing import Any

from rag_agent.config import get_settings


class Neo4jNotConfigured(RuntimeError):
    """未配置 NEO4J_URI。"""


# Driver 内部就是连接池，必须全局复用；每次 query 新建/销毁会重复付建连与 TLS 握手开销
_driver_instance = None
_driver_lock = threading.Lock()


def _driver():
    global _driver_instance
    if _driver_instance is not None:
        return _driver_instance
    with _driver_lock:
        if _driver_instance is not None:  # 双检，避免并发时重复建池
            return _driver_instance
        try:
            from neo4j import GraphDatabase  # 延迟导入：未装驱动时不拖累其他模块
        except ImportError as e:  # pragma: no cover - 依赖缺失提示
            raise RuntimeError(
                "未安装 neo4j 驱动，请先执行: uv add neo4j"
            ) from e
        s = get_settings()
        if not s.neo4j_uri:
            raise Neo4jNotConfigured(
                "Neo4j 未配置（.env 缺少 NEO4J_URI），图查询不可用"
            )
        _driver_instance = GraphDatabase.driver(
            s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password)
        )
        return _driver_instance


def query(cypher: str, **params: Any) -> list[dict[str, Any]]:
    """执行只读 Cypher，返回记录列表（dict 值均 JSON 可序列化）。

    调用方（图查询工具）只传预定义的只读查询模板；本函数不开放任意 Cypher。
    Driver 复用模块级单例，连接池跨请求共享；进程退出时由 GC 回收，不需显式 close。
    """
    with _driver().session() as session:
        result = session.run(cypher, **params)
        return [{k: record[k] for k in record.keys()} for record in result]
