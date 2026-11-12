"""RAG 工具集：四个工具按数据源分工（Pydantic 模型声明参数，Schema 自动生成）。

  - search_bidding_knowledge  本地知识库混合检索（法条/政策/FAQ：dense+sparse RRF 融合 → 重排）
  - search_knowledge_graph    实体关系图谱（企业/采购人/代理机构/违规，MySQL 关联查询）
  - search_postgresql         结构化标的物记录（PostgreSQL bid_subjects，按标的物/筛选/排序/时间夹取）
  - search_web                Tavily 联网搜索（前端联网开关开启时为必调工具）
  - ask_user                  指代不明/实体歧义/时间口径模糊时主动澄清（不查数据）
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal
from typing import Any, Literal

import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import Field

from rag_agent.config import get_settings
from rag_agent.database import get_conn
from rag_agent.retrieval import sql_search
from rag_agent.retrieval.fusion import profile_for, rrf_fuse
from rag_agent.retrieval.rerank import CANDIDATE_CAP, rerank
from rag_agent.retrieval.sparse import get_sparse
from rag_agent.retrieval.vector_store import IndexNotBuilt, get_store
from rag_agent.tools.ask_user import AskUserTool
from rag_agent.tools.base import BaseTool, ToolArgs
from rag_agent.tools.graph_tools import SearchGraphQueryTool
from rag_agent.tools.mcp_tools import ExaWebSearchTool
from rag_agent.web_search import NotConfigured, web_search


def _clip(text: str | None, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def _like(keyword: str) -> str:
    """转义 LIKE 通配符后包上 %%（MySQL/PostgreSQL 默认都认反斜杠转义）。"""
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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


def _rerank_hits(query: str, hits: list[dict], top_k: int, text_key: str) -> list[dict]:
    """过量召回 → 重排 → 截取 top_k；score 回填为重排后的相关性分（0~1）。

    重排关闭或失败时保持融合序，退回"截前 top_k"。
    """
    if len(hits) <= top_k:
        return hits
    ranked = rerank(query, [str(h.get(text_key) or "") for h in hits])
    if ranked is None:
        return hits[:top_k]
    return [{**hits[i], "score": round(v, 3)} for i, v in ranked[:top_k]]


def _hybrid_hits(query: str, store_name: str, top_k: int) -> list[dict]:
    """dense + sparse 双路召回 → 按问题类型加权 RRF 融合（见 retrieval/fusion.py）。

    法规类偏 sparse（法名/术语关键词强特征）、概念类偏 dense（问法与原文措辞
    差异大，语义近似更可靠）；两路与重排共用同一份语料，k/权重随问题类型变化。
    """
    cap = min(top_k * 3, CANDIDATE_CAP)
    dense = get_store(store_name).search(query, top_k=cap)
    sparse = get_sparse(store_name).search(query, top_k=cap)
    p = profile_for(query)
    return rrf_fuse([(dense, p["dense"]), (sparse, p["sparse"])], p["k"])


# 行业办法关键词：出现这些词说明用户在问特定行业，不做通用法加权
_INDUSTRY_WORDS = frozenset(
    {
        "铁路", "水利", "公路", "交通", "通信", "民航", "核电", "军工", "农业",
        "石油", "电力", "煤炭", "冶金", "化工", "林业", "港口", "航道", "城市建设",
    }
)

# 国家级通用法：与行业办法表述高度相似，但适用面更广，通用提问时应优先
_GENERAL_LAWS = ("中华人民共和国招标投标法", "中华人民共和国政府采购法")


def _prefer_general_law(hits: list[dict], query: str) -> list[dict]:
    """通用法优先：用户未提行业时，给通用法微加权。

    法规库里行业办法（铁路/水利/通信…）数量多、表述与通用法高度相似，
    密集召回会把《招标投标法》《政府采购法》压到十几位之外；而用户问
    「招标文件要写什么」这类通用问题时，先给通用法条更合理。
    用户明确提了行业（如「铁路项目」）则保持原序，不做干预。
    """
    if any(w in query for w in _INDUSTRY_WORDS):
        return hits
    boosted = [
        {**h, "score": round(h.get("score", 0) * 1.1, 3)}
        if any(g in (h.get("law_name") or "") for g in _GENERAL_LAWS)
        else h
        for h in hits
    ]
    # score 已归一到 0~1，加权后应大于 1 时不再截断，仅用于排序
    return sorted(boosted, key=lambda x: -x.get("score", 0))


# ── 1. 本地知识库向量检索（法条/政策/FAQ 合并为一个工具）────────────────────

KnowledgeScope = Literal["all", "legal", "policy", "faq"]


class BiddingKnowledgeArgs(ToolArgs):
    query: str = Field(description="语义查询句，如'供应商提出质疑的时限是多少天'")
    scope: KnowledgeScope = Field(
        default="all",
        description="检索范围：all=全部知识库（默认），legal=法规条文，policy=政策全文，faq=实务问答",
    )
    top_k: int = Field(default=4, ge=1, le=6, description="每个知识库返回条数上限")


class SearchBiddingKnowledgeTool(BaseTool):
    name = "search_bidding_knowledge"
    description = (
        "语义检索本地招投标知识库（法规条文/政策全文/实务问答对）。适用于：法规依据类"
        "（质疑异议时限、单一来源采购条件等）、政策文件类、招投标实务操作类问题。"
        "返回：法规名/文件名/问题、内容节选、相关性评分。"
    )
    args_model = BiddingKnowledgeArgs
    source_kind = "knowledge"
    source_title_key = "title"
    empty_hint = "可改写查询词、换 scope（legal/policy/faq），或改用 search_web 联网补充。"

    def run(self, args: BiddingKnowledgeArgs) -> dict[str, Any]:
        top_k = args.top_k
        profile = profile_for(args.query)  # 问题类型 → 融合参数（法规偏关键词/概念偏语义）
        matches: list[dict[str, Any]] = []
        notes: list[str] = []

        if args.scope in ("all", "legal"):
            hits = _prefer_general_law(_hybrid_hits(args.query, "legal", top_k), args.query)
            for h in _rerank_hits(args.query, hits, top_k, "text"):
                matches.append(
                    {
                        "kind": "legal",
                        "title": " ".join(x for x in (h.get("law_name"), h.get("article_title")) if x),
                        "law_name": h.get("law_name"),
                        "law_type": h.get("law_type"),
                        "article_title": h.get("article_title"),
                        "text": _clip(h.get("text"), 500),
                        "score": round(h["score"], 3),
                    }
                )

        if args.scope in ("all", "policy"):
            try:
                hits = _hybrid_hits(args.query, "policy", top_k)
                for h in _rerank_hits(args.query, hits, top_k, "text"):
                    matches.append(
                        {
                            "kind": "policy",
                            "title": h.get("title"),
                            "text": _clip(h.get("text"), 500),
                            "score": round(h["score"], 3),
                        }
                    )
            except IndexNotBuilt:
                notes.append("政策全文向量索引未构建，仅返回文件名匹配")
            try:
                files = sql_search.search_policy_files(args.query)
            except Exception:  # noqa: BLE001 —— 文件名匹配是辅助信息，库不可达不影响向量结果
                files = []
            matches.extend(
                {
                    "kind": "policy",
                    "match_type": "文件名匹配",
                    "title": f.get("policy_name"),
                    "publish_time": f.get("publish_date"),
                    "url": f.get("source_url"),
                }
                for f in files
            )

        if args.scope in ("all", "faq"):
            faq_k = min(top_k, 2)  # FAQ 用问题文本做向量，重排也按问题文本比
            hits = _hybrid_hits(args.query, "faq", faq_k)
            for h in _rerank_hits(args.query, hits, faq_k, "question"):
                matches.append(
                    {
                        "kind": "faq",
                        "title": h.get("question"),
                        "answer": _clip(h.get("answer"), 800),
                        "score": round(h["score"], 3),
                    }
                )

        result: dict[str, Any] = {
            "matches": matches,
            # 检索策略回显：便于核对问题类型判定与融合参数
            "retrieval": {
                "query_kind": profile["kind"],
                "rrf_k": profile["k"],
                "dense_weight": profile["dense"],
                "sparse_weight": profile["sparse"],
            },
        }
        if notes:
            result["note"] = "；".join(notes)
        return result


# ── 2. 实体关系图谱（MySQL：企业/中标/采购/代理/违规 关联查询）──────────────

GraphRelation = Literal["all", "profile", "wins", "purchases", "agency", "violations"]

_RELATION_LABELS = {
    "profile": "工商信息",
    "wins": "中标的项目",
    "purchases": "作为采购人的项目",
    "agency": "作为代理机构的项目",
    "violations": "违法违规记录",
}


class KnowledgeGraphArgs(ToolArgs):
    entity: str = Field(description="实体名称：企业/中标人/采购人/代理机构名称或关键词，如'华润燃气'")
    relation: GraphRelation = Field(
        default="all",
        description=(
            "关注的实体关系：all=全部（默认），profile=工商信息，wins=中标记录，"
            "purchases=作为采购人的项目，agency=作为代理机构的项目，violations=违法违规记录"
        ),
    )
    limit: int = Field(default=5, ge=1, le=10, description="每类关系返回条数上限")


class SearchKnowledgeGraphTool(BaseTool):
    name = "search_knowledge_graph"
    description = (
        "查询企业维度的关联档案：工商信息（法人/注册资本/信用等级/经营状态）、"
        "中标记录与汇总（全量中标次数、总金额、主要采购人 TOP3）、"
        "作为采购人/代理机构参与的项目、违法违规记录。"
        "回答『某公司实力/背景/靠谱程度』这类企业画像问题时，用 relation=all 一次取全五类素材。"
        "注意：中标/采购明细只返回前 limit 条，需要完整项目清单或按标的物（如'空调'）检索时，"
        "改用 search_postgresql。返回：按关系分组的关联记录 + wins_summary 中标汇总。"
    )
    args_model = KnowledgeGraphArgs
    source_kind = "graph"
    source_title_key = "title"
    empty_hint = "可换实体名称关键词（全称/简称），或改用 search_postgresql 按该实体名称检索关联项目。"

    def assess_quality(self, result: dict[str, Any]) -> dict[str, Any]:
        """图谱结果按 edges 聚合判断：单关系失败不判负，全部为空才算。"""
        errors = result.get("errors") or {}
        if not result.get("edges") and errors:
            return {"verdict": "error", "hint": "各关系查询均失败，可稍后重试或改用其他工具。"}
        if not result.get("edges"):
            return {"verdict": "empty", "hint": self.empty_hint}
        return {"verdict": "ok"}

    def source_items(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        """图谱结果是按关系分组的 edges，拍平后参与来源折叠。"""
        rows: list[dict[str, Any]] = []
        for group in (result.get("edges") or {}).values():
            rows.extend(group)
        return rows

    def run(self, args: KnowledgeGraphArgs) -> dict[str, Any]:
        relations = list(_RELATION_LABELS) if args.relation == "all" else [args.relation]
        edges: dict[str, list[dict[str, Any]]] = {}
        errors: dict[str, str] = {}
        wins_summary: dict[str, Any] | None = None
        for rel in relations:
            try:
                rows = self._query(rel, args.entity, args.limit)
                if rows:
                    edges[rel] = rows
            except Exception as e:  # noqa: BLE001 —— 逐关系容错：单表缺失不影响其他关系
                errors[rel] = f"{type(e).__name__}: {e}"
            if rel == "wins":
                # 中标汇总独立于明细 LIMIT：明细只有前 N 条，算不出总次数/总金额/主要采购人
                try:
                    wins_summary = self._wins_summary(args.entity)
                except Exception as e:  # noqa: BLE001 —— 汇总失败只降级，不影响明细
                    errors["wins_summary"] = f"{type(e).__name__}: {e}"

        result: dict[str, Any] = {"entity": args.entity, "edges": edges}
        if wins_summary is not None:
            result["wins_summary"] = wins_summary
        if errors:
            result["errors"] = errors
        if not edges and not errors:
            result["note"] = "未找到与该实体相关的记录"
        return result

    def _wins_summary(self, entity: str, top_n: int = 3) -> dict[str, Any]:
        """中标表现汇总：全量中标次数、总金额、主要采购人 TOP N。

        与 wins 明细的口径一致（winner LIKE），但不带 LIMIT，因此能反映该企业的
        整体中标规模——企业画像里「中标表现」一节的素材就来自这里。
        """
        like = _like(entity)
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total_wins, SUM(award_amount) AS total_amount"
                "  FROM bid_subjects WHERE winner LIKE %s",
                [like],
            )
            total_row = _sanitize([cur.fetchone() or {}])[0]
            cur.execute(
                "SELECT purchaser, COUNT(*) AS wins, SUM(award_amount) AS amount"
                "  FROM bid_subjects"
                " WHERE winner LIKE %s AND purchaser IS NOT NULL AND purchaser <> ''"
                " GROUP BY purchaser ORDER BY wins DESC, amount DESC"
                f" LIMIT {int(top_n)}",
                [like],
            )
            purchaser_rows = _sanitize(list(cur.fetchall()))

        total_amount = total_row.get("total_amount")
        top_purchasers = []
        for r in purchaser_rows:
            amount = r.get("amount")
            top_purchasers.append(
                {
                    "purchaser": r.get("purchaser"),
                    "wins": int(r.get("wins") or 0),
                    "amount_wan": round(amount / 10000, 2) if amount is not None else None,
                }
            )
        return {
            "total_wins": int(total_row.get("total_wins") or 0),
            "total_amount_wan": (
                round(total_amount / 10000, 2) if total_amount is not None else None
            ),
            "top_purchasers": top_purchasers,
            "note": "本汇总为全量统计，不受 limit 约束；明细见 edges.wins（按 limit 截断）",
        }

    def _query(self, rel: str, entity: str, limit: int) -> list[dict[str, Any]]:
        """单类关系查询；行统一带 relation（中文标签）与 title（来源面板标题）。"""
        like = _like(entity)
        sql: str
        params: list[Any] = [like]
        if rel == "profile":
            sql = (
                "SELECT company_name AS title, legal_person, credit_rating, registered_capital,"
                "       establish_date, business_status"
                "  FROM enterprise_企业信息 WHERE company_name LIKE %s ORDER BY id LIMIT {n}"
            )
        elif rel == "wins":
            sql = (
                "SELECT title, category, purchaser, award_amount, award_time, province, city"
                "  FROM bid_subjects WHERE winner LIKE %s ORDER BY award_time DESC LIMIT {n}"
            )
        elif rel == "purchases":
            sql = (
                "SELECT title, category, publish_time, winner, province, city"
                "  FROM bid_subjects WHERE purchaser LIKE %s ORDER BY publish_time DESC LIMIT {n}"
            )
        elif rel == "agency":
            sql = (
                "SELECT title, publish_time, purchaser, winner"
                "  FROM bid_subjects WHERE agency LIKE %s ORDER BY publish_time DESC LIMIT {n}"
            )
        else:  # violations
            sql = (
                "SELECT company_name AS title, credit_code, penalty_date, publish_deadline,"
                "       law_enforcement_unit"
                "  FROM enterprise_违法违规记录 WHERE company_name LIKE %s LIMIT {n}"
            )
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(sql.format(n=int(limit)), params)
            rows = _sanitize(list(cur.fetchall()))
        for r in rows:
            r["relation"] = _RELATION_LABELS[rel]
            if r.get("award_amount") is not None:
                r["award_amount_wan"] = round(r["award_amount"] / 10000, 2)  # 元 → 万元
        return rows


# ── 3. PostgreSQL 结构化检索（bid_subjects，注入见 src/database/to_postgresql.py）──


class PostgresqlArgs(ToolArgs):
    keyword: str | None = Field(default=None, description="项目名称/标题/中标人关键词，如'挖掘机''EPC'")
    subject: str | None = Field(
        default=None,
        description=(
            "标的物名称或关键词，如'空调''复印纸'。用于『有哪些关于空调的采购』"
            "『空调的供应商有哪些』这类按标的物检索的问题——本参数查 subject 列，"
            "不要用 keyword（它只匹配标题/项目名/企业名）"
        ),
    )
    province: str | None = Field(default=None, description="省份，如'安徽省'")
    city: str | None = Field(default=None, description="地级市，如'合肥市'")
    category: str | None = Field(default=None, description="类别：工程/货物/服务")
    only_awarded: bool = Field(default=False, description="只看已中标的项目，默认 false")
    date_from: str | None = Field(
        default=None, description="起始日期 YYYY-MM-DD（已中标按中标时间，否则按发布时间）"
    )
    date_to: str | None = Field(default=None, description="结束日期 YYYY-MM-DD")
    order: Literal["time", "amount"] = Field(
        default="time", description="排序：time=时间倒序（默认），amount=中标金额倒序"
    )
    limit: int = Field(default=8, ge=1, le=10, description="返回条数上限，默认 8")
    group_by: Literal["category", "month"] | None = Field(
        default=None,
        description=(
            "聚合维度：category=按类别统计项目数量；month=按月统计项目数量。"
            "仅「按类别/按月统计、趋势、占比」这类问题设置；设置后返回分组统计与图表，"
            "不要同时设置 limit（聚合结果不受其影响）"
        ),
    )


class SearchPostgresqlTool(BaseTool):
    name = "search_postgresql"
    description = (
        "检索 PostgreSQL 招标采购标的物记录（含中标结果）。用于：按中标人/采购人名称查项目清单、"
        "按标的物名称检索、按地域/类别/时间/金额筛选、排序与聚合。"
        "需要项目明细（名称、金额、时间）或按标的物（如'空调'）检索时用本工具。"
        "「按类别/按月统计项目数量」等趋势、占比类问题，设置 group_by 返回分组结果与图表。"
        "返回：标题、类别、省市区、采购人、代理机构、预算、中标人、中标金额（元与万元）、中标时间、标的物；"
        "聚合查询额外返回分组统计与 chart（ECharts option）。"
    )
    args_model = PostgresqlArgs
    source_kind = "bid_subject"
    source_title_key = "title"
    empty_hint = "可放宽筛选（减少地域/类别/时间限制）、换关键词，或把时间范围调整到系统提示所列的数据覆盖期内。"

    def run(self, args: PostgresqlArgs) -> dict[str, Any]:
        if args.group_by:
            try:
                conn = self._connect()
            except Exception:  # noqa: BLE001 —— PostgreSQL 未部署属预期环境，降级查 MySQL
                return self._run_grouped_mysql(args)
            try:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    rows = self._grouped_rows_pg(cur, args)
            finally:
                conn.close()
            return self._grouped_result(args, rows)
        try:
            conn = self._connect()
        except Exception:  # noqa: BLE001 —— PostgreSQL 未部署属预期环境，降级查 MySQL
            return self._run_mysql(args)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                where: list[str] = []
                params: list[Any] = []
                if args.keyword:
                    like = _like(args.keyword)
                    where.append("(title LIKE %s OR project_name LIKE %s OR purchaser LIKE %s OR winner LIKE %s)")
                    params += [like, like, like, like]
                if args.subject:
                    where.append("subject LIKE %s")
                    params.append(_like(args.subject))
                if args.province:
                    where.append("province LIKE %s")
                    params.append(f"%{args.province}%")
                if args.city:
                    where.append("city LIKE %s")
                    params.append(f"%{args.city}%")
                if args.category:
                    where.append("category = %s")
                    params.append(args.category)
                if args.only_awarded:
                    where.append("winner IS NOT NULL")
                date_col = "award_time" if args.only_awarded else "publish_time"
                clamp_note: str | None = None
                if args.date_from or args.date_to:
                    # 时间夹取（与覆盖范围无交集时自动改查最近等长时段）；占位符/游标形态与 PG 兼容
                    date_from, date_to, clamp_note = sql_search.clamp_date_range(
                        cur, "bid_subjects", date_col, args.date_from, args.date_to
                    )
                else:
                    date_from, date_to = args.date_from, args.date_to
                if date_from:
                    where.append(f"{date_col} >= %s")
                    params.append(date_from)
                if date_to:
                    where.append(f"{date_col} <= %s")
                    params.append(f"{date_to} 23:59:59")
                clause = (" WHERE " + " AND ".join(where)) if where else ""
                order_sql = "award_amount DESC" if args.order == "amount" else f"{date_col} DESC"

                cur.execute(f"SELECT COUNT(*) AS c FROM bid_subjects{clause}", params)
                total = cur.fetchone()["c"]
                cur.execute(
                    f"""SELECT title, category, source, province, city, county, project_no,
                               project_name, purchaser, agency, budget, winner, award_amount,
                               award_time, publish_time, subject
                        FROM bid_subjects{clause} ORDER BY {order_sql} LIMIT {args.limit}""",
                    params,
                )
                rows = _sanitize(list(cur.fetchall()))
        finally:
            conn.close()

        for r in rows:
            if r.get("award_amount") is not None:
                r["award_amount_wan"] = round(r["award_amount"] / 10000, 2)  # 元 → 万元
        result: dict[str, Any] = {"total": total, "rows": rows}
        if clamp_note:
            result["note"] = clamp_note
        return result

    def _run_mysql(self, args: PostgresqlArgs) -> dict[str, Any]:
        """PostgreSQL 不可用时的降级实现：查 MySQL 的 bid_subjects。

        MySQL 表前 18 列与 PG 完全一致，但没有 subject 列，因此标的物条件
        降级为标题关键词匹配（title/project_name 通常含标的物名）。
        时间范围不做夹取校正（那是 PG 侧的辅助优化），由提示词的数据覆盖范围兜底。
        """
        notes: list[str] = ["PostgreSQL 不可用，已改用 MySQL 数据源"]
        keyword = args.keyword
        if args.subject:
            if keyword:
                notes.append("标的物条件已并入标题关键词一并匹配")
            else:
                keyword = args.subject
                notes.append("标的物条件已降级为标题关键词匹配")

        where: list[str] = []
        params: list[Any] = []
        if keyword:
            like = _like(keyword)
            where.append("(title LIKE %s OR project_name LIKE %s OR purchaser LIKE %s OR winner LIKE %s)")
            params += [like, like, like, like]
        if args.province:
            where.append("province LIKE %s")
            params.append(f"%{args.province}%")
        if args.city:
            where.append("city LIKE %s")
            params.append(f"%{args.city}%")
        if args.category:
            where.append("category = %s")
            params.append(args.category)
        if args.only_awarded:
            where.append("winner IS NOT NULL")
        date_col = "award_time" if args.only_awarded else "publish_time"
        if args.date_from:
            where.append(f"{date_col} >= %s")
            params.append(args.date_from)
        if args.date_to:
            where.append(f"{date_col} <= %s")
            params.append(f"{args.date_to} 23:59:59")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        order_sql = "award_amount DESC" if args.order == "amount" else f"{date_col} DESC"

        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM bid_subjects{clause}", params)
            count_row = cur.fetchone()
            total = list(count_row.values())[0] if isinstance(count_row, dict) else count_row[0]
            cur.execute(
                f"""SELECT title, category, source, province, city, county, project_no,
                           project_name, purchaser, agency, budget, winner, award_amount,
                           award_time, publish_time
                    FROM bid_subjects{clause} ORDER BY {order_sql} LIMIT {args.limit}""",
                params,
            )
            rows = _sanitize(list(cur.fetchall()))

        for r in rows:
            if r.get("award_amount") is not None:
                r["award_amount_wan"] = round(r["award_amount"] / 10000, 2)  # 元 → 万元
        return {"total": total, "rows": rows, "note": "；".join(notes)}

    def _group_where(
        self, args: PostgresqlArgs, date_col: str, *, postgres: bool
    ) -> tuple[list[str], list[Any]]:
        """聚合查询的筛选条件（业务口径与明细查询一致）。"""
        where: list[str] = []
        params: list[Any] = []
        keyword = args.keyword
        if args.subject:
            if postgres:
                where.append("subject LIKE %s")
                params.append(_like(args.subject))
            elif not keyword:
                # MySQL 没有 subject 列：与降级明细查询一致，用标题关键词兜底
                keyword = args.subject
        if keyword:
            like = _like(keyword)
            where.append("(title LIKE %s OR project_name LIKE %s OR purchaser LIKE %s OR winner LIKE %s)")
            params += [like, like, like, like]
        if args.province:
            where.append("province LIKE %s")
            params.append(f"%{args.province}%")
        if args.city:
            where.append("city LIKE %s")
            params.append(f"%{args.city}%")
        if args.category:
            where.append("category = %s")
            params.append(args.category)
        if args.only_awarded:
            where.append("winner IS NOT NULL")
        if args.date_from:
            where.append(f"{date_col} >= %s")
            params.append(args.date_from)
        if args.date_to:
            where.append(f"{date_col} <= %s")
            params.append(f"{args.date_to} 23:59:59")
        return where, params

    def _grouped_rows_pg(self, cur: Any, args: PostgresqlArgs) -> list[dict[str, Any]]:
        """PostgreSQL 分组查询：按类别或按月份统计项目数量。"""
        date_col = "award_time" if args.only_awarded else "publish_time"
        where, params = self._group_where(args, date_col, postgres=True)
        if args.group_by == "category":
            where.append("category IS NOT NULL AND TRIM(category) <> ''")
            select = "SELECT category AS name, COUNT(*) AS value"
            group = " GROUP BY category ORDER BY value DESC, category"
        else:
            where.append(f"{date_col} IS NOT NULL")
            select = (
                f"SELECT to_char(date_trunc('month', {date_col}), 'YYYY-MM') AS name, "
                "COUNT(*) AS value"
            )
            group = " GROUP BY 1 ORDER BY 1"
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        cur.execute(f"{select} FROM bid_subjects{clause}{group}", params)
        return _sanitize(list(cur.fetchall()))

    def _run_grouped_mysql(self, args: PostgresqlArgs) -> dict[str, Any]:
        """PostgreSQL 不可用时的降级聚合：MySQL 的分组统计。"""
        notes = ["PostgreSQL 不可用，已改用 MySQL 数据源"]
        if args.subject:
            notes.append(
                "标的物条件已并入标题关键词一并匹配"
                if args.keyword
                else "标的物条件已降级为标题关键词匹配"
            )
        date_col = "award_time" if args.only_awarded else "publish_time"
        where, params = self._group_where(args, date_col, postgres=False)
        if args.group_by == "category":
            where.append("category IS NOT NULL AND TRIM(category) <> ''")
            select = "SELECT category AS name, COUNT(*) AS value"
            group = " GROUP BY category ORDER BY value DESC, category"
        else:
            where.append(f"{date_col} IS NOT NULL")
            # pymysql 走参数化查询时会把 % 当占位符，格式化串里的 % 需要写成 %%
            select = f"SELECT DATE_FORMAT({date_col}, '%%Y-%%m') AS name, COUNT(*) AS value"
            group = " GROUP BY 1 ORDER BY 1"
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(f"{select} FROM bid_subjects{clause}{group}", params)
            rows = _sanitize(list(cur.fetchall()))
        return self._grouped_result(args, rows, "；".join(notes))

    def _grouped_result(
        self,
        args: PostgresqlArgs,
        rows: list[dict[str, Any]],
        note: str | None = None,
    ) -> dict[str, Any]:
        """把分组结果收敛成 {total, rows, chart}；chart 完全由代码从结果算出。"""
        items: list[dict[str, Any]] = []
        for r in rows:
            name = r.get("name")
            if name in (None, ""):
                continue
            try:
                value = int(r.get("value"))
            except (TypeError, ValueError):
                continue
            items.append({"name": str(name), "value": value})
        result: dict[str, Any] = {"total": sum(i["value"] for i in items), "rows": items}
        if note:
            result["note"] = note
        if items:
            result["chart"] = self._chart_spec(args.group_by, items)
        return result

    @staticmethod
    def _chart_spec(group_by: str | None, items: list[dict[str, Any]]) -> dict[str, Any]:
        """按分组维度生成 ECharts option（纯代码，不调用模型）。"""
        total = sum(i["value"] for i in items)
        if group_by == "category":
            return {
                "title": {
                    "text": "按类别统计项目数量",
                    "subtext": f"共 {total} 个项目",
                    "left": 12,
                    "top": 4,
                    "textAlign": "left",
                    "textStyle": {"fontSize": 13},
                    "subtextStyle": {"fontSize": 11},
                },
                "tooltip": {"trigger": "item", "formatter": "{b}: {c} 个（{d}%）"},
                "series": [
                    {
                        "type": "pie",
                        "radius": ["28%", "46%"],
                        "center": ["50%", "55%"],
                        "data": items,
                        "label": {"formatter": "{b}\n{d}%", "fontSize": 11},
                        "labelLine": {"length": 8, "length2": 8},
                        "avoidLabelOverlap": True,
                    }
                ],
            }
        return {
            "title": {
                "text": "按月统计项目数量",
                "subtext": f"共 {total} 个项目",
                "left": 12,
                "top": 4,
                "textAlign": "left",
                "textStyle": {"fontSize": 13},
                "subtextStyle": {"fontSize": 11},
            },
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 48, "right": 24, "top": 56, "bottom": 36},
            "xAxis": {
                "type": "category",
                "data": [i["name"] for i in items],
                "axisLabel": {"rotate": 45 if len(items) > 8 else 0},
            },
            "yAxis": {"type": "value", "name": "项目数", "minInterval": 1},
            "series": [
                {
                    "type": "line",
                    "smooth": True,
                    "areaStyle": {},
                    "data": [i["value"] for i in items],
                }
            ],
        }

    @staticmethod
    def _connect():
        """连接参数与 to_postgresql.py 同源（POSTGRES_* 环境变量，均有默认值）。"""
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "")
        dbname = os.getenv("POSTGRES_DB", "postgres")
        try:
            return psycopg2.connect(host=host, port=port, user=user, password=password,
                                    dbname=dbname, connect_timeout=5)
        except Exception as e:  # noqa: BLE001 —— 连接失败给出可操作的提示
            raise RuntimeError(
                f"PostgreSQL 连接失败（{host}:{port}, db={dbname}, user={user}）: {e}。"
                "提示：确认服务已启动并在 .env 配置 POSTGRES_HOST/PORT/USER/PASSWORD/DB，"
                "数据未导入时先运行 uv run python src/database/to_postgresql.py"
            ) from e


# ── 4. 联网搜索（Tavily）───────────────────────────────────────────────────


class WebSearchArgs(ToolArgs):
    query: str = Field(description="搜索关键词或查询句")
    max_results: int = Field(default=5, ge=1, le=8, description="返回条数，默认 5")


class SearchWebTool(BaseTool):
    name = "search_web"
    description = (
        "联网搜索（Tavily）。用户开启联网搜索时应调用至少一个联网工具（本工具或"
        " search_web_exa）：与本地检索工具配合——先完成本地检索，再联网获取最新网页信息"
        "（公告/法规更新、本地语料外的主题），综合两类结果回答。"
        "返回：标题、网址、内容摘要、相关性评分。"
    )
    args_model = WebSearchArgs
    source_kind = "web"
    source_title_key = "title"
    empty_hint = "可换更具体或更宽泛的搜索词重试；主题属本地语料范围时也可改用本地工具。"

    def run(self, args: WebSearchArgs) -> dict[str, Any]:
        try:
            results = web_search(args.query, args.max_results)
        except NotConfigured as e:
            return {"error": str(e)}
        return {"matches": results}


# ── 注册表（Agent 类从这里取已注册工具）────────────────────────────────────

_BUILTIN_TOOLS: list[BaseTool] = [
    SearchBiddingKnowledgeTool(),
    SearchKnowledgeGraphTool(),
    SearchPostgresqlTool(),
    SearchGraphQueryTool(),
    SearchWebTool(),
    AskUserTool(),
]

# Exa MCP 需配置密钥才注册：未配置时不占工具列表，避免模型选到一个必然报错的工具
if get_settings().exa_api_key:
    _BUILTIN_TOOLS.append(ExaWebSearchTool())

TOOL_REGISTRY: dict[str, BaseTool] = {t.name: t for t in _BUILTIN_TOOLS}

# 联网类工具：Agent 按请求开关（前端"联网搜索"）决定是否加入可调用集合
WEB_TOOLS = frozenset(name for name in TOOL_REGISTRY if name in {"search_web", "search_web_exa"})
