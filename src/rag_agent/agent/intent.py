"""意图路由前置：进 ReAct 工具循环前先判定一次，简单请求不跑完整循环。

三档（其余情况一律走完整循环，宁可多查一轮，不可误判后直接作答）：

  chitchat  寒暄/致谢/告别/询问助手身份 → 不调工具，直接短答
  faq       纯知识性提问（法规/政策/实务流程，不涉及具体项目/企业/中标数据）
            → 只查一次 FAQ 知识库（scope=faq），然后直接作答
  complex   其余：项目、企业、中标结果、金额、地域清单、多轮关联、实时信息等
            → 现有完整 ReAct 循环（多工具、多轮）

判定顺序：
  1. 寒暄用正则快速判定：零成本、毫秒级，覆盖绝大多数客套话；
  2. 其余用工具轮小模型做一次单标签分类（max_tokens 很小）；
  3. 分类调用失败/超时降级为 complex —— 路由是性能优化，不能成为故障点。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

INTENT_CHITCHAT = "chitchat"
INTENT_FAQ = "faq"
INTENT_COMPLEX = "complex"

# 前端/日志用的中文标签
INTENT_LABELS = {
    INTENT_CHITCHAT: "闲聊寒暄，直接作答",
    INTENT_FAQ: "FAQ 知识问答，单次检索",
    INTENT_COMPLEX: "复杂问题，完整 ReAct 循环",
}

# ── 寒暄规则 ────────────────────────────────────────────────────────────────
# 允许"你好，你是谁""谢谢你的回答"这类组合；句子一旦带上业务内容（如"你好，查一下…"）
# 就不再整体匹配，交给模型分类，避免把真实问题误判成寒暄。
_CHITCHAT_TOKEN = (
    r"你好|您好|嗨|哈喽|哈啰|hello|hi|hey|在吗|在不在|"
    r"早上好|上午好|中午好|下午好|晚上好|晚安|再见|拜拜|"
    r"谢谢|谢谢你|多谢|感谢|辛苦了|好的|好滴|ok|okay|嗯|收到|"
    r"你是谁|你叫什么(?:名字)?|你能做什么|你会什么|你能帮我做什么|"
    r"介绍一下你自己|介绍下你自己|你是什么"
)
_CHITCHAT_RE = re.compile(
    rf"(?:(?:{_CHITCHAT_TOKEN})[呀啊呢吧哦喔哈啦了]*[，,。.!！?？、~～\s]*)+"
    rf"[您你]?(?:的?(?:回答|解答|帮助|建议))?",
    re.IGNORECASE,
)

# ── 模型分类 ────────────────────────────────────────────────────────────────
_ROUTE_PROMPT = """你是招投标问答系统的意图路由器。把用户问题归为下列三类之一，只输出一个英文标签，不要解释：
chitchat：寒暄、道谢、告别、询问助手身份/能力，或与招投标业务无关且不需要查资料的内容。
faq：招投标实务、法规、政策、流程等知识性提问。问的是"规则/时限/条件/流程/概念/怎么办"，
     答案在知识库的实务问答里，不需要查具体项目、企业、中标记录、金额或地域清单。
complex：需要查询具体项目/企业/中标结果/金额/地域清单、多步关联、对比统计、写作任务，
     或时效性要求高（近期新闻、最新政策）。
判断不确定时选 complex。

示例：
你好 -> chitchat
你是谁 -> chitchat
谢谢 -> chitchat
投标保证金最晚什么时候退 -> faq
单一来源采购需要满足什么条件 -> faq
质疑和投诉有什么区别 -> faq
合肥近半年中标的空调项目有哪些 -> complex
某某公司中标过哪些项目 -> complex
帮我对比安徽和江苏的废标率 -> complex
帮我写一封质疑函 -> complex

用户问题：{question}
标签："""

_LABEL_RE = re.compile(r"\b(chitchat|faq|complex)\b", re.IGNORECASE)


def is_chitchat(question: str) -> bool:
    """纯寒暄/致谢/问身份：正则整句匹配（零模型调用）。"""
    return bool(_CHITCHAT_RE.fullmatch(question.strip()))


def _parse_label(text: str | None) -> str:
    """从模型输出里取标签；解析不出就按 complex 处理。"""
    raw = text or ""
    m = _LABEL_RE.search(raw)
    if m:
        return m.group(1).lower()
    # 模型偶尔回中文：做一层宽松兜底，仍解析不出就按 complex（宁可多查一轮）
    if any(w in raw for w in ("寒暄", "闲聊", "问候")):
        return INTENT_CHITCHAT
    if "实务问答" in raw or "知识库" in raw:
        return INTENT_FAQ
    return INTENT_COMPLEX


def route_intent(
    question: str,
    client: Any,
    model: str,
    thinking: str | None = None,
) -> str:
    """返回 chitchat / faq / complex。

    client/model 为工具轮使用的小模型与客户端；分类只输出一个词，成本近零。
    任何异常都降级为 complex，不阻断问答主流程。
    """
    if is_chitchat(question):
        return INTENT_CHITCHAT
    try:
        resp = client.chat(
            [{"role": "user", "content": _ROUTE_PROMPT.format(question=question)}],
            model=model,
            temperature=0.0,
            thinking=thinking,
            max_tokens=64,
            timeout=8,
        )
        content = resp.choices[0].message.content
    except Exception:  # noqa: BLE001 —— 路由失败不是故障，退回完整循环即可
        logger.warning("意图路由调用失败，降级为 complex", exc_info=True)
        return INTENT_COMPLEX
    return _parse_label(content)
