"""并发直跑全量标的物提取（不依赖 Batch API）。

读 data/raw/核心标的物提取_batch_flash.jsonl 的请求，多线程并发调 chat/completions，
成功的行按 Batch API 输出格式追加写入 data/batch/batch_results_processed.jsonl，
可直接喂给 提数据_插标的物.py。

断点续跑：只统计 status_code=200 的行，中断后重跑本脚本会跳过已成功的、补跑失败的。
失败行不写入文件，避免同一 custom_id 重复。

用法:
    uv run python batch/并发提标的物.py                  # 默认 8 并发
    uv run python batch/并发提标的物.py --workers 4      # 限流严重时降并发
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "data" / "raw" / "核心标的物提取_batch_flash.jsonl"
_OUT = _ROOT / "data" / "batch" / "batch_results_processed.jsonl"
_RETRY = 3


def _load_done(path: Path) -> set[str]:
    """已成功的 custom_id 集合（status_code=200 才算，失败的会重跑）。"""
    if not path.exists():
        return set()
    done: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (obj.get("response") or {}).get("status_code") == 200:
                cid = obj.get("custom_id")
                if cid:
                    done.add(cid)
    return done


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.chdir(_ROOT)

    ap = argparse.ArgumentParser(description="并发跑全量标的物提取")
    ap.add_argument("--workers", type=int, default=8, help="并发数（默认 8）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全部），用于小批验证")
    ap.add_argument("--src", type=Path, default=_SRC)
    ap.add_argument("--out", type=Path, default=_OUT)
    args = ap.parse_args()

    from rag_agent.config import get_settings

    s = get_settings()
    client = OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=120, max_retries=0)

    reqs = [json.loads(line) for line in args.src.open(encoding="utf-8") if line.strip()]
    done = _load_done(args.out)
    pending = [r for r in reqs if r["custom_id"] not in done]
    print(f"总请求 {len(reqs)} | 已成功 {len(done)} | 待跑 {len(pending)} | 并发 {args.workers}")
    if args.limit:
        pending = pending[:args.limit]
        print(f"--limit {args.limit}：本次只跑 {len(pending)} 条")
    if not pending:
        print("全部已完成。")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    t0 = time.perf_counter()

    def call(req: dict) -> dict:
        body = req["body"]
        item = {"custom_id": req["custom_id"], "id": "local"}
        last = ""
        for attempt in range(_RETRY):
            try:
                resp = client.chat.completions.create(
                    model=body["model"],
                    messages=body["messages"],
                    temperature=body.get("temperature", 0.1),
                    extra_body={"thinking": body.get("thinking")},
                )
                item["response"] = {"status_code": 200, "body": resp.model_dump()}
                return item
            except Exception as e:  # noqa: BLE001 —— 单条失败不影响整批
                last = f"{type(e).__name__}: {str(e)[:150]}"
                if "429" in last or "rate" in last.lower() or "overload" in last.lower():
                    time.sleep(2 * (attempt + 1))
                    continue
                break
        item["response"] = {"status_code": 500, "body": {"error": last}}
        return item

    with args.out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(call, r): r["custom_id"] for r in pending}
        for i, fut in enumerate(as_completed(futures), 1):
            item = fut.result()
            if item["response"]["status_code"] == 200:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                f.flush()
                ok += 1
            else:
                fail += 1
            if i % 100 == 0 or i == len(pending):
                el = time.perf_counter() - t0
                eta = (len(pending) - i) * el / i / 60
                print(f"[{i}/{len(pending)}] ok={ok} fail={fail} "
                      f"已用 {el/60:.1f} min · 预计剩余 {eta:.1f} min")

    print(f"\n结果写入 {args.out}（成功 {ok}，失败 {fail}）")
    if fail:
        print("失败的项没有写入文件，直接重跑本脚本即可补跑，已成功的会自动跳过。")


if __name__ == "__main__":
    main()
