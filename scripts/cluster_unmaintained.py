"""未维护问题聚类 + 草稿：帮管理员批量消化问答积压（离线跑，不挂同步接口）。

流程：
  1. 拉未维护 question（--limit 只取最近 N 条，冒烟测试用）
  2. embed_texts 向量化（已 L2 归一化，点积即余弦）
  3. 余弦阈值贪心聚类：先「种子 + 归并同簇」，再按质心归并两个切碎的簇
  4. 每簇用 question + 来源标题起草一条回答，写回簇内全部记录的 answer_draft

约束：qa_record 只存了 sources（来源标题数组），没有完整检索结果。起草只能靠
问题原文与标题，prompt 里明确要求「不确定的细节不写」，不能假装读过项目数据。

簇身份 = 草稿内容相同（不新增簇表），簇 id 取簇内最小 qa_record.id；
B 端 GET /api/admin/clusters 按草稿归簇展示。

用法:
  uv run python scripts/cluster_unmaintained.py                 # 全量，阈值 0.85
  uv run python scripts/cluster_unmaintained.py --limit 5       # 只跑最近 5 条
  uv run python scripts/cluster_unmaintained.py --dry-run       # 只聚类，不起草
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from rag_agent.clients.llm_factory import get_llm_client
from rag_agent.llm import embed_texts
from rag_agent.store import list_unmaintained_qa, save_answer_drafts

DEFAULT_THRESHOLD = 0.85
MAX_SOURCE_TITLES = 20
MAX_QUESTIONS_IN_PROMPT = 10

_DRAFT_SYSTEM = """你是招投标领域的问答维护专家。管理员给你一组语义相近的用户问题，
以及这些问题记录里出现过的来源标题。请为这组问题起草一条可以共用的标准回答。

硬性要求：
1. 只写你能确定的内容。涉及具体项目、具体公司、具体金额、具体日期等细节时，
   素材里没给出的，一律不要编造；改用「需以招标文件/官方公告为准」等表述。
2. 不能假装读过项目数据：你没有完整的检索结果，只有问题原文和来源标题。
3. 回答面向普通用户：先给结论，再给依据要点；涉及时限、条件、流程时尽量列成条目。
4. 长度 200~400 字，中文；不要复述问题，不要「根据您的问题」之类的套话。
5. 多个问题关注点略有差异时，回答共同点，并在结尾用一句话覆盖差异。

