"""智谱 Batch API 批量任务：提交 / 列表 / 等待 / 下载结果。

配合 提数据_编JSONL.py 生成的请求 JSONL 使用（OpenAI 兼容格式，purpose=batch
上传文件后创建批量任务）。batch id 保存在 data/raw/批量任务_id.txt，wait /
download 缺省读取；API key 取 .env 的 LLM_API_KEY。

用法:
    uv run python batch/批量任务.py list                     # 最近批量任务
    uv run python batch/批量任务.py submit --input 请求.jsonl
    uv run python batch/批量任务.py wait                     # 轮询到任务结束
    uv run python batch/批量任务.py download                 # 下载结果 JSONL
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

_ROOT = Path(__file__).resolve().parents[1]
_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
_ID_FILE = _ROOT / "data" / "raw" / "批量任务_id.txt"
_DEFAULT_INPUT = _ROOT / "data" / "raw" / "核心标的物提取_batch.jsonl"
_DEFAULT_OUTPUT = _ROOT / "data" / "raw" / "核心标的物提取_batch_results.jsonl"
_DONE = {"completed", "failed", "expired", "cancelled"}


def _client() -> OpenAI:
    load_dotenv(_ROOT / ".env")
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise SystemExit("缺少 API key：.env 的 LLM_API_KEY 未设置")
    return OpenAI(api_key=key, base_url=_BASE_URL)


def _save_id(batch_id: str) -> None:
    _ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ID_FILE.write_text(batch_id, encoding="utf-8")


def _load_id(args: argparse.Namespace) -> str:
    if getattr(args, "batch_id", None):
        return args.batch_id
    if _ID_FILE.exists():
        return _ID_FILE.read_text(encoding="utf-8").strip()
    raise SystemExit(f"未提供 batch id，且记录文件不存在: {_ID_FILE}（先执行 submit）")


def _describe(batch: object) -> str:
    counts = getattr(batch, "request_counts", None)
    n = f"{getattr(counts, 'completed', 0)}/{getattr(counts, 'total', 0)}" if counts else "-"
    fail = getattr(counts, "failed", 0) if counts else 0
    err = getattr(batch, "error", None)
    msg = f"，error: {err}" if err else ""
    return f"{getattr(batch, 'status', '?')}（完成 {n}，失败 {fail}）{msg}"


def _fmt_ts(v: object) -> str:
    """created_at 兼容 unix 时间戳（秒/毫秒）与字符串三种返回。"""
    if isinstance(v, (int, float)):
        secs = v / 1000 if v > 1e12 else v
        return datetime.fromtimestamp(secs).strftime("%m-%d %H:%M")
    return str(v)[:16]


def cmd_list(args: argparse.Namespace) -> None:
    client = _client()
    batches = client.batches.list(limit=args.limit).data or []
    if not batches:
        print("平台上没有批量任务")
        return
    for b in batches:
        desc = (b.metadata or {}).get("description", "")
        print(f"{b.id}  {_fmt_ts(b.created_at)}  {_describe(b)}  {desc}")


def cmd_submit(args: argparse.Namespace) -> None:
    if not args.input.exists():
        raise SystemExit(f"输入文件不存在: {args.input}")
    first = json.loads(args.input.read_text(encoding="utf-8").splitlines()[0])
    endpoint = first.get("url", "/v4/chat/completions")
    total = sum(1 for ln in args.input.open(encoding="utf-8") if ln.strip())
    client = _client()
    with args.input.open("rb") as f:
        file = client.files.create(file=f, purpose="batch")
    batch = client.batches.create(
        input_file_id=file.id,
        endpoint=endpoint,
        completion_window="24h",
        metadata={"description": f"核心标的物提取 {args.input.name}"},
    )
    _save_id(batch.id)
    print(f"请求数: {total}，endpoint: {endpoint}")
    print(f"上传文件: {file.id}")
    print(f"批量任务: {batch.id}（id 已存 {_ID_FILE.name}）")
    print(f"状态: {_describe(batch)}")


def cmd_wait(args: argparse.Namespace) -> None:
    client = _client()
    batch_id = _load_id(args)
    deadline = time.monotonic() + args.timeout
    batch = client.batches.retrieve(batch_id)
    last = ""
    while True:
        line = _describe(batch)
        if line != last:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {batch_id}: {line}")
            last = line
        if batch.status in _DONE:
            if batch.status != "completed":
                raise SystemExit(f"批量任务未完成: {batch.status}")
            print(f"结果文件: {batch.output_file_id}")
            return
        if time.monotonic() > deadline:
            raise SystemExit(f"等待超时（{args.timeout}s），任务仍为 {batch.status}，稍后重跑 wait 继续")
        time.sleep(args.interval)
        batch = client.batches.retrieve(batch_id)


def cmd_download(args: argparse.Namespace) -> None:
    client = _client()
    batch_id = _load_id(args)
    batch = client.batches.retrieve(batch_id)
    if batch.status != "completed" or not batch.output_file_id:
        raise SystemExit(f"任务不可下载，当前状态: {_describe(batch)}")
    data = client.files.content(batch.output_file_id).content
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    lines = sum(1 for ln in args.output.open(encoding="utf-8") if ln.strip())
    print(f"已下载: {args.output}（{lines} 行结果）")


def cmd_cancel(args: argparse.Namespace) -> None:
    client = _client()
    batch_id = _load_id(args)
    batch = client.batches.cancel(batch_id)
    print(f"已请求取消: {batch_id}，当前状态: {_describe(batch)}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="智谱批量任务提交与结果获取")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="最近批量任务")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("submit", help="上传请求 JSONL 并创建批量任务")
    p.add_argument("--input", type=Path, default=_DEFAULT_INPUT)
    p.set_defaults(fn=cmd_submit)

    p = sub.add_parser("cancel", help="取消批量任务")
    p.add_argument("--batch-id", dest="batch_id", help="缺省读 批量任务_id.txt")
    p.set_defaults(fn=cmd_cancel)

    for name, help_ in (("wait", "轮询直到任务结束"), ("download", "下载结果 JSONL")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--batch-id", dest="batch_id", help="缺省读 批量任务_id.txt")
        if name == "wait":
            p.add_argument("--interval", type=float, default=20.0, help="轮询间隔秒")
            p.add_argument("--timeout", type=float, default=7200.0, help="最长等待秒")
        else:
            p.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
        p.set_defaults(fn={"wait": cmd_wait, "download": cmd_download}[name])

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
