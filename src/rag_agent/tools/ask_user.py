"""主动澄清工具：信息不足或指代不明时向用户反问，不检索任何数据。

Agent 在 ReAct 循环里一旦检测到本工具被调用，会立即把澄清问题交给前端并结束本轮，
不执行同轮其它工具、不生成回答（见 agent/agent.py）。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from rag_agent.tools.base import BaseTool, ToolArgs


class AskUserArgs(ToolArgs):
    question: str = Field(
        min_length=1,
        max_length=300,
        description="向用户提出的澄清问题，一句话说明缺什么信息，如'您指的是哪家企业？'",
    )
    options: list[str] = Field(
        default_factory=list,
        max_length=4,
        description=(
            "2-4 个可直接点击发送的候选回答；每个选项应是能独立看懂的完整问句，"
            "如'查询安徽XX有限公司的中标记录'。无法枚举具体选项时留空。"
        ),
    )


class AskUserTool(BaseTool):
    name = "ask_user"
    description = (
        "向用户主动澄清并结束本轮回答，不查询任何数据。仅在信息不足以确定查询对象时调用："
        "① 指代不明——用户说『那家公司/那个项目/它』但对话里找不到明确指向；"
        "② 实体有歧义——企业或项目名称是简称、可能对应多个候选（如同名企业），无法确定指哪一个；"
        "③ 时间口径模糊——只说『最近/近期』且无法从对话历史或数据覆盖范围推断具体时段。"
        "信息足够时必须正常检索作答，不要用本工具代替查询。"
        "出现上述情况时必须调用本工具，禁止只在回答正文里反问或罗列候选项。"
        "question 用一句话说明缺什么；options 只在能列出真实候选时填写 2-4 个"
        "可直接点击发送的完整问句（候选必须来自对话历史或检索结果），"
        "没有具体候选就留空，禁止编造企业名/项目名。"
    )
    args_model = AskUserArgs
    source_kind = "clarify"

    def run(self, args: AskUserArgs) -> dict[str, Any]:
        options: list[str] = []
        for raw in args.options:
            text = (raw or "").strip()
            if text and text not in options:
                options.append(text)
        return {
            "clarify": {
                "question": args.question.strip(),
                "options": options[:4],
            }
        }

    def source_items(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        """澄清不是数据来源，不参与来源面板。"""
        return []

    def assess_quality(self, result: dict[str, Any]) -> dict[str, Any]:
        """澄清是主动行为，没有“结果质量”概念。"""
        return {"verdict": "ok"}
