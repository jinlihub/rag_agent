"""Agent：RAG 能力注册为工具，大模型自动调用后流式作答。

用法（tools/rag_tools.py 已把 4 个检索工具批量注册进 TOOL_REGISTRY）：
    agent = Agent()
    for event in agent.run_stream(question): ...

也可以在实例上继续注册自定义工具（Pydantic 模型声明参数，见 tools/base.py）：
    agent.register_tool(MySearchTool())

事件契约（API 层原样转成 SSE data 帧）：
  {"type": "status", "stage": "thinking"|"analysis"|"quality"|"tool_call"|"generating", "tool"?, "args"?, "verdict"?, "text"?}
  {"type": "delta",  "text": "..."}                最终回答的增量文本
  {"type": "reasoning", "text": "..."}             深度思考过程增量（开关开启且模型返回 reasoning_content 时）
  {"type": "sources", "items": [...]}              本次回答引用的数据来源
  {"type": "chart",  "spec": {...}}                图表（ECharts option，聚合工具从分组结果算出）
  {"type": "clarify", "question": "...", "options": ["..."]}
                                                   主动澄清（ask_user 被调用后立即结束，不生成回答）
  {"type": "timing", "stages": [{"key", "seconds", "tool"?}, ...], "total"}
                                                   各阶段耗时（秒）与总用时；key: routing|analysis|tool|generating
  {"type": "error",  "message": "..."}
  {"type": "done"}
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from rag_agent.agent.intent import (
    INTENT_CHITCHAT,
    INTENT_FAQ,
    INTENT_LABELS,
    route_intent,
)
from rag_agent.agent.prompt import (
    COMPANY_PROFILE_NUDGE,
    build_system_prompt,
    is_company_profile_question,
)
from rag_agent.clients.llm_factory import get_client_for, get_llm_client
from rag_agent.clients.model_catalog import provider_of, resolve_deep_thinking_model
from rag_agent.config import get_settings
from rag_agent.tools import WEB_TOOLS, TOOL_REGISTRY, BaseTool, collect_sources

MAX_TOOL_ROUNDS = 3  # ReAct 循环上限：Reason→Act→Observe 算一轮
ASK_USER_TOOL = "ask_user"  # 主动澄清工具：调用后立即收束，不生成回答

# 无历史时的指代兜底：小模型偶尔会把澄清写进正文而不调工具，这里用规则兜住
_UNRESOLVED_REF_RE = re.compile(
    r"^\s*(?:帮我|请|麻烦|我想|想)?\s*(?:查一下|查询|查查|查|看看|看一下|了解(?:一下)?)?\s*"
    r"(?:一下)?\s*(?:那家|这家|那个|这个|该|上述)\s*(公司|企业|单位|集团|项目|工程|标段|采购)"
)
_CLARIFY_MARKERS = ("请问您", "请提供", "请补充", "您指的是", "您想查询",
                    "需要您提供", "请您提供", "请您补充")
_PROJECT_NOUNS = {"项目", "工程", "标段", "采购"}


def _unresolved_reference_prompt(
    question: str, history: list[dict[str, str]] | None
) -> str | None:
    """无历史且问题以“那家公司/那个项目”等指代开头 → 返回固定的澄清问句。

    有历史时不走兜底：指代可能在上一轮有明确指向，交给模型结合上下文判断。
    """
    if history:
        return None
    match = _UNRESOLVED_REF_RE.match(question)
    if not match:
        return None
    if match.group(1) in _PROJECT_NOUNS:
        return "您指的是哪个项目？请补充项目名称或编号。"
    return "您指的是哪家公司？请补充公司全称或可识别的简称。"


def _thought_is_clarification(text: str) -> bool:
    """分析文本看起来是在向用户要信息（而不是准备作答）。"""
    return bool(text) and any(marker in text for marker in _CLARIFY_MARKERS)

_FINAL_NUDGE = (
    "请基于以上已检索到的结果回答用户的问题，不要再尝试任何检索或调用任何工具。"
    "若结果足以支撑回答，直接作答；"
    "若结果与问题只有部分匹配（如问“计划”但只查到“中标结果”、问“最新”但只有历史数据），"
    "应先给出这些数据并注明其局限（说明它们是什么、不是什么），再说明还缺什么——"
    "不要因为不完全匹配就直接说“未找到”；"
    "只有在结果完全无关时，才如实说明信息局限并给 1-2 条调整建议（如换关键词、开启联网搜索后重试）。"
    "禁止编造数据，禁止引用检索结果中不存在的来源。"
    "不要提及工具名称、查询过程或本条指令。"
)

# 调过工具但全程没有可用结果时的收束指令：如实告知，禁止硬答
_EMPTY_NUDGE = (
    "以上检索均未得到可用结果。请如实告知用户：基于现有数据暂时无法回答该问题，"
    "并给出 1-2 条调整建议（如换关键词、调整时间范围、开启联网搜索后重试）。"
    "禁止编造任何数据，禁止推测失败原因（不要写“数据库异常”“系统故障”“主库无法访问”）。"
    "不要提及工具名称、查询过程或本条指令。"
)

# 闲聊分支：不检索、不寒暄过度，简短回应并引导到业务问题
_CHITCHAT_NUDGE = (
    "用户这句话是寒暄、致谢或询问你的身份，无需检索任何资料，直接简短回应即可。"
    "用 1-2 句自然回应；若是问身份，说明你是「招投标信息官」，"
    "可以回答招投标法规、政策、实务与项目数据类问题。"
    "不要提及工具、检索过程或本条指令。"
)

# FAQ 分支：只依据这一次 FAQ 检索结果作答，不再触发工具循环
_FAQ_NUDGE = (
    "以上是知识库 FAQ（实务问答）的检索结果。请只依据这些结果直接回答用户问题，"
    "不要调用任何工具，不要补充结果之外的任何事实——包括项目名、企业名、金额、日期、"
    "法规名称、条款文号与条款内容，即使你确信确有其事也不得写入。"
    "若结果与问题只有部分对应，只采用能对上的内容；仍不足时如实说明「FAQ 未覆盖完整信息」，"
    "并建议用户换关键词或补充条件后重试。不要提及工具名称、检索过程或本条指令。"
)

# 有结果但部分数据源失败/不达标时的收束指令：只允许用真正检索到的内容，且不得补全来源外事实
_LIMITED_NUDGE = (
    "本轮检索存在以下问题：{issues}。\n"
    "请严格按下列规则作答：\n"
    "1. 只能使用上面工具实际返回的内容。禁止列举检索结果中不存在的项目名称、企业名称、"
    "金额、日期或条款——即使你确信确有其事，也不得写入，一律视为编造。\n"
    "2. 数据源不可用时不要推测或解释原因（不要写“数据库异常”“系统故障”“主库无法访问”），"
    "只需说明“本次未能检索到符合条件的数据”。\n"
    "3. 若检索结果与问题条件部分匹配（如问“计划”但只有“中标结果”），应先给出这些数据并注明其局限，"
    "再说明还缺什么；只有完全无关时才省略，不要因为不完全匹配就说“未找到”。\n"
    "4. 结尾给出 1-2 条可操作的调整建议（换关键词、放宽条件、开启联网搜索后重试）。\n"
    "不要提及工具名称、查询过程或本条指令。"
)


def _parse_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        args = json.loads(raw)
        return args if isinstance(args, dict) else {}
    except json.JSONDecodeError:
        return {}


class Agent:
    """把已注册的检索工具接到大模型 function calling 循环上。

    模型自己决定查什么：法规·政策·实务类问题走本地知识库（search_bidding_knowledge），
    实体关系类走知识图谱（search_knowledge_graph），项目/中标数据类走
    search_postgresql，最新信息走 search_web（联网开关开启时）。
    工具结果回填对话后进入流式作答，全程产出统一事件流。
    """

    def __init__(self, max_tool_rounds: int = MAX_TOOL_ROUNDS) -> None:
        self.max_tool_rounds = max_tool_rounds
        self._tools: dict[str, BaseTool] = dict(TOOL_REGISTRY)

    def register_tool(self, tool: BaseTool) -> None:
        """注册一个自定义工具（BaseTool 子类实例，参数用 Pydantic 模型声明）。"""
        self._tools[tool.name] = tool

    def _tool_views(self, allow_web: bool) -> tuple[list[dict[str, Any]], dict[str, BaseTool]]:
        """本轮可用的 (工具 Schema, 工具实例)；未开启联网搜索时剔除联网工具。"""
        tools = (
            self._tools
            if allow_web
            else {n: t for n, t in self._tools.items() if n not in WEB_TOOLS}
        )
        return [t.openai_schema for t in tools.values()], tools

    def run_stream(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
        allow_web: bool = False,
        answer_model: str | None = None,
        deep_thinking: bool = False,
    ) -> Iterator[dict[str, Any]]:
        client = get_llm_client()
        settings = get_settings()
        # 最终作答模型：前端"LLM 选择" > .env LLM_MODEL > 客户端默认
        base_model = answer_model or settings.llm_model or client.default_model
        model = base_model
        final_thinking = settings.llm_final_thinking
        if deep_thinking:
            # 深度思考只作用于最终作答：智谱调高 reasoning_effort，DeepSeek 切 reasoner 模型；
            # 工具轮保持轻量模型，避免每一轮检索都多等一次思考
            model = resolve_deep_thinking_model(base_model)
            final_thinking = settings.llm_deep_thinking or "enabled"
        # 工具轮换轻量模型（选工具/拼参数不需要旗舰模型）；空则回退客户端默认，再回退基础模型
        tool_model = settings.llm_tool_model or client.default_tool_model or base_model
        schemas, tools = self._tool_views(allow_web)
        messages: list[dict[str, Any]] = [{"role": "system", "content": build_system_prompt()}]
        messages += [dict(m) for m in (history or [])]
        messages.append({"role": "user", "content": question})
        sources: list[dict[str, Any]] = []
        web_called = False
        tool_called = False
        chart_emitted = False  # 聚合查询可能没有来源条目，但有图表数据，不能按“空结果”收束
        # 本轮工具失败/结果不达标的记录，收束时逐条告知模型，避免其凭记忆补全
        quality_issues: list[str] = []
        t_start = time.perf_counter()
        stages: list[dict[str, Any]] = []

        def _mark(key: str, t0: float | None, tool: str | None = None,
                  seconds: float | None = None) -> None:
            """记录一个阶段的耗时（秒）；同 key 多次出现由前端聚合展示（×N）。

            串行阶段传 t0 起算；并行执行的工具自带计时，直接传 seconds。
            """
            item: dict[str, Any] = {
                "key": key,
                "seconds": seconds if seconds is not None else round(time.perf_counter() - t0, 2),
            }
            if tool:
                item["tool"] = tool
            stages.append(item)

        try:
            # ── 阶段零：意图路由（进工具循环前判定一次）──────────────────────
            # 闲聊/纯 FAQ 不跑完整 ReAct：前者不调工具，后者只查一次 FAQ 后直接作答；
            # 其余（以及路由失败降级）走下面的完整循环。
            yield {"type": "status", "stage": "thinking"}
            t_route = time.perf_counter()
            intent = route_intent(question, client, tool_model, settings.llm_tool_thinking)
            _mark("routing", t_route)
            yield {
                "type": "status",
                "stage": "analysis",
                "text": f"意图识别：{INTENT_LABELS[intent]}",
            }

            # 无历史时的显式指代（“那家公司/那个项目”）必然没有指代对象：
            # 直接走 ask_user，避免小模型随机选择“写一段反问”或“猜一个对象去查”
            reference_prompt = _unresolved_reference_prompt(question, history)
            if reference_prompt:
                clarify_tool = self._tools.get(ASK_USER_TOOL)
                if clarify_tool is not None:
                    clarify_result = clarify_tool.execute(
                        {"question": reference_prompt, "options": []}
                    )
                    clarify = (
                        clarify_result.get("clarify")
                        if isinstance(clarify_result, dict)
                        else None
                    )
                    if isinstance(clarify, dict) and clarify.get("question"):
                        yield {
                            "type": "clarify",
                            "question": clarify["question"],
                            "options": clarify.get("options") or [],
                        }
                        return

            faq_answered = False
            if intent == INTENT_FAQ:
                faq_tool = self._tools.get("search_bidding_knowledge")
                if faq_tool is not None:
                    # scope=all：知识性问题同时查法规/政策/FAQ。只查 faq 会漏掉法规依据
                    # （FAQ 仅 83 条实务问答，法规 4954 条，多数「规则类」问题的答案在法规里）
                    faq_args: dict[str, Any] = {"query": question, "scope": "all", "top_k": 4}
                    yield {
                        "type": "status",
                        "stage": "tool_call",
                        "tool": faq_tool.name,
                        "args": faq_args,
                    }
                    t_faq = time.perf_counter()
                    result = self._execute(faq_tool.name, faq_args, tools)
                    _mark("tool", t_faq, tool=faq_tool.name)
                    quality = faq_tool.assess_quality(result)
                    if quality["verdict"] == "ok":
                        # FAQ 命中：把结果回填成一次标准工具往返，随后直接收束作答
                        collect_sources(faq_tool, result, sources)
                        messages.append(
                            {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "intent_faq",
                                        "type": "function",
                                        "function": {
                                            "name": faq_tool.name,
                                            "arguments": json.dumps(faq_args, ensure_ascii=False),
                                        },
                                    }
                                ],
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": "intent_faq",
                                "content": json.dumps(result, ensure_ascii=False),
                            }
                        )
                        faq_answered = True
                        tool_called = True
                    else:
                        # FAQ 没查到可用结果：退回完整循环，避免把可回答的问题直接判死
                        yield {
                            "type": "status",
                            "stage": "quality",
                            "tool": faq_tool.name,
                            "verdict": quality["verdict"],
                            "text": quality["hint"],
                        }

            # 闲聊/FAQ 已在前置分支处理完：ReAct 轮次与联网补查一并跳过
            skip_tools = intent == INTENT_CHITCHAT or faq_answered

            # ── 阶段一：ReAct 循环（Reason→Act→Observe，非流式工具轮）────────
            # 每轮模型先输出一行"分析"（已获得什么/还缺什么），再决定调用哪些工具；
            # 判定信息充分时不再调用工具，循环收束进入最终作答。
            for _ in range(0 if skip_tools else self.max_tool_rounds):
                yield {"type": "status", "stage": "thinking"}
                t_round = time.perf_counter()
                # 按工具模型所属厂商选客户端：混用智谱/DeepSeek 时各自走自己的 base_url
                resp = get_client_for(provider_of(tool_model)).chat(
                    messages,
                    model=tool_model,
                    tools=schemas,
                    temperature=0.2,
                    thinking=settings.llm_tool_thinking,
                )
                msg = resp.choices[0].message
                _mark("analysis", t_round)
                thought = (msg.content or "").strip()
                if thought:
                    yield {"type": "status", "stage": "analysis", "text": thought[:200]}
                if not msg.tool_calls:
                    # 模型把澄清写进了分析文本却没调用 ask_user：转成澄清事件，
                    # 避免再跑一次生成、把反问当正式回答输出
                    if _thought_is_clarification(thought):
                        yield {
                            "type": "clarify",
                            "question": thought.removeprefix("分析：").strip()[:300],
                            "options": [],
                        }
                        return
                    break  # 分析后判定信息充分（或无工具可再查），进入最终回答
                messages.append(
                    {
                        "role": "assistant",
                        "content": thought,
                        "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                    }
                )
                # 模型一轮可能返回多个 tool_calls：先统一发事件，再按需并行执行
                calls: list[tuple[Any, str, dict[str, Any]]] = []
                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = _parse_args(tc.function.arguments)
                    if name in WEB_TOOLS:  # Tavily 或 Exa 任一联网检索都算已联网
                        web_called = True
                    # ask_user 不是检索：不向前端播报“正在查询工具”
                    if name != ASK_USER_TOOL:
                        yield {"type": "status", "stage": "tool_call", "tool": name, "args": args}
                    calls.append((tc, name, args))

                # 主动澄清：一旦调用 ask_user，立即把澄清问题交给前端并结束本轮，
                # 不执行同轮其它工具，也不进入最终生成（前端渲染成带快捷选项的气泡）
                clarify_call = next((c for c in calls if c[1] == ASK_USER_TOOL), None)
                if clarify_call is not None:
                    clarify_result = self._execute(ASK_USER_TOOL, clarify_call[2], tools)
                    clarify = (
                        clarify_result.get("clarify")
                        if isinstance(clarify_result, dict)
                        else None
                    )
                    if isinstance(clarify, dict):
                        question = str(clarify.get("question") or "").strip()
                        raw_options = clarify.get("options")
                        options = (
                            [str(o).strip() for o in raw_options if str(o).strip()]
                            if isinstance(raw_options, list)
                            else []
                        )
                        if question:
                            yield {"type": "clarify", "question": question, "options": options}
                            return

                tool_called = True

                def _run_one(call: tuple[Any, str, dict[str, Any]]) -> dict[str, Any]:
                    """执行单个工具并自带计时（并行时各工具耗时独立，供前端分别展示）。"""
                    _tc, _name, _args = call
                    t0 = time.perf_counter()
                    res = self._execute(_name, _args, tools)
                    return {"result": res, "seconds": round(time.perf_counter() - t0, 2)}

                # 单工具保持原有串行语义；多工具并行，省掉逐个等待的网络往返
                if len(calls) > 1:
                    with ThreadPoolExecutor(max_workers=min(len(calls), 4)) as pool:
                        outs = list(pool.map(_run_one, calls))
                else:
                    outs = [_run_one(calls[0])]

                for (tc, name, _args), out in zip(calls, outs):
                    result = out["result"]
                    _mark("tool", None, tool=name, seconds=out["seconds"])
                    tool = tools.get(name)
                    if tool is not None:
                        # 结果质量检查（行数/相关性分数）：不达标时事件通知前端，
                        # 并把质量结论并入回填消息，驱动下一轮换工具/换参数
                        quality = tool.assess_quality(result)
                        if quality["verdict"] != "ok":
                            yield {
                                "type": "status",
                                "stage": "quality",
                                "tool": name,
                                "verdict": quality["verdict"],
                                "text": quality["hint"],
                            }
                            result = {**result, "quality": quality}
                            quality_issues.append(f"{name}（{quality['verdict']}：{quality['hint']}）")
                        collect_sources(tool, result, sources)
                    # 聚合工具会附带代码生成的 ECharts spec；前端负责校验与渲染
                    chart = result.get("chart") if isinstance(result, dict) else None
                    if isinstance(chart, dict):
                        chart_emitted = True
                        yield {"type": "chart", "spec": chart}
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )

            # ── 联网开启而模型未联网：强制补一次联网检索，保证"本地+联网"双源作答 ──
            # 优先 Tavily；未配置 Tavily 时退回 Exa；两者都不可用则跳过（收束时如实告知）
            candidates = [
                n
                for n, key in (("search_web", settings.tavily_api_key), ("search_web_exa", settings.exa_api_key))
                if key
            ]
            forced_name = next((n for n in candidates if n in tools), None)
            if allow_web and not skip_tools and not web_called and forced_name:
                forced_call_id = f"forced_{forced_name}"
                forced_args = {"query": question}
                yield {"type": "status", "stage": "tool_call", "tool": forced_name, "args": forced_args}
                t_tool = time.perf_counter()
                result = self._execute(forced_name, forced_args, tools)
                _mark("tool", t_tool, tool=forced_name)
                web_tool = tools.get(forced_name)
                if web_tool is not None:
                    collect_sources(web_tool, result, sources)
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": forced_call_id,
                                "type": "function",
                                "function": {
                                    "name": forced_name,
                                    "arguments": json.dumps(forced_args, ensure_ascii=False),
                                },
                            }
                        ],
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": forced_call_id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            # ── 阶段二：最终回答（流式，不带工具，保证收束到用户可见的回答）──
            # 企业画像问题无论结果完整与否，都追加四节模板；数据缺失由模板要求逐节说明
            profile_question = is_company_profile_question(question)
            if intent == INTENT_CHITCHAT:
                messages.append({"role": "user", "content": _CHITCHAT_NUDGE})
            elif faq_answered:
                messages.append({"role": "user", "content": _FAQ_NUDGE})
            elif tool_called and not sources and not chart_emitted:
                # 调过工具但颗粒无收：明确告知用户并给建议，而不是拿空结果硬答
                messages.append({"role": "user", "content": _EMPTY_NUDGE})
            elif quality_issues:
                # 有结果但存在失败/不达标的数据源：只允许用真实检索到的内容，禁止补全来源外事实
                nudge = _LIMITED_NUDGE.format(issues="；".join(quality_issues))
                if profile_question:
                    nudge += "\n\n" + COMPANY_PROFILE_NUDGE
                messages.append({"role": "user", "content": nudge})
            else:
                messages.append(
                    {
                        "role": "user",
                        "content": COMPANY_PROFILE_NUDGE if profile_question else _FINAL_NUDGE,
                    }
                )
            yield {"type": "sources", "items": sources}
            yield {"type": "status", "stage": "generating"}
            t_gen = time.perf_counter()
            # 作答模型可能来自另一家厂商（前端下拉可选），同样按 provider 路由
            stream = get_client_for(provider_of(model)).chat_stream(
                messages,
                model=model,
                temperature=0.3,
                thinking=final_thinking,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None:
                    continue
                # 深度思考模型会先流式返回 reasoning_content，再返回正式回答；
                # 前端把它折叠成可展开的「思考过程」，不混入最终答案
                reasoning = (
                    getattr(delta, "reasoning_content", None)
                    or getattr(delta, "reasoning", None)
                )
                if reasoning:
                    yield {"type": "reasoning", "text": reasoning}
                if delta.content:
                    yield {"type": "delta", "text": delta.content}
            _mark("generating", t_gen)
            # 阶段耗时汇总：意图分析 / 各工具执行 / 最终生成（历史构建耗时由 API 层并入）
            yield {
                "type": "timing",
                "stages": stages,
                "total": round(time.perf_counter() - t_start, 2),
            }
        except Exception as e:  # noqa: BLE001 —— 任何异常都转成 error 事件，不让流硬断
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}

    def _execute(
        self,
        name: str,
        args: dict[str, Any],
        tools: dict[str, BaseTool] | None = None,
    ) -> dict[str, Any]:
        """执行已注册工具；参数校验与异常折叠在 BaseTool.execute 内统一处理。"""
        tool = (tools or self._tools).get(name)
        if tool is None:
            if name in WEB_TOOLS:
                # 联网开关关闭时被裁剪：明确告知模型原因，避免其反复尝试或凭记忆硬答
                return {"error": "联网搜索未开启（用户未打开联网开关）。请只用本地工具检索回答，或如实说明信息局限。"}
            return {"error": f"未知工具: {name}"}
        return tool.execute(args)
