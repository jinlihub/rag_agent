"""clients/model_catalog.py 与 llm_factory 的多 provider 路由测试。

背景：一个 LLM_BASE_URL 只能对应一家厂商。要让前端下拉同时出现智谱和
DeepSeek，必须先解决「模型 → 厂商」的映射，否则探活和调用都会打错端点。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag_agent.clients import llm_factory, model_catalog  # noqa: E402
from rag_agent.clients.deepseek_client import DeepSeekClient  # noqa: E402
from rag_agent.clients.zai_client import ZaiClient  # noqa: E402


class TestCatalogShape:
    def test_contains_models_from_both_providers(self):
        """下拉要同时列智谱和 DeepSeek 的模型。"""
        ids = {c.id for c in model_catalog.catalog()}
        assert "glm-4.7-flashx" in ids, "智谱模型应在列"
        assert "deepseek-flash" in ids, "DeepSeek 模型应在列"

    def test_each_item_has_provider(self):
        for c in model_catalog.catalog():
            assert c.provider in ("zai", "deepseek"), f"{c.id} 缺少合法 provider"


class TestProviderOf:
    @pytest.mark.parametrize(
        "model_id,expected",
        [
            ("glm-4.7-flashx", "zai"),
            ("glm-4.5-air", "zai"),
            ("glm-4-flash", "zai"),
            ("deepseek-flash", "deepseek"),
            ("deepseek-v4-pro", "deepseek"),
        ],
    )
    def test_known_models(self, model_id, expected):
        assert model_catalog.provider_of(model_id) == expected

    def test_unknown_model_falls_back_to_configured_provider(self):
        """未知模型（如 LLM_MODEL_CHOICES 自定义的）按当前 provider 处理。"""
        from rag_agent.config import get_settings

        default = (get_settings().llm_provider or "zai").strip().lower()
        assert model_catalog.provider_of("某个自定义模型") == default


class TestClientRouting:
    def test_get_client_for_zai(self):
        assert isinstance(llm_factory.get_client_for("zai"), ZaiClient)

    def test_get_client_for_deepseek(self):
        assert isinstance(llm_factory.get_client_for("deepseek"), DeepSeekClient)

    def test_same_provider_returns_cached_instance(self):
        """同一 provider 应复用实例，避免每次调用都重建连接池。"""
        assert llm_factory.get_client_for("zai") is llm_factory.get_client_for("zai")

    def test_unknown_provider_raises(self):
        with pytest.raises(RuntimeError, match="未知"):
            llm_factory.get_client_for("openai")

    def test_get_llm_client_still_works(self):
        """保留旧接口：仍返回当前配置 provider 的客户端。"""
        from rag_agent.config import get_settings

        provider = (get_settings().llm_provider or "zai").strip().lower()
        assert llm_factory.get_llm_client() is llm_factory.get_client_for(provider)


class TestProbeUsesCorrectProvider:
    def test_probe_calls_client_of_that_provider(self, monkeypatch):
        """探活必须用模型所属厂商的 client，否则会用错 base_url 判成不可用。"""
        called: list[str] = []

        class FakeClient:
            provider = "fake"

            def chat(self, *a, **kw):
                called.append(kw.get("model", ""))
                raise RuntimeError("probe stop")

        monkeypatch.setattr(
            model_catalog, "get_client_for", lambda p: (called.append(f"client:{p}"), FakeClient())[1]
        )
        model_catalog._probe_one("deepseek-flash")
        assert "client:deepseek" in called, "应取 deepseek 的 client"
        assert "deepseek-flash" in called
