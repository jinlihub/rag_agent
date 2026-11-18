"""LLM-as-judge：DeepSeek 独立评审 Agent 回答（与被评 Agent 的 GLM 不同厂商，避免自评偏差）。

评分维度（1-5 整数）：correctness 正确性 / faithfulness 忠实度 / completeness 完整性，
只输出 JSON，解析失败自动重试（最多 2 次）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI

from rag_agent.config import get_settings

_DEFAULT_BASE_URL = "https://api.deepseek.com"
# deepseek-chat 已退役（调用返回 400），当前可用的是 flash / v4-pro
_DEFAULT_MODEL = "deepseek-flash"

_SYSTEM = """你是招投标问答系统的严格评测员。依据【问题】【参考要点】【检索来源】评定【回答】的三个维度（1-5 整数）：
- correctness 正确性：陈述与参考要点/客观事实一致、无错误结论；无参考要点时按领域常识判断
- faithfulness 忠实度：结论是否由【检索来源】支撑、无来源之外编造的具体数据；无检索来源时，衡量其是否如实说明信息边界而非编造
- completeness 完整性：覆盖问题要点、不遗漏不跑题
评分纪律：宁可低分不可放水；回答与参考要点矛盾时 correctness ≤ 2。
只输出 JSON：{"correctness": 整数, "faithfulness": 整数, "completeness": 整数, "comment": "一句话理由"}"""


def make_judge_client() -> tuple[OpenAI, str]:
    """DeepSeek 评审客户端 → (client, model)；未配置 key 抛 RuntimeError。"""
    s = get_settings()
    if not s.deepseek_api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY，LLM 评审不可用（--no-judge 可跳过打分）")
    return OpenAI(api_key=s.deepseek_api_key, base_url=s.deepseek_base_url or _DEFAULT_BASE_URL), _DEFAULT_MODEL


def _parse_json(text: str) -> dict[str, Any]:
    """宽松解析：直接 json.loads，失败则截取首个 {...} 块。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def judge_answer(
    client: OpenAI,
    model: str,
    question: str,
    reference: str,
    sources: list[str],
    answer: str,
) -> dict[str, Any]:
    """评一个用例 → {"correctness": int, "faithfulness": int, "completeness": int, "comment": str}。"""
    parts = [f"【问题】{question}"]
    parts.append(f"【参考要点】{reference or '（无，按领域常识判断）'}")
    parts.append("【检索来源】" + ("\n".join(f"- {t}" for t in sources[:10]) or "（无）"))
    parts.append(f"【回答】\n{answer[:4000]}")
    last_err: Exception | None = None
    for _ in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            scores = _parse_json(resp.choices[0].message.content or "")
            return {
                "correctness": int(scores.get("correctness", 0)),
                "faithfulness": int(scores.get("faithfulness", 0)),
                "completeness": int(scores.get("completeness", 0)),
                "comment": str(scores.get("comment", ""))[:200],
            }
        except Exception as e:  # noqa: BLE001 —— 网络/解析失败重试
            last_err = e
    raise RuntimeError(f"评审失败: {last_err}")


# ── RAGAS 口径三维评审（0~1）────────────────────────────────────────────
# run_eval 的三维是 1-5 分、偏「答案好不好」；这里按 RAGAS 口径改成 0~1，
# 分别看「有没有编造（faithfulness）/ 切不切题（relevancy）/ 检索资料够不够（recall）」，
# 用于综合评分报告。单个维度解析失败记 None，不拖累其他维度。

RAG_DIMENSIONS = ("faithfulness", "relevancy", "recall")

_RAG_SYSTEM = """你是招投标问答系统的严格评测员，按 RAGAS 口径给【回答】打三个 0~1 的分（保留两位小数）：

- faithfulness 忠实度：回答中的事实性断言是否都能被【检索来源】支撑。出现来源之外编造的具体数字、
  条款号、项目名、企业名时显著扣分；没有来源却如实说明「资料不足」不扣分，编造则记 0。
- relevancy 相关度：回答是否直接回应【问题】——切题、具体、不跑题，不用套话搪塞。
- recall 召回覆盖：只看【检索来源】——它是否包含回答该问题所需的关键信息（对照【参考要点】）。
  来源完全不含所需信息记 0.00，覆盖全部要点记 1.00，只覆盖一部分给中间分。

评分纪律：宁可低分不可放水。只输出 JSON：
{"faithfulness": 0.00, "relevancy": 0.00, "recall": 0.00, "comment": "一句话理由"}"""


def _score01(value: Any) -> float | None:
    """评审返回值 → 0~1 小数；不可解析或越界返回 None（该维度不计入有效数）。

    模型偶尔不守 0~1 的约定而给 1-5 分，按 /5 折算而不是直接丢弃。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x > 1:
        if x > 5:
            return None
        x = x / 5
    if x < 0:
        return None
    return round(x, 2)


def judge_rag_answer(
    client: OpenAI,
    model: str,
    question: str,
    reference: str,
    context: str,
    answer: str,
) -> dict[str, Any]:
    """RAGAS 三维评审 → {"faithfulness"/"relevancy"/"recall": float|None, "comment", "error"}。

    context 传检索到原文节选（不是只有标题）——忠实度与召回都靠它判断，
    只给标题会让评审几乎无法核实，分数会虚低。
    """
    parts = [f"【问题】{question}"]
    parts.append(f"【参考要点】{reference or '（无，按领域常识判断）'}")
    parts.append(f"【检索来源】\n{context[:8000] or '（无检索来源）'}")
    parts.append(f"【回答】\n{answer[:4000]}")
    last_err: Exception | None = None
    for _ in range(3):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": _RAG_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            data = _parse_json(resp.choices[0].message.content or "")
            out: dict[str, Any] = {"comment": str(data.get("comment", ""))[:200], "error": ""}
            for dim in RAG_DIMENSIONS:
                out[dim] = _score01(data.get(dim))
            return out
        except Exception as e:  # noqa: BLE001 —— 网络/解析失败重试
            last_err = e
    return {
        **{dim: None for dim in RAG_DIMENSIONS},
        "comment": "",
        "error": f"评审失败: {last_err}"[:200],
    }
