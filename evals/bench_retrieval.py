"""实测当前检索栈的性能：索引加载、向量检索延迟、embedding 调用延迟。

分开测「向量检索」和「embedding 调用」是关键——
如果瓶颈在 embedding API，换向量库再多也省不掉这部分。
"""

import statistics
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from rag_agent.llm import embed_texts  # noqa: E402
from rag_agent.retrieval.vector_store import get_store  # noqa: E402

IDX = _ROOT / "data" / "index"

print("=" * 60)
print("一、索引文件体积与规模")
print("=" * 60)
total = 0
for name in ("legal", "policy", "faq"):
    npz = IDX / f"{name}.npz"
    meta = IDX / f"{name}.meta.jsonl"
    if not npz.exists():
        continue
    npz_mb = npz.stat().st_size / 1024 / 1024
    meta_mb = meta.stat().st_size / 1024 / 1024 if meta.exists() else 0
    data = np.load(npz)
    arr = data["vectors"] if "vectors" in data else list(data.values())[0]
    total += npz_mb + meta_mb
    print(f"  {name:8} {arr.shape[0]:>5} 条 × {arr.shape[1]:>4} 维   "
          f"npz {npz_mb:>6.1f} MB  meta {meta_mb:>5.1f} MB   dtype={arr.dtype}")
print(f"  合计索引体积 {total:.1f} MB")

print()
print("=" * 60)
print("二、冷启动加载耗时")
print("=" * 60)
for name in ("legal", "policy", "faq"):
    if not (IDX / f"{name}.npz").exists():
        continue
    t0 = time.perf_counter()
    store = get_store(name)
    _ = store.vectors.shape
    print(f"  {name:8} 加载 {((time.perf_counter() - t0) * 1000):.1f} ms")

print()
print("=" * 60)
print("三、纯向量检索延迟（不含 embedding，模拟向量已就绪）")
print("=" * 60)
store = get_store("legal")
vecs = store.vectors
n, dim = vecs.shape

# 用随机向量模拟 query，测「点积 + argsort」本身
rng = np.random.default_rng(0)
qs = rng.standard_normal((200, dim)).astype("float32")
qs /= np.linalg.norm(qs, axis=1, keepdims=True)

lat = []
for q in qs:
    t0 = time.perf_counter()
    scores = vecs @ q
    top = np.argsort(-scores)[:15]
    _ = [int(i) for i in top]
    lat.append((time.perf_counter() - t0) * 1000)

lat.sort()
print(f"  语料 {n} 条 × {dim} 维，200 次查询")
print(f"  P50 {statistics.median(lat):.2f} ms   P95 {lat[int(len(lat) * 0.95)]:.2f} ms   "
      f"max {lat[-1]:.2f} ms")

print()
print("=" * 60)
print("四、embedding 调用延迟（真实 API，逐次不同 query 无缓存）")
print("=" * 60)
samples = [
    "供应商提出质疑的时限是多少天",
    "投标保证金退还的条件",
    "公开招标与邀请招标的区别",
    "单一来源采购的适用情形",
    "评标委员会成员的回避规定",
]
emb_lat = []
for s in samples:
    t0 = time.perf_counter()
    try:
        v = embed_texts([s + f" #{time.time_ns() % 100000}"])
        if not v or not v[0]:
            print("  embedding 返回空，跳过该项")
            break
        emb_lat.append((time.perf_counter() - t0) * 1000)
    except Exception as e:  # noqa: BLE001
        print(f"  embedding 调用失败：{e}")
        break

if emb_lat:
    print(f"  {len(emb_lat)} 次调用  平均 {statistics.mean(emb_lat):.0f} ms   "
          f"最快 {min(emb_lat):.0f} ms   最慢 {max(emb_lat):.0f} ms")
    print(f"\n  → 单次检索总耗时 ≈ embedding {statistics.mean(emb_lat):.0f} ms + "
          f"向量检索 {statistics.median(lat):.1f} ms")
    print(f"  → 向量检索占比 {statistics.median(lat) / (statistics.mean(emb_lat) + statistics.median(lat)) * 100:.2f}%")
