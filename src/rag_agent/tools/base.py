"""工具基类：Pydantic 模型驱动的工具定义、Schema 生成与执行分发。

每个工具三件套：
  1. 参数模型（ToolArgs 子类）——字段即参数，类型/范围/默认值/描述直接写进模型；
  2. BaseTool 子类——声明 name / description / args_model，实现 run()；
  3. OpenAI function calling 的 JSON Schema 由参数模型自动生成（model_json_schema），
     无需再手写维护 tools 列表。

execute() 统一做两层容错：参数校验失败、执行异常都折叠成 {"error": ...}，
让模型读到可读错误后自我纠正，而不是让整条对话流断掉。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from rag_agent.retrieval.vector_store import IndexNotBuilt


class ToolArgs(BaseModel):
    """工具参数基类：所有工具参数都用 Pydantic 模型声明。"""


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """model_json_schema() → OpenAI function calling 的 parameters：去掉 title/$defs 噪音。"""
    schema.pop("title", None)
    schema.pop("$defs", None)  # 扁平参数模型没有嵌套定义块，直接丢弃
    for prop in (schema.get("properties") or {}).values():
        prop.pop("title", None)
    return schema


def _format_validation_error(e: ValidationError) -> str:
    """校验错误压成一行可读文本，随 {"error": ...} 回给模型。"""
    parts = [
        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
        for err in e.errors(include_url=False)
    ]
    text = "; ".join(parts)
    return text if len(text) <= 300 else text[:300] + "…"


class BaseTool(ABC):
    """Pydantic 模型驱动的工具基类。

    子类只需声明 name / description / args_model 并实现 run(args)；
    Schema 生成、参数校验、异常折叠都由基类统一处理。
    """

    name: str
    description: str
    args_model: type[ToolArgs]
    # 工具结果进"参考来源"面板时的 kind 标签与标题字段
    source_kind: str = ""
    source_title_key: str = "title"

    @abstractmethod
    def run(self, args: ToolArgs) -> dict[str, Any]:
        """执行工具（参数已通过 args_model 校验）。"""

    @property
    def openai_schema(self) -> dict[str, Any]:
        """OpenAI function calling 定义，从 args_model 自动生成。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _clean_schema(self.args_model.model_json_schema()),
            },
        }

    def execute(self, raw_args: dict[str, Any] | None) -> dict[str, Any]:
        """校验参数并执行；任何异常都折叠成 {"error": ...}。"""
        try:
            args = self.args_model.model_validate(raw_args or {})
        except ValidationError as e:
            return {"error": f"参数校验失败: {_format_validation_error(e)}"}
        try:
            return self.run(args)
        except IndexNotBuilt as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001 —— 对模型隐藏内部细节，只回传可读错误
            return {"error": f"工具执行失败: {type(e).__name__}: {e}"}

    def source_items(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        """工具结果 → 参与"参考来源"折叠的条目列表（默认取 rows/matches）。"""
        return result.get("rows") or result.get("matches") or []

    # 相关性分数低于该值视为"弱结果"（重排 LLM 打分 0/1 二值，Tavily/向量余弦 0~1）
    WEAK_SCORE = 0.35
    # 空结果时给模型的换策略建议（子类按数据源覆盖）
    empty_hint = "换关键词或放宽筛选条件重试；仍无结果就如实告知用户。"

    def assess_quality(self, result: dict[str, Any]) -> dict[str, Any]:
        """结果质量检查（行数 + 相关性分数）→ {"verdict": ok|empty|weak|error, "hint": 改进建议}。

        verdict 非 ok 时 agent 把结论回填给模型，驱动下一轮换工具/换参数；
        全部落空则收束时如实告知用户，而不是拿着空结果硬答。
        """
        if isinstance(result.get("error"), str):
            return {"verdict": "error", "hint": f"调用失败（{result['error'][:120]}）。可换其他工具或方式重试。"}
        rows = self.source_items(result)
        if not rows:
            return {"verdict": "empty", "hint": self.empty_hint}
        scores = [s for r in rows if isinstance((s := r.get("score")), (int, float))]
        if scores and max(scores) < self.WEAK_SCORE:
            return {"verdict": "weak", "hint": f"结果相关性偏低（最高 {max(scores):.2f}）。{self.empty_hint}"}
        return {"verdict": "ok"}


def collect_sources(
    tool: BaseTool, result: dict[str, Any], sources: list[dict[str, Any]]
) -> None:
    """把工具结果折叠成"来源"引用列表（就地追加，去重，封顶 20 条）。

    条目自带 kind 字段时优先（如知识库工具一条结果可能是 legal/policy/faq）。
    """
    seen = {(s.get("kind"), s.get("title")) for s in sources}
    for item in tool.source_items(result)[:5]:
        title = item.get(tool.source_title_key)
        if not title:
            continue
        score = item.get("score")
        if isinstance(score, (int, float)) and score < tool.WEAK_SCORE:
            continue  # 低于弱结果阈值的条目是检索噪声，不进参考来源
        kind = item.get("kind") or tool.source_kind
        if (kind, title) in seen:
            continue
        seen.add((kind, title))
        brief = {
            k: item.get(k)
            for k in ("publish_time", "award_time", "award_amount_wan", "province", "city",
                      "law_type", "score", "url", "relation")
            if item.get(k) is not None
        }
        sources.append({"kind": kind, "title": title, **brief})
    del sources[20:]
