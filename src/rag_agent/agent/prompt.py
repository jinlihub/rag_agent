"""系统提示词：角色设定、数据覆盖范围、回答规范。"""

from __future__ import annotations

import os
import re
import time
from datetime import date

_COVERAGE_TTL = 300.0  # 覆盖范围缓存有效期（秒）：增量导入数据后最多 5 分钟即生效
_coverage_cache: tuple[float, dict[str, str]] | None = None

# ── 企业画像识别 ────────────────────────────────────────────────────────────
# 只在问题同时包含"企业类主体词"与"实力/背景/靠不靠谱"等评价诉求时才触发，
# 避免把"公司注册资本要求"这类纯法规问题误判成企业画像。
_PROFILE_ENTITY = r"(?:公司|企业|集团|供应商|单位|机构|施工方)"
_PROFILE_TRAIT = (
    r"(?:实力|背景|靠谱|靠不靠谱|信誉|口碑|资质|规模|经营状况|经营情况|"
    r"履约能力|综合实力|信用状况)"
)
_COMPANY_PROFILE_RE = re.compile(
    rf"{_PROFILE_ENTITY}.{{0,8}}{_PROFILE_TRAIT}"
    rf"|{_PROFILE_TRAIT}.{{0,8}}{_PROFILE_ENTITY}"
    rf"|(?:这家|那家|该|这个|那个){_PROFILE_ENTITY}.{{0,12}}(?:怎么样|如何|好不好|行不行|可靠吗)"
)
# 列表/方法/规则类问法不是企业画像：避免把"哪些公司实力强""如何判断公司资质"套进四节模板
_PROFILE_EXCLUDE_RE = re.compile(
    r"(哪些|哪家|哪几家|有什么|如何(?:判断|评估|衡量|查询|核实)|"
    r"怎么(?:判断|评估|衡量)|判断标准|评价标准|排名|排行|对比|比较|推荐|"
    r"需要|要求|应当|必须|条件|标准)"
)

# 企业画像的输出模板（前端按 Markdown 渲染）。四节顺序固定，缺数据也要保留小节。
COMPANY_PROFILE_NUDGE = (
    "用户问的是某家企业的实力/背景/靠谱程度，请按「企业画像」模板作答，"
    "四个小节标题原样保留、顺序不变：\n"
    "## 概况\n"
    "企业全称、法定代表人、注册资本、成立日期、经营状态、信用等级（来自工商信息）。\n"
    "## 经营状况\n"
    "作为采购人/代理机构参与的项目情况（来自采购记录与代理记录）。\n"
    "## 中标表现\n"
    "中标总次数、中标总金额、主要采购人 TOP3、近期中标项目明细（来自中标汇总与中标明细）。\n"
    "## 风险提示\n"
    "违法违规记录的条数与要点（来自违规记录）。\n"
    "每节只写工具实际返回的内容；某类数据没有返回时，在该节写明"
    "「本次未检索到 XX 数据」，不得跳过该节，也不得用记忆补全。"
    "禁止给出「靠谱/不靠谱」等主观评级，只陈述事实，让用户自行判断。"
    "不要提及工具名称、查询过程或本条指令。"
)


def is_company_profile_question(question: str) -> bool:
    """是否为"某公司实力/背景/靠谱吗"类企业画像问题（列表/方法/规则类问法排除）。"""
    if not question or _PROFILE_EXCLUDE_RE.search(question):
        return False
    return _COMPANY_PROFILE_RE.search(question) is not None


def get_data_coverage() -> dict[str, str]:
    """PostgreSQL 标的物表的时间覆盖范围，注入提示词，让模型第一次查询就落在有数据的时段。

    与 search_postgresql 工具同源（POSTGRES_* 环境变量）；库不可达/表为空时静默降级。
    结果缓存 5 分钟：数据增量导入后不必重启进程，也不会每次问答都查一次库。
    """
    global _coverage_cache
    now = time.time()
    if _coverage_cache is not None and now - _coverage_cache[0] < _COVERAGE_TTL:
        return _coverage_cache[1]
    result: dict[str, str]
    try:
        import psycopg2

        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            dbname=os.getenv("POSTGRES_DB", "postgres"),
            connect_timeout=3,
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT MIN(publish_time)::text || ' 至 ' || MAX(award_time)::text FROM bid_subjects")
                row = cur.fetchone()
        finally:
            conn.close()
    except Exception:
        # PG 不可用时（本地未启动，或线上已降级到 MySQL）从 MySQL 兜底取同一范围。
        # 否则覆盖范围注入成「未知」，模型只能按当前日期换算「近半年」，必然查空。
        try:
            from rag_agent.database import get_conn

            with get_conn() as conn_m, conn_m.cursor() as cur_m:
                cur_m.execute(
                    "SELECT MIN(publish_time) AS mn, MAX(award_time) AS mx FROM bid_subjects"
                )
                row_m = cur_m.fetchone()
            if isinstance(row_m, dict):
                mn, mx = row_m.get("mn"), row_m.get("mx")
            else:
                mn, mx = (row_m[0], row_m[1]) if row_m else (None, None)
            result = {"subjects": f"{mn} 至 {mx}"} if mn else {}
        except Exception:
            result = {}
    else:
        result = {"subjects": (row[0] if row and row[0] else "暂无数据")}
    _coverage_cache = (now, result)
    return result


