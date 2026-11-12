"""混合检索融合：dense/sparse 两路结果按问题类型加权 RRF。

问题类型判定用规则（关键词正则），不调模型——检索工具轮每轮都发生，规则毫秒级
且可解释；判错的代价只是权重略偏，不至于检索失败。

RRF 公式 score = Σ w_i / (k + rank_i)。k 控制排名深度的衰减：
  - 法规类：关键词命中通常就在头部，k 取小（30）放大头部差距，权重偏 sparse
    （法名/条款号/术语是强特征，"质疑""异议"这类词 BM25 精确命中远比语义近似可靠）；
  - 概念类：语义相关的块往往排得深（问法与原文措辞差异大），k 取大（80）抹平
    头部效应，权重偏 dense；
  - 通用：k=60（文献默认值），权重近似均衡略偏 dense。
融合分归一到 0~1（除以最大值），供重排关闭时前端"相关性 %"展示，也保持
"重排失败回退融合序"链路下分数仍可读。
"""

from __future__ import annotations

import re
from typing import Any

# 法规/程序类强特征：出现即按法规类处理
_LEGAL_RE = re.compile(
    r"(?<![方做想说不算])法"  # "方法/做法/想法/说法/算 法" 等误报排除；办法单独列
    r"|条例|办法|规章|条款|第[一二三四五六七八九十百\d]{1,4}条"
    r"|依据|时限|期限|日内|个工作日|质疑|异议|投诉|废标|流标"
    r"|保证金|评标|开标|中标通知|资格审查|处罚|罚款"
)
# 概念解释类特征
_CONCEPT_RE = re.compile(
    r"什么是|是什么|什么意思|含义|定义|概念|指的是|为什么|为何|如何理解|区别|差异|对比|通俗"
)

# 问题类型 → RRF 参数（k 越小头部排名权重越大）
_PROFILES: dict[str, dict[str, Any]] = {
    "legal": {"k": 30, "dense": 0.4, "sparse": 0.6},
    "conceptual": {"k": 80, "dense": 0.7, "sparse": 0.3},
    "general": {"k": 60, "dense": 0.55, "sparse": 0.45},
}


def classify_query(query: str) -> str:
    """legal | conceptual | general：法规/程序特征优先（命中即强信号）。"""
    if _LEGAL_RE.search(query):
        return "legal"
    if _CONCEPT_RE.search(query):
        return "conceptual"
    return "general"


def profile_for(query: str) -> dict[str, Any]:
    """查询 → 融合参数（含判定结果，供结果回显与调试）。"""
    kind = classify_query(query)
    return {"kind": kind, **_PROFILES[kind]}


def rrf_fuse(rankings: list[tuple[list[dict[str, Any]], float]], k: int) -> list[dict[str, Any]]:
    """多路召回 RRF 融合。

    rankings: [(该路结果按相关度降序, 该路权重)]；两路的 dict 须带同一行号键 "row"
    （dense/sparse 均产自行号），据此去重合并——同一块被两路同时召回时得分叠加，
    这正是 RRF 的价值所在。返回按融合分降序，score 归一到 0~1。
    """
    scores: dict[int, float] = {}
    origin: dict[int, dict[str, Any]] = {}
    for items, weight in rankings:
        for rank, item in enumerate(items, start=1):
            row = item.get("row")
            if row is None:
                continue
            scores[row] = scores.get(row, 0.0) + weight / (k + rank)
            origin.setdefault(row, item)
    if not scores:
        return []
    peak = max(scores.values())
    return [
        {**origin[row], "score": round(scores[row] / peak, 3)}
        for row in sorted(scores, key=lambda r: (-scores[r], r))
    ]
