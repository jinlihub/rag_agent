"""工具层冒烟测试：Pydantic Schema 生成、参数校验、容错折叠、Agent 集成与真实执行。

用法: uv run python scripts/tools_smoke_test.py          # 结构断言 + 真实工具执行
      uv run python scripts/tools_smoke_test.py --dry   # 只跑结构断言，不连库/不调模型
"""

from __future__ import annotations

import sys

from rag_agent.agent.agent import Agent
from rag_agent.tools import TOOL_REGISTRY, WEB_TOOLS, BaseTool, collect_sources

_PASS = 0


def ok(cond: bool, label: str) -> None:
    global _PASS
    if not cond:
        raise AssertionError(label)
    _PASS += 1
    print(f"  ✓ {label}")


def struct_tests() -> None:
    print("── 结构断言 ──")
    base_tools = {"search_bidding_knowledge", "search_knowledge_graph", "search_postgresql",
                  "graph_query", "search_web", "ask_user"}
    exa_on = "search_web_exa" in TOOL_REGISTRY  # 配了 EXA_API_KEY 才会注册
    ok(set(TOOL_REGISTRY) == base_tools | ({"search_web_exa"} if exa_on else set()),
       f"注册表 = 6 个基础工具{' + Exa' if exa_on else ''}")
    ok(WEB_TOOLS == frozenset({"search_web"} | ({"search_web_exa"} if exa_on else set())),
       "WEB_TOOLS 覆盖全部联网工具")

    if exa_on:
        exa = TOOL_REGISTRY["search_web_exa"].openai_schema["function"]
        ok(set(exa["parameters"]["properties"]) == {"query", "max_results"},
           "Exa 参数来自 Pydantic 模型")

    web = TOOL_REGISTRY["search_web"].openai_schema
    fn = web["function"]
    ok(web["type"] == "function" and fn["name"] == "search_web", "search_web schema 结构")
    ok(set(fn["parameters"]["properties"]) == {"query", "max_results"}, "search_web 参数来自 Pydantic 模型")
    ok(fn["parameters"]["required"] == ["query"], "query 必填")
    ok(all("title" not in p for p in fn["parameters"]["properties"].values()), "已剥离 title 噪音")

    kb = TOOL_REGISTRY["search_bidding_knowledge"].openai_schema["function"]
    props = kb["parameters"]["properties"]
    ok(props["scope"].get("enum") == ["all", "legal", "policy", "faq"], "scope Literal → enum")
    ok(props["top_k"].get("minimum") == 1 and props["top_k"].get("maximum") == 6, "top_k 约束 ge/le")

    pg = TOOL_REGISTRY["search_postgresql"].openai_schema["function"]
    ok(pg["parameters"]["properties"]["order"].get("enum") == ["time", "amount"], "order Literal → enum")

    ask = TOOL_REGISTRY["ask_user"].openai_schema["function"]
    ok(set(ask["parameters"]["properties"]) == {"question", "options"}, "ask_user 参数来自 Pydantic 模型")
    ok(ask["parameters"]["required"] == ["question"], "ask_user question 必填")
    clarify = TOOL_REGISTRY["ask_user"].execute(
        {"question": "您指的是哪家企业？", "options": ["查询安徽A公司的中标记录", "查询安徽B公司的中标记录"]}
    )
    ok(clarify.get("clarify", {}).get("question") == "您指的是哪家企业？"
       and len(clarify["clarify"]["options"]) == 2, "ask_user.run 直接返回 clarify")

    # 校验失败折叠为可读 error；多余字段忽略
    bad = TOOL_REGISTRY["search_postgresql"].execute({"limit": 99})
    ok("参数校验失败" in bad.get("error", ""), "limit=99 → 参数校验失败")
    bad2 = TOOL_REGISTRY["search_web"].execute({})
    ok("参数校验失败" in bad2.get("error", ""), "缺 query → 参数校验失败")
    ignored = TOOL_REGISTRY["search_web"].execute({"query": "test", "hacker": 1})
    ok("error" not in ignored or "校验" not in str(ignored.get("error")), "未知字段忽略（extra=ignore）")

    # Agent 集成：关闭联网时剔除 web 工具
    agent = Agent()
    schemas_off, tools_off = agent._tool_views(allow_web=False)
    schemas_on, tools_on = agent._tool_views(allow_web=True)
    ok(len(schemas_off) == len(TOOL_REGISTRY) - len(WEB_TOOLS) and not (WEB_TOOLS & set(tools_off)),
       f"allow_web=False → 剔除 {len(WEB_TOOLS)} 个联网工具")
    ok(len(schemas_on) == len(TOOL_REGISTRY) and WEB_TOOLS <= set(tools_on),
       f"allow_web=True → {len(TOOL_REGISTRY)} 个工具")
    ok([s["function"]["name"] for s in schemas_on] == list(tools_on), "Schema 顺序与注册表一致")

    # collect_sources：item 级 kind 覆盖 + 去重 + 封顶
    kb_tool: BaseTool = TOOL_REGISTRY["search_bidding_knowledge"]
    fake = {"matches": [
        {"kind": "legal", "title": "《政府采购法》第五十二条", "score": 0.9},
        {"kind": "faq", "title": "质疑时限是多久？", "score": 0.8},
        {"kind": "legal", "title": "《政府采购法》第五十二条", "score": 0.9},  # 重复
    ]}
    sources: list[dict] = []
    collect_sources(kb_tool, fake, sources)
    ok([s["kind"] for s in sources] == ["legal", "faq"], "item 级 kind 覆盖 + 去重")

    # assess_quality：行数 + 相关性分数 → verdict
    web_tool = TOOL_REGISTRY["search_web"]
    ok(web_tool.assess_quality({"matches": []})["verdict"] == "empty", "0 行 → empty")
    ok(web_tool.assess_quality({"matches": [{"title": "t", "score": 0.9}]})["verdict"] == "ok", "高分 → ok")
    qw = web_tool.assess_quality({"matches": [{"title": "t", "score": 0.1}]})
    ok(qw["verdict"] == "weak" and "相关性偏低" in qw["hint"], "低分 → weak + 改进提示")
    ok(web_tool.assess_quality({"error": "boom"})["verdict"] == "error", "error 字段 → error")
    g_tool = TOOL_REGISTRY["search_knowledge_graph"]
    ok(g_tool.assess_quality({"entity": "x", "edges": {"wins": [{"title": "t"}]}})["verdict"] == "ok",
       "图谱按 edges 判定 ok")
    ok(g_tool.assess_quality({"entity": "x", "edges": {}})["verdict"] == "empty", "图谱空 edges → empty")
    ok(g_tool.assess_quality({"entity": "x", "edges": {}, "errors": {"wins": "db down"}})["verdict"] == "error",
       "图谱全失败 → error")


