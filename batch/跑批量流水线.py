"""批量任务 → 下载结果 → 跑完后续流水线。

读 data/raw/批量任务_id.txt 里的 batch id，轮询状态直到完成，把结果下载为
data/batch/batch_results_processed.jsonl，再依次执行：
    提数据_插标的物 → 统计数据_插交易频次 → 建知识图谱_导CSV

用法:
    uv run python batch/跑批量流水线.py                 # 等待并跑完整链路
    uv run python batch/跑批量流水线.py --batch-id batch_xxx
    uv run python batch/跑批量流水线.py --no-wait       # 只查一次状态，未完成即退出
    uv run python batch/跑批量流水线.py --download-only # 只下载结果，不跑后续
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from openai import OpenAI

_ROOT = Path(__file__).resolve().parents[1]
_ID_FILE = _ROOT / "data" / "raw" / "批量任务_id.txt"
_RESULT = _ROOT / "data" / "batch" / "batch_results_processed.jsonl"
_POLL_INTERVAL = 30.0
_MAX_POLLS = 40
_DONE = ("completed", "failed", "cancelled", "expired")

# 下游顺序固定：插标的物 → 统计频次 → 导知识图谱 CSV
_DOWNSTREAM = ("提数据_插标的物.py", "统计数据_插交易频次.py", "建知识图谱_导CSV.py")


def _client() -> OpenAI:
    from rag_agent.config import get_settings

    s = get_settings()
    return OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=180, max_retries=2)


def _resolve_id(arg: str | None) -> str:
    if arg:
        return arg.strip()
    if _ID_FILE.exists():
        value = _ID_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    raise SystemExit(f"未指定 batch id，且 {_ID_FILE} 不存在或为空")


def _wait(client: OpenAI, batch_id: str, wait: bool):
    """轮询到终态并返回 batch 对象；--no-wait 时查一次就返回。"""
    for i in range(1, _MAX_POLLS + 1):
        b = client.batches.retrieve(batch_id)
        c = b.request_counts
        print(f"[{i}/{_MAX_POLLS}] status={b.status} "
              f"completed={c.completed}/{c.total} failed={c.failed}")
        if b.status in _DONE:
            return b
        if not wait:
            raise SystemExit("任务尚未完成（--no-wait 只查一次，稍后重跑）")
        if i < _MAX_POLLS:
            time.sleep(_POLL_INTERVAL)
    raise SystemExit(f"轮询 {_MAX_POLLS} 次仍未完成，稍后重跑本脚本即可")


def _download(client: OpenAI, b) -> Path:
    if b.status != "completed":
        if b.error_file_id:
            try:
                print("--- error file ---")
                print(client.files.content(b.error_file_id).text[:1500])
            except Exception as e:  # noqa: BLE001 —— 错误详情只是辅助信息
                print(f"(读取错误文件失败: {e})")
        raise SystemExit(f"任务终态为 {b.status}，无法下载结果")
    if not b.output_file_id:
        raise SystemExit("任务已完成但没有 output_file_id")
    _RESULT.parent.mkdir(parents=True, exist_ok=True)
    client.files.content(b.output_file_id).write_to_file(str(_RESULT))
    lines = sum(1 for _ in _RESULT.open(encoding="utf-8"))
    print(f"结果已保存: {_RESULT}（{lines} 行，{_RESULT.stat().st_size / 1024:.1f} KB）")
    return _RESULT


def _run_downstream() -> None:
    for name in _DOWNSTREAM:
        path = Path(__file__).parent / name
        if not path.exists():
            raise SystemExit(f"下游脚本不存在: {path}")
        print(f"\n>>> {name}")
        r = subprocess.run([sys.executable, str(path)], cwd=str(_ROOT))
        if r.returncode != 0:
            raise SystemExit(f"{name} 失败（退出码 {r.returncode}），后续步骤不执行")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.chdir(_ROOT)  # 让 config 能找到 .env
    ap = argparse.ArgumentParser(description="等待批量任务完成并跑完后续流水线")
    ap.add_argument("--batch-id", help="批量任务 id（默认读 data/raw/批量任务_id.txt）")
    ap.add_argument("--no-wait", action="store_true", help="只查一次状态，不阻塞")
    ap.add_argument("--download-only", action="store_true", help="只下载结果，不跑后续脚本")
    args = ap.parse_args()

    batch_id = _resolve_id(args.batch_id)
    print(f"batch id = {batch_id}")
    client = _client()
    b = _wait(client, batch_id, wait=not args.no_wait)
    _download(client, b)
    if not args.download_only:
        _run_downstream()
        print("\n全部完成。")


if __name__ == "__main__":
    main()
