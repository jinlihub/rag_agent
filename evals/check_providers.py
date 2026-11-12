"""验证多 provider：分别用智谱与 DeepSeek 的客户端各调一次。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rag_agent.clients.llm_factory import get_client_for, known_providers  # noqa: E402
from rag_agent.clients.model_catalog import catalog, provider_of  # noqa: E402

print("已注册厂商:", known_providers())
print("\n候选模型清单：")
for c in catalog():
    print(f"  {c.provider:9} {c.id:24} {c.label:10} {c.hint}")

print("\nprovider_of 抽查：")
for m in ("glm-4.7-flashx", "deepseek-flash", "deepseek-v4-pro"):
    print(f"  {m:22} → {provider_of(m)}")

print("\n实际调用测试：")
for provider, model in (("zai", "glm-4.5-air"), ("deepseek", "deepseek-flash")):
    try:
        client = get_client_for(provider)
        resp = client.chat(
            [{"role": "user", "content": "回复两个字：收到"}],
            model=model,
            temperature=0,
            max_tokens=16,
        )
        text = (resp.choices[0].message.content or "").strip()
        print(f"  [{provider}] {model:18} → {text[:30]!r}  ✅")
    except Exception as e:  # noqa: BLE001
        print(f"  [{provider}] {model:18} → {type(e).__name__}: {str(e)[:90]}")