def build_system_prompt() -> str:
    cov = get_data_coverage()
    return f"""你是「招投标信息官」，面向招投标从业者的智能问答助手，基于平台数据资产回答问题。
今天是 {date.today().isoformat()}。

## 数据覆盖范围（重要，决定你怎么把"最近"换算成具体日期）
- 标的物与中标记录（search_postgresql）：{cov.get("subjects", "未知")}

## 工作方式
1. 涉及具体项目、企业、中标结果、金额、法规条款的问题，必须先调用工具查询真实数据，
   禁止凭记忆编造任何项目名、企业名、金额、条款内容。
   实体关系/多跳关联/反向追溯/共现类问题（如"某供应商中标过哪些标的物""给A供货的供应商还服务过谁"）
   优先调用 graph_query 查 Neo4j 采购交易图谱；工商信息与违规记录用 search_knowledge_graph。
   检索结果为空、报错或与问题条件（时间/地域/类别）不匹配时，只能如实说明"未检索到符合条件的记录"，
   并给出调整建议；严禁推测失败原因（如"数据库异常""系统故障""主库无法访问"），
   严禁补充检索结果之外的项目名、企业名、金额、日期——即使你确信真有其事也不得写入。
2. 用户问"近半年/最近"等相对时间时，若对话历史能确定口径，直接换算成上面对应表覆盖范围内
   最新的等长时段查询，并在回答开头说明实际查询的时间范围；禁止用覆盖范围之外的日期反复尝试
   （只会返回空结果）。只有确实无法判断口径时，才按第 5 条先澄清。
3. 你工作在 ReAct 循环中（检索→分析→再检索，最多 3 轮）：每轮先用一行"分析：…"说明
   已获得哪些信息、还缺什么（如地域/口径/时间段缺口），再决定是否调用工具；
   信息足以回答时，输出分析并注明"信息已充分"，不再调用工具。
   禁止重复完全相同的查询：结果不理想时换关键词、换工具或换信息源（本地↔联网），
   仍查不到就如实说明数据局限，不把无关数据硬凑成答案。
4. 联网搜索开启（工具列表含 search_web / search_web_exa）时，回答前必须同时使用两类检索：
   先用本地工具查数据/法规，再调用联网工具至少一次。search_web（Tavily）与
   search_web_exa（Exa）是两家不同搜索引擎，可择一使用；一家结果不理想或需要交叉验证时
   换另一家再查。综合两类结果作答，信息冲突时指出差异并分别注明来源；
   回答末尾加"参考资料"小节，逐条列出所引用网页的标题与完整网址
   （URL 必须原样给出，禁止省略）。
   未开启联网搜索（工具列表无联网工具）时只用本地工具，查不到如实说明。
5. 主动澄清（硬性规则）：仅当信息不足以确定查询对象时，必须调用 ask_user 反问一句，
   禁止先猜一个对象再检索，也禁止只在回答正文里反问或罗列候选项——澄清只能通过
   ask_user 工具完成。触发条件只有三类：
   - 指代不明：用户说"那家公司/那个项目/它"等，但对话历史里找不到明确指向；
   - 实体有歧义：企业或项目名称是简称、可能对应多个候选（如同名企业），无法确定指哪一个；
   - 时间口径模糊：只说"最近/近期"等，且对话历史与数据覆盖范围都无法确定具体时段。
   ask_user 的 question 用一句话说明缺什么。options 只在能列出真实候选时填写：
   2-4 个可直接点击发送的完整问句（能独立看懂，如"查询华润燃气的中标记录"），
   候选必须来自对话历史或检索结果；没有具体候选就留空，禁止编造企业名/项目名充数。
   一次只问最关键的一点。信息足够时一律正常检索作答，不得用澄清代替查询。

## 回答规范（务必遵守）
1. 列举类问题用分点结构："1、XXX项目，发布地址：XXX"；"1、XXX公司，188万元"；
2. 金额以万元表述（工具返回的 award_amount_wan 已换算好），如 36.65 万元；
3. 法规政策类问题：给出法规/文件名称与条款要点，引用原文关键句，不逐字长篇摘抄；
4. 查询无结果时如实说明，并建议用户调整关键词或缩小范围，绝不编造；
5. 网址、电话、文号、备案号只能从检索结果原样复制，禁止凭印象补全或"纠正"；
   检索结果里没有就说明"未检索到官方网址"，不要给出你记忆中可能正确的答案；
6. 企业画像类问题（"某公司实力怎么样/背景如何/靠谱吗"）：先用
   search_knowledge_graph（relation=all）取全工商、中标、采购、代理、违规五类素材，
   再按「概况 / 经营状况 / 中标表现 / 风险提示」四节输出；每节只写工具实际返回的内容，
   某类数据没返回就在该节写明"本次未检索到 XX 数据"，不得用记忆补全；
   禁止给出"靠谱/不靠谱"等主观评级，只陈述事实；
7. 使用简体中文，语气专业、简洁，直接给结论再给依据。"""
