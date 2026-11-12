"""会话记忆：历史问答 → LLM 消息列表，旧组滚动压缩为摘要（历史消息定期压缩）。

组装结构（按时间序，全部塞进 messages 后再接当前问题）：
  [要点摘要(system)] + [滑出窗口但未压缩的组(逐字)] + [最近 N 组(逐字)]

"定期"的实现：最近 HISTORY_WINDOW 组逐字保留；更早的组攒够 COMPRESS_MIN_BATCH 组
才与旧摘要合并再压一次（约每 3 个新问题触发，控制摘要 LLM 调用频率），不足一批的
"窗口外尾巴"先逐字顶着，下批一起压——上下文既完整又有界。

摘要按会话持久化（session_memory 表），覆盖边界用 qa_record.id（upto_qa_id）标记，
增量推进、重复压缩覆盖。摘要生成失败绝不阻断问答：退化为旧摘要+逐字的机械拼接。

压缩提示词按本项目的翻车案例设计（"您共查询了 5 个省"漏掉最早一个）：实体清单
（查过哪些省/企业/项目）必须逐条保留——这正是长对话里最容易被截断丢掉的部分。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from rag_agent.clients.llm_factory import get_llm_client
from rag_agent.config import get_settings
from rag_agent.store import get_session_memory, get_session_records, save_session_memory

logger = logging.getLogger(__name__)

HISTORY_WINDOW = 4  # 最近 N 组问答逐字保留
COMPRESS_MIN_BATCH = 3  # 滑出窗口的组攒够 N 组才压一次
ANSWER_CLIP = 1500  # 逐字保留时单条历史回答的截断（上下文预算）
SUMMARY_CLIP = 800  # 摘要长度上限

# 同一会话的后台压缩去重：一次请求触发一次，压缩完成前不重复起线程
_inflight: set[tuple[int, str]] = set()
_inflight_lock = threading.Lock()

_SUMMARY_SYSTEM = (
    "你是对话摘要器。把旧摘要与新增对话片段合并为一份要点摘要，供问答助手延续上下文。"
    "必须保留：用户查询或提及过的实体清单（省份、企业、项目、法规名等，逐条列出）、"
    "每个问题的核心结论与关键数字、用户做过的纠正与表达过的偏好、尚未回答的追问意图。"
    "舍弃：寒暄、重复表述、检索过程描述。直接输出摘要纯文本，不超过 500 字。"
)


def _clip(text: str, n: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[:n] + "…（已截断）"


def _verbatim(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """问答行 → 逐字 user/assistant 消息对。"""
    out: list[dict[str, str]] = []
    for r in rows:
        out.append({"role": "user", "content": r["question"]})
        out.append({"role": "assistant", "content": _clip(r["answer"] or "（该回答未成功生成）", ANSWER_CLIP)})
    return out


def _compress(prev_summary: str, rows: list[dict[str, Any]]) -> str:
    """旧摘要 + 滑出窗口的问答组 → 新摘要；失败时机械拼接兜底，绝不断档。"""
    convo = "\n".join(f"问：{r['question']}\n答：{(r['answer'] or '（未生成）')[:600]}" for r in rows)
    prev = f"【旧摘要】\n{prev_summary}\n\n" if prev_summary else ""
    try:
        s = get_settings()
        resp = get_llm_client().chat(
            [
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": f"{prev}【新增对话片段】\n{convo}"},
            ],
            model=s.llm_tool_model or s.llm_model,
            temperature=0.2,
            timeout=30,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text:
            return _clip(text, SUMMARY_CLIP)
    except Exception:  # noqa: BLE001 —— 摘要只是优化，任何失败都走兜底拼接
        pass
    half = SUMMARY_CLIP // 2
    return _clip(f"{prev_summary}\n{convo}", SUMMARY_CLIP) if len(prev_summary) < half else (
        _clip(prev_summary, half) + "\n" + _clip(convo, half)
    )


def _spawn_compress(
    user_id: int, session_id: str, prev_summary: str, rows: list[dict[str, Any]]
) -> None:
    """后台压缩：不阻塞本次请求，下次提问即可用上新摘要。

    压缩原本在请求路径上同步执行，用户点发送后要先等一次 LLM 往返（~1.5s）。
    改为后台线程后，本次仍把滑出窗口的问答逐字带上（信息不丢），摘要留给下次用。
    """
    key = (user_id, session_id)
    with _inflight_lock:
        if key in _inflight:
            return
        _inflight.add(key)

    def _work() -> None:
        try:
            summary = _compress(prev_summary, rows)
            save_session_memory(user_id, session_id, summary, rows[-1]["id"])
        except Exception:  # noqa: BLE001 —— 后台失败只影响下次能否用摘要，不能影响主流程
            logger.warning("会话摘要后台压缩失败 session=%s", session_id, exc_info=True)
        finally:
            with _inflight_lock:
                _inflight.discard(key)

    threading.Thread(target=_work, daemon=True, name="mem-compress").start()


def build_chat_history(user_id: int, session_id: str, before_qa_id: int) -> list[dict[str, str]]:
    """会话历史 → LLM 消息（旧组=摘要、近组=逐字）；before_qa_id 排除本次刚落库的问题。"""
    rows = [r for r in get_session_records(user_id, session_id) if r["id"] < before_qa_id]
    if not rows:
        return []
    if len(rows) <= HISTORY_WINDOW:
        return _verbatim(rows)

    recent = rows[-HISTORY_WINDOW:]
    mem = get_session_memory(user_id, session_id) or {}
    prev_summary = mem.get("summary") or ""
    upto = int(mem.get("upto_qa_id") or 0)
    stale = [r for r in rows[:-HISTORY_WINDOW] if r["id"] > upto]

    # 压缩丢到后台，本次先用旧摘要 + 逐字拼接顶上；压缩完成前 stale 会短暂累积
    if len(stale) >= COMPRESS_MIN_BATCH:
        _spawn_compress(user_id, session_id, prev_summary, stale)

    messages: list[dict[str, str]] = []
    if prev_summary:
        messages.append(
            {"role": "system", "content": f"以下是本会话此前对话的要点摘要（细节以最近对话为准）：\n{prev_summary}"}
        )
    messages += _verbatim(stale)
    messages += _verbatim(recent)
    return messages