def live_tests() -> None:
    print("── 真实执行（网络/库可达时）──")
    kb = TOOL_REGISTRY["search_bidding_knowledge"].execute(
        {"query": "供应商提出质疑的时限是多少天", "scope": "legal", "top_k": 2}
    )
    if "error" in kb:
        print(f"  · 知识库检索不可用: {kb['error'][:80]}")
    else:
        kinds = {m["kind"] for m in kb["matches"]}
        ok(kinds == {"legal"}, "法条检索命中 kind=legal")
        print(f"  · 命中 {len(kb['matches'])} 条法条，top score = {kb['matches'][0]['score']}")

    graph = TOOL_REGISTRY["search_knowledge_graph"].execute({"entity": "华润", "limit": 3})
    if "error" in graph:
        print(f"  · 知识图谱不可用: {graph['error'][:80]}")
    else:
        ok("entity" in graph and ("edges" in graph or "errors" in graph),
           f"图谱逐关系容错: edges={list(graph['edges'])}, errors={list(graph.get('errors', {}))}")
        if graph.get("edges", {}).get("wins"):
            summary = graph.get("wins_summary") or {}
            ok(
                summary.get("total_wins", 0) >= len(graph["edges"]["wins"])
                and len(summary.get("top_purchasers", [])) <= 3,
                f"中标汇总: 总次数={summary.get('total_wins')}, "
                f"总金额(万元)={summary.get('total_amount_wan')}",
            )

    pg = TOOL_REGISTRY["search_postgresql"].execute({"keyword": "挖掘机", "limit": 3})
    if "error" in pg:
        print(f"  · PostgreSQL 不可用: {pg['error'][:100]}")
    else:
        ok(pg["total"] >= 0 and isinstance(pg["rows"], list), f"PG 检索 total={pg['total']}")

    if "search_web_exa" in TOOL_REGISTRY:
        exa = TOOL_REGISTRY["search_web_exa"].execute({"query": "政府采购 2025 新规", "max_results": 2})
        if "error" in exa:
            print(f"  · Exa MCP 不可用: {exa['error'][:100]}")
        else:
            ok(isinstance(exa.get("matches"), list), f"Exa MCP 返回 {len(exa['matches'])} 条结果")

    # 来源折叠走一遍真实图谱结果
    if "edges" in graph and graph["edges"]:
        gtool = TOOL_REGISTRY["search_knowledge_graph"]
        sources: list[dict] = []
        collect_sources(gtool, graph, sources)
        ok(bool(sources) and all(s["kind"] == "graph" for s in sources), "图谱结果 → 来源折叠")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    struct_tests()
    if "--dry" not in sys.argv:
        live_tests()
    print(f"\n全部通过：{_PASS} 项断言")


if __name__ == "__main__":
    main()
