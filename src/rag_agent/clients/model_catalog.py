"""可选回答模型目录：前端「LLM 选择」按钮的数据源 + 请求侧合法性校验。

清单：内置按厂商分组的候选表，可被 .env `LLM_MODEL_CHOICES`（`id:标签:说明` 逗号分隔）覆盖；
配置里的 LLM_MODEL 永远在列（作为默认项）。

可用性：候选模型逐个用 1-token 请求探活并缓存（默认 5 分钟）。这一步是必需的——
按资源包计费的账户在余额耗尽后，除免费档外所有模型都会 429，列出一个"选了必然失败"
的模型不如直接告诉他为什么不可选，前端据此置灰并显示原因。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from rag_agent.clients.llm_factory import get_client_for, get_llm_client
from rag_agent.config import get_settings

_PROBE_TTL = 300.0  # 探活结果有效期（秒）
_PROBE_TIMEOUT = 20.0  # 单模型探活超时（繁忙模型排队可能更久）
_PROBE_PROMPT = "回复一个字"


@dataclass(frozen=True)
class ChatModel:
    """一个候选模型（前端下拉项）。"""

    id: str
    label: str  # 短标签，如"默认"
    hint: str  # 说明，如下拉项副标题
    provider: str = "zai"  # 所属厂商：决定用哪家的 base_url 与 Key
    is_default: bool = False


# 内置候选表（扁平，每项带厂商）：(provider, id, 短标签, 说明)
# 跨厂商混列——前端一次列出两家，选中后按 provider 路由到对应客户端。
# 注意：混用前需在 .env 配好各家的 Key，否则该家模型会在探活阶段被判不可用。
_BUILTIN: tuple[tuple[str, str, str, str], ...] = (
    ("zai", "glm-4.7-flashx", "默认", "快速均衡，日常问答首选"),
    ("zai", "glm-4.6", "更强", "复杂推理更稳，延迟略高"),
    ("zai", "glm-4.5-air", "轻量", "低成本，简短问答够用"),
    ("zai", "glm-4-flash", "免费", "基础档，额度稳定"),
    ("deepseek", "deepseek-flash", "DeepSeek", "V4.1 Flash，响应快、成本低"),
    ("deepseek", "deepseek-v4-pro", "DeepSeek 强", "V4 Pro，复杂推理更稳"),
)

_lock = threading.Lock()
_availability: dict[str, dict[str, Any]] = {}  # id → {available, reason, checked_at}
_probe_seq: tuple[str, ...] = ()  # 当前在探的模型 id 集合，避免重复起线程
_probe_thread: threading.Thread | None = None


def _parse_choices(raw: str) -> list[tuple[str | None, str, str, str]]:
    """`[provider:]id:标签:说明, ...` → [(provider|None, id, label, hint)]。

    段数决定含义，避免歧义：
      3 段 `id:标签:说明`        → provider 取 .env LLM_PROVIDER（同厂商内换模型）
      4 段 `provider:id:标签:说明` → 显式指定厂商（跨厂商混列）
    """
    out: list[tuple[str | None, str, str, str]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split(":")]
        if len(parts) >= 4:
            provider, mid, label, hint = parts[0], parts[1], parts[2], parts[3]
        else:
            provider = None
            mid = parts[0]
            label = parts[1] if len(parts) > 1 and parts[1] else mid
            hint = parts[2] if len(parts) > 2 and parts[2] else ""
        if mid:
            out.append((provider.lower() if provider else None, mid, label, hint))
    return out


def default_model_id() -> str:
    """当前配置的默认回答模型（.env LLM_MODEL → 客户端默认）。"""
    s = get_settings()
    try:
        client = get_llm_client()
    except Exception:  # noqa: BLE001 —— 未配置时目录仍可给出 LLM_MODEL
        return s.llm_model
    return s.llm_model or client.default_model


def _entries() -> list[tuple[str, str, str, str]]:
    """全部候选：(provider, id, 短标签, 说明)。

    `LLM_MODEL_CHOICES` 覆盖内置表时，所列模型统一归当前 provider——
    该配置面向「同一家厂商内换模型」；要跨厂商请直接改内置表。
    """
    s = get_settings()
    default_provider = (s.llm_provider or "zai").strip().lower()
    raw = (s.llm_model_choices or "").strip()
    if raw:
        return [
            (p or default_provider, mid, label, hint) for p, mid, label, hint in _parse_choices(raw)
        ]
    return list(_BUILTIN)


def provider_of(model_id: str) -> str:
    """模型 id → 所属厂商；未知模型按当前 LLM_PROVIDER 处理。

    调用侧与探活都靠它选客户端——判错会用错 base_url，表现为「模型明明能用却报 401」。
    """
    for provider, mid, _, _ in _entries():
        if mid == model_id:
            return provider
    return (get_settings().llm_provider or "zai").strip().lower()


def catalog() -> list[ChatModel]:
    """候选模型清单（含默认项）。"""
    entries = _entries()
    fallback = default_model_id()
    if fallback and not any(e[1] == fallback for e in entries):
        provider = (get_settings().llm_provider or "zai").strip().lower()
        entries.insert(0, (provider, fallback, "默认", "当前配置的回答模型"))
    return [
        ChatModel(id=e[1], label=e[2], hint=e[3], provider=e[0], is_default=e[1] == fallback)
        for e in entries
    ]


def allowed_ids() -> set[str]:
    return {c.id for c in catalog()}


def resolve_answer_model(raw: str | None) -> str:
    """请求里的模型 id → 实际使用的 id；None/空取默认，非法值抛 ValueError（API 层转 400）。"""
    value = (raw or "").strip()
    if not value:
        return default_model_id()
    if value not in allowed_ids():
        raise ValueError(f"不支持的模型: {value}（可选：{'、'.join(sorted(allowed_ids()))}）")
    return value


def resolve_deep_thinking_model(base_model: str) -> str:
    """前端「深度思考」开启时的实际回答模型。

    DeepSeek Chat API 没有 thinking 透传参数，深度思考等价于换到 reasoner 模型；
    智谱等支持参数的厂商沿用当前模型，由客户端只调高思考强度。
    """
    s = get_settings()
    provider = (s.llm_provider or "zai").strip().lower()
    if provider == "deepseek":
        return s.deepseek_thinking_model or "deepseek-reasoner"
    return base_model


def _classify_error(e: Exception) -> str:
    """异常 → 用户可读的不可用原因。"""
    msg = str(e)
    for key, text in (
        ("余额不足", "账户余额不足或无可用资源包"),
        ("无可用资源包", "账户余额不足或无可用资源包"),
        ("访问量过大", "模型当前繁忙，稍后再试"),
        ("模型不存在", "模型代码不存在"),
        ("invalid_request", "请求被拒绝"),
        ("429", "触发限流"),
        ("timed out", "探测超时"),
        ("Connection", "服务连接失败"),
    ):
        if key in msg:
            return text
    return msg[:80] or type(e).__name__


def _probe_one(model_id: str) -> dict[str, Any]:
    try:
        # 按模型所属厂商取客户端：混用多家时，用错 base_url 会得到 401 而非模型本身的问题
        client = get_client_for(provider_of(model_id))
        client.chat(
            [{"role": "user", "content": _PROBE_PROMPT}],
            model=model_id,
            temperature=0.1,
            timeout=_PROBE_TIMEOUT,
            max_tokens=8,
        )
        return {"available": True, "reason": None, "checked_at": time.time()}
    except Exception as e:  # noqa: BLE001 —— 探活失败即"当前不可用"，原因归类展示
        return {"available": False, "reason": _classify_error(e), "checked_at": time.time()}


def _probe_all(ids: tuple[str, ...]) -> None:
    """串行探活（并发打同一账户容易自己触发限流，串行更准）。"""
    global _probe_thread
    try:
        for mid in ids:
            with _lock:
                _availability[mid] = _probe_one(mid)
            time.sleep(0.6)
    finally:
        with _lock:
            _probe_thread = None


def ensure_availability() -> None:
    """探活结果过期时后台起线程刷新；本次调用不阻塞（首屏先拿到 null，几秒后就绪）。"""
    global _probe_thread, _probe_seq
    ids = tuple(c.id for c in catalog())
    with _lock:
        fresh = _probe_seq == ids and _availability and all(
            (time.time() - v["checked_at"]) < _PROBE_TTL for v in _availability.values()
        )
        if fresh or _probe_thread is not None:
            return
        _probe_seq = ids
        _probe_thread = threading.Thread(target=_probe_all, args=(ids,), daemon=True)
        _probe_thread.start()


def availability_of(model_id: str) -> dict[str, Any]:
    """id → {available: bool|None, reason: str|None}；None = 尚未探测出结果。"""
    with _lock:
        entry = _availability.get(model_id)
    if entry is None:
        return {"available": None, "reason": None}
    if time.time() - entry["checked_at"] > _PROBE_TTL:
        return {"available": None, "reason": None}  # 过期当未知，避免按旧结论置灰
    return {"available": entry["available"], "reason": entry["reason"]}


def list_payload() -> dict[str, Any]:
    """GET /api/models 的响应体。"""
    ensure_availability()
    return {
        "default": default_model_id(),
        "items": [
            {"id": c.id, "label": c.label, "hint": c.hint, "provider": c.provider,
             "is_default": c.is_default, **availability_of(c.id)}
            for c in catalog()
        ],
    }
