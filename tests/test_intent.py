"""agent/intent.py 的寒暄判定测试。

规则用正则整句匹配（零模型调用）。关键边界：
带业务内容的句子不能被判成寒暄，否则用户的问题会被当客套话敷衍掉。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag_agent.agent.intent import _parse_label, is_chitchat  # noqa: E402


class TestIsChitchat:
    @pytest.mark.parametrize(
        "text",
        [
            "你好",
            "您好",
            "嗨",
            "在吗",
            "在不在",
            "谢谢",
            "谢谢你",
            "多谢",
            "辛苦了",
            "好的",
            "收到",
            "你是谁",
            "你叫什么名字",
            "你能做什么",
            "hello",
            "Hi",
        ],
    )
    def test_pure_chitchat(self, text):
        assert is_chitchat(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "你好呀",
            "你好啊",
            "谢谢啦",
            "谢谢你！",
            "你好，你是谁",
            "谢谢你的回答",
            "好的，谢谢",
            "你好~",
        ],
    )
    def test_chitchat_with_particles(self, text):
        """带语气词、标点、组合客套话仍算寒暄。"""
        assert is_chitchat(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "你好，查一下安徽的项目",
            "谢谢，那投标保证金是多少",
            "你好，我想问一下单一来源采购的条件",
            "在吗，帮我查个中标记录",
            "你是谁开发的这个系统",
        ],
    )
    def test_business_content_not_chitchat(self, text):
        """带业务内容的句子必须交给模型分类，不能当寒暄。"""
        assert is_chitchat(text) is False

    @pytest.mark.parametrize("text", ["", "   ", "今天天气不错", "量子纠缠是什么"])
    def test_non_chitchat(self, text):
        assert is_chitchat(text) is False

    def test_leading_trailing_space_tolerated(self):
        assert is_chitchat("  你好  ") is True


class TestParseLabel:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("chitchat", "chitchat"),
            ("faq", "faq"),
            ("complex", "complex"),
            ("  faq  ", "faq"),
            ("标签：complex", "complex"),
            ("FAQ", "faq"),  # 大小写不敏感
        ],
    )
    def test_english_labels(self, raw, expected):
        assert _parse_label(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("这是寒暄", "chitchat"),
            ("属于闲聊", "chitchat"),
            ("答案在实务问答里", "faq"),
            ("查知识库", "faq"),
        ],
    )
    def test_chinese_fallback(self, raw, expected):
        """模型偶尔回中文，做一层宽松兜底。"""
        assert _parse_label(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "不知道", "随便"])
    def test_unparseable_defaults_to_complex(self, raw):
        """解析不出就按复杂处理——宁可多查一轮，不可误判后直接作答。"""
        assert _parse_label(raw) == "complex"
