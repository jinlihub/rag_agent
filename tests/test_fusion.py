"""retrieval/fusion.py 的单元测试：查询分类与 RRF 融合。

这两个都是纯函数，是整个检索链路里「判错代价最大、又最容易写错」的部分：
分类错了 → 权重用错；融合错了 → 排序乱掉，而且线上一时看不出来。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag_agent.retrieval.fusion import classify_query, profile_for, rrf_fuse  # noqa: E402


class TestClassifyQuery:
    """法规 / 概念 / 通用三类判定。"""

    @pytest.mark.parametrize(
        "query",
        [
            "《招标投标法》第二十三条怎么规定的",
            "供应商提出质疑的时限是多少天",
            "投标保证金的比例上限",
            "废标后可以重新招标吗",
            "中标通知书发出后多久签合同",
            "评标委员会成员需要回避吗",
            "这个项目的投标有效期是多少个工作日",
        ],
    )
    def test_legal_features(self, query):
        assert classify_query(query) == "legal"

    @pytest.mark.parametrize(
        "query",
        [
            "什么是单一来源采购",
            "公开招标和邀请招标有什么区别",
            "联合体投标是什么意思",
            "什么是不平衡报价",
        ],
    )
    def test_conceptual_features(self, query):
        assert classify_query(query) == "conceptual"

    @pytest.mark.parametrize(
        "query",
        [
            "废标的含义是什么",
            "为什么需要履约保证金",
            "什么是投标保证金",
        ],
    )
    def test_legal_wins_even_when_asking_for_definition(self, query):
        """含法规术语时即使问「含义」也判 legal —— 这是有意的取舍。

        术语本身就是强匹配信号：用户问「废标的含义」，检索时按法规条文走
        （sparse 权重 0.6）比按概念语义走更容易命中法条原文。
        如果哪天改为「问含义就判概念类」，这条测试会失败，提醒同步调整策略。
        """
        assert classify_query(query) == "legal"

    @pytest.mark.parametrize(
        "query",
        [
            "有哪些关于空调的采购项目",
            "重庆稳信科技有限公司中标了哪些项目",
            "合肥市有哪些工程类项目",
            "帮我查一下那个项目",
        ],
    )
    def test_general_features(self, query):
        assert classify_query(query) == "general"

    @pytest.mark.parametrize(
        "query",
        [
            "这个方法怎么做",
            "有什么好的做法",
            "你有什么想法",
            "这个说法对吗",
        ],
    )
    def test_legal_not_triggered_by_false_positives(self, query):
        """「方法/做法/想法/说法」里的「法」不该判成法规类。"""
        assert classify_query(query) != "legal"

    def test_legal_takes_priority_over_conceptual(self):
        """同时含两类特征时，法规类优先——命中法条特征就是强信号。"""
        assert classify_query("什么是投标保证金，规定在哪条") == "legal"

    def test_empty_string_is_general(self):
        assert classify_query("") == "general"


class TestProfileFor:
    def test_legal_params(self):
        p = profile_for("供应商提出质疑的时限")
        assert p["kind"] == "legal"
        assert p["k"] == 30
        assert p["dense"] == 0.4
        assert p["sparse"] == 0.6

    def test_conceptual_params(self):
        p = profile_for("什么是单一来源采购")
        assert p["kind"] == "conceptual"
        assert p["k"] == 80
        assert p["dense"] == 0.7

    def test_general_params(self):
        p = profile_for("有哪些空调采购项目")
        assert p["kind"] == "general"
        assert p["k"] == 60
        assert p["dense"] == 0.55

    def test_weights_sum_to_one(self):
        for q in ("质疑时限", "什么是单一来源", "空调采购项目"):
            p = profile_for(q)
            assert p["dense"] + p["sparse"] == pytest.approx(1.0)


class TestRrfFuse:
    def test_empty_input(self):
        assert rrf_fuse([], k=60) == []

    def test_all_empty_paths(self):
        assert rrf_fuse([([], 0.5), ([], 0.5)], k=60) == []

    def test_single_path(self):
        out = rrf_fuse([([{"row": 0}, {"row": 1}], 1.0)], k=60)
        assert [x["row"] for x in out] == [0, 1]
        assert out[0]["score"] == 1.0  # 归一到 1
        assert 0 < out[1]["score"] < 1.0

    def test_dedup_and_score_accumulation(self):
        """同一 row 被两路召回时得分叠加，应排到最前。"""
        dense = [{"row": 5}, {"row": 3}]
        sparse = [{"row": 3}, {"row": 7}]
        out = rrf_fuse([(dense, 0.5), (sparse, 0.5)], k=60)
        rows = [x["row"] for x in out]
        assert rows[0] == 3, "两路都命中的 row=3 应排第一"
        assert set(rows) == {3, 5, 7}, "重复行应被合并"
        assert len(rows) == 3

    def test_weight_affects_order(self):
        dense = [{"row": 1}]
        sparse = [{"row": 2}]
        heavy_dense = rrf_fuse([(dense, 0.9), (sparse, 0.1)], k=60)
        heavy_sparse = rrf_fuse([(dense, 0.1), (sparse, 0.9)], k=60)
        assert heavy_dense[0]["row"] == 1
        assert heavy_sparse[0]["row"] == 2

    def test_k_affects_head_emphasis(self):
        """k 越小，头部排名差距被放大：rank1 与 rank2 的分差应更大。"""
        items = [{"row": 1}, {"row": 2}]
        small_k = rrf_fuse([(items, 1.0)], k=10)
        large_k = rrf_fuse([(items, 1.0)], k=100)
        assert small_k[1]["score"] < large_k[1]["score"]

    def test_skip_items_without_row(self):
        out = rrf_fuse([([{"text": "没有 row 字段"}, {"row": 9}], 1.0)], k=60)
        assert [x["row"] for x in out] == [9]

    def test_score_normalized_and_sorted(self):
        dense = [{"row": i} for i in range(5)]
        out = rrf_fuse([(dense, 1.0)], k=60)
        scores = [x["score"] for x in out]
        assert scores == sorted(scores, reverse=True), "应按分数降序"
        assert max(scores) == 1.0
        assert all(0 < s <= 1.0 for s in scores)

    def test_preserves_original_fields(self):
        out = rrf_fuse([([{"row": 1, "text": "原文", "law_name": "招标投标法"}], 1.0)], k=60)
        assert out[0]["text"] == "原文"
        assert out[0]["law_name"] == "招标投标法"
        assert "score" in out[0]
