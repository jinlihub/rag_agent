"""tools/rag_tools.py 中「通用法优先」的单元测试。

这个函数是 2026-11-11 新增的：用户没提行业时，给《招标投标法》《政府采购法》
加权，避免被大量行业办法（铁路/水利/通信）挤出前列。

它直接决定法规类问题的参考来源顺序，改坏了线上不易察觉（答案还是那些，
只是顺序变了），所以边界要固定住。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag_agent.tools.rag_tools import _GENERAL_LAWS, _INDUSTRY_WORDS, _prefer_general_law  # noqa: E402


def hit(row: int, law: str, score: float) -> dict:
    return {"row": row, "law_name": law, "score": score}


@pytest.fixture
def mixed_hits():
    """行业办法在首位、通用法在次位——正是加权的目标场景。"""
    return [
        hit(1, "房屋建筑和市政基础设施工程施工招标投标管理办法", 1.0),
        hit(2, "中华人民共和国招标投标法", 0.991),
        hit(3, "招标公告和公示信息发布管理办法", 0.573),
    ]


class TestPreferGeneralLaw:
    def test_boosts_general_law_above_industry(self, mixed_hits):
        out = _prefer_general_law(mixed_hits, "公开招标的公告要发在哪些地方")
        assert out[0]["law_name"] == "中华人民共和国招标投标法"
        assert out[0]["row"] == 2

    def test_boost_factor_is_1_1(self, mixed_hits):
        out = _prefer_general_law(mixed_hits, "公开招标的公告要发在哪些地方")
        boosted = next(h for h in out if h["row"] == 2)
        assert boosted["score"] == pytest.approx(0.991 * 1.1, abs=1e-3)

    def test_non_general_scores_untouched(self, mixed_hits):
        out = _prefer_general_law(mixed_hits, "公开招标的公告要发在哪些地方")
        assert next(h for h in out if h["row"] == 1)["score"] == 1.0
        assert next(h for h in out if h["row"] == 3)["score"] == 0.573

    def test_does_not_mutate_input(self, mixed_hits):
        before = [dict(h) for h in mixed_hits]
        _prefer_general_law(mixed_hits, "公开招标的公告要发在哪些地方")
        assert mixed_hits == before, "不应原地修改传入的列表"

    @pytest.mark.parametrize("industry", sorted(_INDUSTRY_WORDS)[:6])
    def test_industry_query_keeps_order(self, mixed_hits, industry):
        """用户明确提了行业，说明要的就是行业办法，不干预排序。"""
        out = _prefer_general_law(mixed_hits, f"{industry}项目的招标公告要发在哪")
        assert [h["row"] for h in out] == [1, 2, 3]

    def test_no_general_law_keeps_order(self):
        hits = [
            hit(1, "铁路建设工程招标投标实施办法", 1.0),
            hit(2, "水利工程建设项目招标投标管理规定", 0.9),
        ]
        out = _prefer_general_law(hits, "招标文件要写什么")
        assert [h["row"] for h in out] == [1, 2]

    def test_empty_hits(self):
        assert _prefer_general_law([], "招标文件要写什么") == []

    def test_handles_missing_law_name(self):
        """policy/faq 来源没有 law_name，不该抛异常。

        注意这里 0.7×1.1=0.77 仍小于 0.8，顺序不变——本测试只验证「不崩」，
        不验证加权后超越。
        """
        hits = [{"row": 1, "score": 0.8}, {"row": 2, "law_name": "中华人民共和国政府采购法", "score": 0.7}]
        out = _prefer_general_law(hits, "政府采购必须买国产吗")
        assert [h["row"] for h in out] == [1, 2]
        assert next(h for h in out if h["row"] == 1)["score"] == 0.8, "缺 law_name 的项不应被改动"

    def test_all_general_laws(self):
        hits = [
            hit(1, "中华人民共和国政府采购法", 0.8),
            hit(2, "中华人民共和国招标投标法", 0.9),
        ]
        out = _prefer_general_law(hits, "投标保证金上限")
        assert [h["row"] for h in out] == [2, 1], "都加权后仍按加权分数排序"


class TestConstants:
    def test_general_laws_are_national_level(self):
        assert all(law.startswith("中华人民共和国") for law in _GENERAL_LAWS)

    def test_industry_words_not_empty(self):
        assert len(_INDUSTRY_WORDS) >= 10

    def test_common_industries_covered(self):
        for word in ("铁路", "水利", "公路", "通信", "农业"):
            assert word in _INDUSTRY_WORDS
