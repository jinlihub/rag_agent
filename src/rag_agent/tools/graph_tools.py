"""Neo4j 图查询工具：把知识图谱（GraphRAG）能力注册成 Agent 可调用的工具。

与 rag_tools.py 里的 search_knowledge_graph（查 MySQL 的工商/中标/违规关联）不同，
本工具查的是 Neo4j 里的「采购交易图谱」——标的物、采购商、供应商、代理机构、所在地
之间的结构化关系，回答多跳、反向关联、共现类问题。

只提供预定义查询模板（实体画像 / 反向关联 / 多跳路径 / 共现），模型只填参数，
不直接写 Cypher，避免语法错误与危险查询。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from rag_agent.retrieval.neo4j_client import Neo4jNotConfigured, query
from rag_agent.tools.base import BaseTool, ToolArgs

QueryKind = Literal["entity", "reverse", "path", "cooccur"]


class GraphQueryArgs(ToolArgs):
    entity: str = Field(description="实体名称（标的物/采购商/供应商/代理机构名），如'超声波流量计'")
    kind: QueryKind = Field(
        default="entity",
        description=(
            "查询类型：entity=实体画像（某实体关联了哪些采购商/供应商/标的物，默认）；"
            "reverse=反向关联（某标的物被哪些采购商采购、被哪些供应商中标）；"
            "path=多跳路径（从某采购商出发，经供应商再到其他采购商的链路）；"
            "cooccur=共现（哪些供应商经常中标同一类标的物）"
        ),
    )
    limit: int = Field(default=8, ge=1, le=20, description="返回条数上限，默认 8")


class SearchGraphQueryTool(BaseTool):
    name = "graph_query"
    description = (
        "查询 Neo4j 知识图谱（采购交易图谱：标的物-采购商-供应商-代理机构-所在地的关系网）。"
        "适用于实体关系、多跳关联、反向追溯、共现分析类问题，例如："
        "'某供应商中标过哪些标的物'、'某标的物被哪些采购商采购'、"
        "'给A供货的供应商还服务过谁'、'哪些供应商常竞争同类标的物'。"
        "返回：按查询类型组织的关系记录（名称、关系类型、关联实体、金额等）。"
        "注意：本工具查的是交易关系图谱，工商信息/违规记录请用 search_knowledge_graph。"
    )
    args_model = GraphQueryArgs
    source_kind = "graph_neo4j"
    source_title_key = "title"
    empty_hint = "可换实体名称（全称/简称/关键词），或换查询类型（entity/reverse/path/cooccur）重试。"

    def source_items(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        return result.get("rows") or []

    def run(self, args: GraphQueryArgs) -> dict[str, Any]:
        try:
            rows = self._run(args.kind, args.entity, args.limit)
        except Neo4jNotConfigured as e:
            return {"error": str(e)}
        result: dict[str, Any] = {"entity": args.entity, "kind": args.kind, "rows": rows}
        if not rows:
            result["note"] = "未找到与该实体相关的图数据"
        return result

    def _run(self, kind: str, entity: str, limit: int) -> list[dict[str, Any]]:
        name = entity.strip()
        if kind == "entity":
            return self._entity_profile(name, limit)
        if kind == "reverse":
            return self._reverse(name, limit)
        if kind == "path":
            return self._path(name, limit)
        return self._cooccur(name, limit)

    # ── 各查询模板（只读，参数化，禁任意 Cypher）────────────────────────

    def _entity_profile(self, name: str, limit: int) -> list[dict[str, Any]]:
        """某实体的直接关联：作为采购商/供应商/代理机构各关联了什么，或作为标的物被谁关联。"""
        cypher = (
            "MATCH (n) WHERE n.name = $name "
            "OPTIONAL MATCH (n)-[r1]->(m1) "
            "OPTIONAL MATCH (m2)-[r2]->(n) "
            "RETURN n.name AS title, "
            "       labels(n) AS labels, "
            "       collect(DISTINCT {rel: type(r1), to: m1.name})[..$limit] AS outgoing, "
            "       collect(DISTINCT {rel: type(r2), from: m2.name})[..$limit] AS incoming"
        )
        rec = query(cypher, name=name, limit=limit)
        if not rec:
            return []
        row = rec[0]
        out = []
        for d in (row.get("outgoing") or []):
            if d and d.get("to"):
                out.append({"title": d["to"], "relation": d.get("rel"), "direction": "out"})
        for d in (row.get("incoming") or []):
            if d and d.get("from"):
                out.append({"title": d["from"], "relation": d.get("rel"), "direction": "in"})
        return out

    def _reverse(self, name: str, limit: int) -> list[dict[str, Any]]:
        """以标的物为中心的反向关联：谁采购了它、谁中标了它。"""
        cypher = (
            "MATCH (i:Item {name: $name}) "
            "OPTIONAL MATCH (p:Purchaser)-[r1:采购]->(i) "
            "OPTIONAL MATCH (s:Supplier)-[r2:中标]->(i) "
            "RETURN collect(DISTINCT {title: p.name, relation: '采购', amount: r1.amount})[..$limit] AS purchasers, "
            "       collect(DISTINCT {title: s.name, relation: '中标', amount: r2.amount})[..$limit] AS suppliers"
        )
        rec = query(cypher, name=name, limit=limit)
        if not rec:
            return []
        rows = []
        for d in (rec[0].get("purchasers") or []):
            if d and d.get("title"):
                rows.append({"title": d["title"], "relation": "采购", "amount": d.get("amount")})
        for d in (rec[0].get("suppliers") or []):
            if d and d.get("title"):
                rows.append({"title": d["title"], "relation": "中标", "amount": d.get("amount")})
        return rows

    def _path(self, name: str, limit: int) -> list[dict[str, Any]]:
        """多跳：从某采购商出发，经中标供应商，再穿透到该供应商服务过的其他采购商。"""
        cypher = (
            "MATCH (p:Purchaser {name: $name})-[:采购]->(i:Item)<-[:中标]-(s:Supplier) "
            "MATCH (s)-[:中标]->(i2:Item)<-[:采购]-(p2:Purchaser) "
            "WHERE p2.name <> $name "
            "RETURN s.name AS supplier, p2.name AS other_purchaser, count(DISTINCT i2) AS shared "
            "ORDER BY shared DESC LIMIT $limit"
        )
        rows = query(cypher, name=name, limit=limit)
        return [
            {"title": r.get("other_purchaser"), "relation": "同供应商间接关联",
             "supplier": r.get("supplier"), "shared": r.get("shared")}
            for r in rows if r.get("other_purchaser")
        ]

    def _cooccur(self, name: str, limit: int) -> list[dict[str, Any]]:
        """共现：与某供应商中标过同一（或同类）标的物的其他供应商。"""
        cypher = (
            "MATCH (s:Supplier {name: $name})-[:中标]->(i:Item)<-[:中标]-(s2:Supplier) "
            "WHERE s2.name <> $name "
            "RETURN s2.name AS title, collect(DISTINCT i.name)[..3] AS items, "
            "       count(DISTINCT i) AS shared "
            "ORDER BY shared DESC LIMIT $limit"
        )
        rows = query(cypher, name=name, limit=limit)
        return [
            {"title": r.get("title"), "relation": "共同中标", "items": r.get("items"), "shared": r.get("shared")}
            for r in rows if r.get("title")
        ]