直接输出回答正文，不要 Markdown 代码块，不要额外说明。"""


def greedy_cluster(vectors: np.ndarray, threshold: float) -> list[list[int]]:
    """种子 + 归并的贪心聚类，返回下标分组（不引 sklearn）。

    第一轮：按输入顺序取未分配点做种子，把所有与种子余弦 ≥ 阈值的未分配点并入；
            成员只要求与种子相似，不要求两两相似。
    第二轮：簇间质心相似度 ≥ 阈值就合并，避免相邻两个种子把同一类问题切碎。
    """
    n = len(vectors)
    if n == 0:
        return []
    assigned = np.zeros(n, dtype=bool)
    sims = vectors @ vectors.T  # 归一化向量点积 = 余弦相似度
    clusters: list[list[int]] = []
    for seed in range(n):
        if assigned[seed]:
            continue
        members = np.where(~assigned & (sims[seed] >= threshold))[0]
        assigned[members] = True
        clusters.append(members.tolist())

    merged = True
    while merged and len(clusters) > 1:
        merged = False
        centroids = np.asarray([vectors[c].mean(axis=0) for c in clusters], dtype="float32")
        norms = np.linalg.norm(centroids, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        centroids = centroids / norms
        for i in range(len(clusters)):
            if merged:
                break
            for j in range(i + 1, len(clusters)):
                if float(centroids[i] @ centroids[j]) >= threshold:
                    clusters[i].extend(clusters[j])
                    del clusters[j]
                    merged = True
                    break
    return clusters


def source_titles(sources_json: str | None) -> list[str]:
    """从 qa_record.sources（来源 JSON 数组）里取标题，去重保序。

    历史上既可能是 [{"title": ...}, ...]，也可能是 ["标题", ...]，两种都兼容。
    """
    if not sources_json:
        return []
    try:
        data = json.loads(sources_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    titles: list[str] = []
    for item in data:
        title = item.get("title") if isinstance(item, dict) else item
        if isinstance(title, str) and title.strip() and title.strip() not in titles:
            titles.append(title.strip())
    return titles


def build_draft_prompt(questions: list[str], titles: list[str]) -> str:
    shown_qs = "\n".join(f"{i}. {q}" for i, q in enumerate(questions[:MAX_QUESTIONS_IN_PROMPT], 1))
    if len(questions) > MAX_QUESTIONS_IN_PROMPT:
        shown_qs += f"\n…另有 {len(questions) - MAX_QUESTIONS_IN_PROMPT} 条相似问题"
    shown_titles = "\n".join(f"- {t}" for t in titles[:MAX_SOURCE_TITLES]) or "（无）"
    return (
        f"这组问题共 {len(questions)} 条：\n{shown_qs}\n\n"
        f"记录中出现过的来源标题：\n{shown_titles}\n\n"
        "请起草一条能覆盖这组问题的标准回答。"
    )


def draft_answer(questions: list[str], titles: list[str]) -> str:
    """调对话模型起草一条回答；失败返回空串由调用方跳过该簇。"""
    client = get_llm_client()
    resp = client.chat(
        [
            {"role": "system", "content": _DRAFT_SYSTEM},
            {"role": "user", "content": build_draft_prompt(questions, titles)},
        ],
        temperature=0.3,
        timeout=180,
    )
    content = resp.choices[0].message.content or ""
    return content.strip()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="未维护问题聚类 + 起草共用回答")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="余弦相似度阈值（默认 0.85）")
    parser.add_argument("--limit", type=int, default=None, help="只处理最近 N 条未维护问题（冒烟测试用）")
    parser.add_argument("--dry-run", action="store_true", help="只聚类，不调模型、不写库")
    args = parser.parse_args()

    rows = list_unmaintained_qa(limit=args.limit)
    if not rows:
        print("没有未维护问题，退出")
        return
    print(f"未维护问题 {len(rows)} 条，开始向量化…")
    vectors = np.asarray(embed_texts([r["question"] for r in rows]), dtype="float32")

    clusters = greedy_cluster(vectors, args.threshold)
    clusters.sort(key=lambda c: (-len(c), min(c)))
    print(f"聚成 {len(clusters)} 簇（阈值 {args.threshold}）：")
    for i, members in enumerate(clusters, 1):
        print(f"  簇 {i}: {len(members)} 条 | 样例: {rows[members[0]]['question'][:50]}")
    if args.dry_run:
        print("--dry-run：不调模型、不写库")
        return

    written = 0
    for i, members in enumerate(clusters, 1):
        questions = [rows[k]["question"] for k in members]
        titles: list[str] = []
        for k in members:
            for t in source_titles(rows[k].get("sources")):
                if t not in titles:
                    titles.append(t)
        try:
            draft = draft_answer(questions, titles)
        except Exception as e:  # 单簇起草失败不拖垮整批
            print(f"  ✗ 簇 {i} 起草失败: {type(e).__name__}: {e}")
            continue
        if not draft:
            print(f"  ✗ 簇 {i} 起草结果为空，跳过")
            continue
        qa_ids = [int(rows[k]["id"]) for k in members]
        updated = save_answer_drafts(qa_ids, draft)
        written += updated
        print(f"  ✓ 簇 {i}: {updated} 条写回草稿（{len(draft)} 字）")

    print(f"\n完成：{len(clusters)} 簇，累计写回 {written} 条草稿")


if __name__ == "__main__":
    main()
