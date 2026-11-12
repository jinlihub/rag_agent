"""把知识图谱 CSV 注入 Neo4j（建节点 + 关系，含基础实体归一化）。

输入 data/processed/招标采购标的物信息提取训练数据_2_知识图谱.csv（六列）：
    标的物、采购商、代理机构、供应商、交易额、所在地

图模型：
    节点  Item(标的物)  Purchaser(采购商)  Supplier(供应商)
          Agency(代理机构)  Location(所在地)
    关系  采购 (Purchaser)-[:采购 {amount}]->(Item)
          中标 (Supplier)-[:中标 {amount}]->(Item)
          委托 (Purchaser)-[:委托]->(Agency)
          位于 (Item)-[:位于]->(Location)

归一化：实体名首尾空白裁剪；空值跳过对应节点/关系；同一实体的重复名称
（如 "合肥A公司" 与 "合肥A有限公司"）这里只做精确去重，模糊合并需另配实体
消歧表，见 docs 说明。

用法:
    uv run python scripts/import_to_neo4j.py                    # 全量注入
    uv run python scripts/import_to_neo4j.py --csv 其它.csv     # 指定 CSV
    uv run python scripts/import_to_neo4j.py --dry-run          # 只打印统计，不连库
    uv run python scripts/import_to_neo4j.py --clear            # 注入前先清空（删全部节点）
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from rag_agent.retrieval.neo4j_client import Neo4jNotConfigured, query

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CSV = _ROOT / "data" / "processed" / "招标采购标的物信息提取训练数据_2_知识图谱.csv"

# 列名 → (节点标签, 节点属性名)；标的物/所在地是独立节点，采购商/供应商/代理机构是实体节点
_ENTITY_LABELS = {
    "采购商": ("Purchaser", "name"),
    "代理机构": ("Agency", "name"),
    "供应商": ("Supplier", "name"),
    "所在地": ("Location", "name"),
}

# 批量注入：一次 UNWIND 处理一批行，把 8789 次往返压到十几次。
# FOREACH 内的变量不跨块生效，故「委托」关系里重新 MERGE 一次采购商（同名会复用已有节点）。
_IMPORT_CYPHER = """
UNWIND $rows AS r
MERGE (i:Item {name: r.item})
FOREACH (_ IN CASE WHEN r.pur IS NULL THEN [] ELSE [1] END |
  MERGE (p:Purchaser {name: r.pur})
  MERGE (p)-[:采购 {amount: r.amount}]->(i)
)
FOREACH (_ IN CASE WHEN r.sup IS NULL THEN [] ELSE [1] END |
  MERGE (s:Supplier {name: r.sup})
  MERGE (s)-[:中标 {amount: r.amount}]->(i)
)
FOREACH (_ IN CASE WHEN r.ag IS NULL OR r.pur IS NULL THEN [] ELSE [1] END |
  MERGE (a:Agency {name: r.ag})
  MERGE (p2:Purchaser {name: r.pur})
  MERGE (p2)-[:委托]->(a)
)
FOREACH (_ IN CASE WHEN r.loc IS NULL THEN [] ELSE [1] END |
  MERGE (l:Location {name: r.loc})
  MERGE (i)-[:位于]->(l)
)
"""

_BATCH = 500  # 每批行数：太大单事务内存高，太小往返次数多


def _norm(name: str | None) -> str | None:
    """实体名归一：裁剪首尾空白，去内联多余空格；空串返回 None。"""
    if name is None:
        return None
    name = " ".join(str(name).split())
    return name or None


def _to_int(v) -> int | None:
    """交易额 → 整数元；空/非法返回 None。"""
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _counts() -> dict[str, int]:
    """各节点/关系标签的计数（用于 dry-run 与注入后核对）。"""
    out: dict[str, int] = {}
    for label in ("Item", "Purchaser", "Supplier", "Agency", "Location"):
        try:
            out[label] = query(f"MATCH (n:{label}) RETURN count(n) AS c")[0]["c"]
        except Exception:  # noqa: BLE001 —— 库不可达时跳过
            out[label] = -1
    for rel in ("采购", "中标", "委托", "位于"):
        try:
            out[rel] = query(f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c")[0]["c"]
        except Exception:  # noqa: BLE001
            out[rel] = -1
    return out


def _load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="知识图谱 CSV → Neo4j")
    ap.add_argument("--csv", type=Path, default=_DEFAULT_CSV)
    ap.add_argument("--dry-run", action="store_true", help="只统计待注入数据，不连库")
    ap.add_argument("--clear", action="store_true", help="注入前清空现有图（删全部节点与关系）")
    args = ap.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"CSV 不存在: {args.csv}")

    rows = _load_rows(args.csv)
    # 预统计
    items = suppliers = purchasers = agencies = locations = 0
    edges = 0
    for r in rows:
        item = _norm(r.get("标的物"))
        pur = _norm(r.get("采购商"))
        sup = _norm(r.get("供应商"))
        ag = _norm(r.get("代理机构"))
        loc = _norm(r.get("所在地"))
        amount = _to_int(r.get("交易额"))
        if item:
            items += 1
        if pur:
            purchasers += 1
        if sup:
            suppliers += 1
        if ag:
            agencies += 1
        if loc:
            locations += 1
        if item and pur:
            edges += 1
        if item and sup:
            edges += 1
        if pur and ag:
            edges += 1
        if item and loc:
            edges += 1

    print(f"CSV 行数: {len(rows)}")
    print(f"待建节点: Item={items} Purchaser={purchasers} Supplier={suppliers} "
          f"Agency={agencies} Location={locations}")
    print(f"待建关系: {edges}（采购+中标+委托+位于）")

    if args.dry_run:
        print("--dry-run：不连库，仅以上统计。")
        return

    try:
        query("MATCH (n) RETURN count(n) AS c LIMIT 1")  # 连通性自检
    except Neo4jNotConfigured as e:
        raise SystemExit(str(e))
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Neo4j 连接失败: {e}")

    if args.clear:
        query("MATCH (n) DETACH DELETE n")
        print("已清空现有图。")

    # 先清洗成待注入 payload，再按批 UNWIND 写入（每批一条语句、一次往返）
    payload: list[dict] = []
    for r in rows:
        item = _norm(r.get("标的物"))
        if not item:
            continue  # 没有标的物就无法成图，跳过
        payload.append(
            {
                "item": item,
                "pur": _norm(r.get("采购商")),
                "sup": _norm(r.get("供应商")),
                "ag": _norm(r.get("代理机构")),
                "loc": _norm(r.get("所在地")),
                "amount": _to_int(r.get("交易额")),
            }
        )

    done = 0
    for i in range(0, len(payload), _BATCH):
        chunk = payload[i : i + _BATCH]
        query(_IMPORT_CYPHER, rows=chunk)
        done += len(chunk)
        if done % 1000 < _BATCH:  # 每满 1000 行报一次进度（按批对齐，不逐行判断）
            print(f"  已注入 {done}/{len(payload)} 行")

    print(f"注入完成，共处理 {done} 行。")
    counts = _counts()
    print("节点:", {k: counts.get(k) for k in ("Item", "Purchaser", "Supplier", "Agency", "Location")})
    print("关系:", {k: counts.get(k) for k in ("采购", "中标", "委托", "位于")})


if __name__ == "__main__":
    main()
