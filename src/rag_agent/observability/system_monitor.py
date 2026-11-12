"""系统监控指标采集：CPU / 内存 / 磁盘 / GPU / 进程 / 近期日志。

全部在本机采集，不依赖外部服务：
  - CPU、内存、磁盘、进程、启动时间用 psutil；
  - GPU 调 nvidia-smi；没有 NVIDIA 显卡或未安装驱动时返回 available=false，
    其余指标照常返回（监控页不能因为单个指标缺失整体失败）；
  - 日志用进程内环形缓冲区，最多保留 500 条 root / rag_agent / uvicorn 日志。
"""

from __future__ import annotations

import logging
import platform
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

_LOG_CAPACITY = 500
_LOG_LIMIT_MAX = 500

# 进程指标需要跨请求保留 cpu_percent 的采样基线；首次调用返回 0，后续才有意义
_PROCESS = psutil.Process()
_PROCESS.cpu_percent(interval=None)


class _RingLogHandler(logging.Handler):
    """内存环形日志缓冲；同一 record 被多个 logger 传播时只记录一次。"""

    def __init__(self, capacity: int = _LOG_CAPACITY) -> None:
        super().__init__()
        self._records: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "_system_monitor_seen", False):
            return
        record._system_monitor_seen = True
        try:
            message = record.getMessage()
            # 监控页每 5 秒轮询一次，自身访问日志会把真正的日志挤出缓冲区
            if record.name == "uvicorn.access" and "/api/admin/system" in message:
                return
            entry = {
                "time": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": message[:4000],
            }
            with self._lock:
                self._records.append(entry)
        except Exception:  # noqa: BLE001 —— 日志采集失败不能影响业务日志本身
            self.handleError(record)

    def snapshot(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._records)
        if limit <= 0:
            return []
        return items[-limit:]


_LOG_HANDLER = _RingLogHandler()
_LOG_INSTALLED = False


def install_log_capture() -> None:
    """把环形日志处理器挂到应用与 uvicorn logger；重复调用只安装一次。"""
    global _LOG_INSTALLED
    if _LOG_INSTALLED:
        return
    _LOG_INSTALLED = True
    _LOG_HANDLER.setLevel(logging.INFO)
    for name in ("", "rag_agent", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.addHandler(_LOG_HANDLER)
        # root 默认 WARNING 会把 rag_agent 的 INFO 过滤掉，显式放开应用日志
        if name == "rag_agent" and logger.level == logging.NOTSET:
            logger.setLevel(logging.INFO)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def _cpu_metrics() -> dict[str, Any]:
    percent = psutil.cpu_percent(interval=0.1)
    per_core = psutil.cpu_percent(percpu=True, interval=None)
    return {
        "percent": round(percent, 1),
        "per_core": [round(v, 1) for v in per_core],
        "logical": psutil.cpu_count(logical=True) or 0,
        "physical": psutil.cpu_count(logical=False) or 0,
    }


def _memory_metrics() -> tuple[dict[str, Any], dict[str, Any]]:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    memory = {
        "total": mem.total,
        "used": mem.used,
        "available": mem.available,
        "percent": round(mem.percent, 1),
    }
    swap_info = {
        "total": swap.total,
        "used": swap.used,
        "percent": round(swap.percent, 1),
    }
    return memory, swap_info


def _disk_metrics() -> dict[str, Any]:
    root = Path.cwd().anchor or "/"
    try:
        usage = psutil.disk_usage(root)
        total, used, free, percent = usage.total, usage.used, usage.free, usage.percent
    except OSError:
        total = used = free = 0
        percent = 0.0

    partitions: list[dict[str, Any]] = []
    try:
        parts = psutil.disk_partitions(all=False)
    except OSError:
        parts = []
    for part in parts:
        if not part.fstype:
            continue  # Windows 光驱/空读卡器没有文件系统
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        partitions.append(
            {
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": u.total,
                "used": u.used,
                "free": u.free,
                "percent": round(u.percent, 1),
            }
        )
    return {
        "path": root,
        "total": total,
        "used": used,
        "free": free,
        "percent": round(percent, 1),
        "partitions": partitions[:12],
    }


def _to_num(value: str, cast: type) -> float | int | None:
    try:
        return cast(value.strip())
    except (TypeError, ValueError):
        return None


def _gpu_metrics() -> dict[str, Any]:
    """通过 nvidia-smi 读取 NVIDIA GPU；缺失时返回可读说明而不是报错。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {
            "available": False,
            "message": "未检测到 nvidia-smi（本机可能没有 NVIDIA GPU 或未安装驱动）",
            "items": [],
        }
    cmd = [
        exe,
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return {"available": False, "message": f"nvidia-smi 调用失败：{e}", "items": []}

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        return {"available": False, "message": f"nvidia-smi 返回 {proc.returncode}：{detail}", "items": []}

    items: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",", 5)]
        if len(parts) < 6:
            continue
        items.append(
            {
                "index": _to_num(parts[0], int),
                "name": parts[1],
                "utilization": _to_num(parts[2], float),
                "memory_used": _to_num(parts[3], int),
                "memory_total": _to_num(parts[4], int),
                "temperature": _to_num(parts[5], int),
            }
        )
    return {
        "available": bool(items),
        "message": "" if items else "nvidia-smi 未返回 GPU 信息",
        "items": items,
    }


def _host_metrics() -> dict[str, Any]:
    boot = psutil.boot_time()
    load_avg: list[float] | None = None
    try:
        load_avg = [round(v, 2) for v in psutil.getloadavg()]
    except (AttributeError, OSError):
        pass
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "boot_time": _iso(boot),
        "uptime_seconds": int(time.time() - boot),
        "load_avg": load_avg,
    }


def _process_metrics() -> dict[str, Any]:
    with _PROCESS.oneshot():
        mem = _PROCESS.memory_info()
        create_time = _PROCESS.create_time()
        return {
            "pid": _PROCESS.pid,
            "name": _PROCESS.name(),
            "cpu_percent": round(_PROCESS.cpu_percent(interval=None), 1),
            "memory_rss": mem.rss,
            "memory_percent": round(_PROCESS.memory_percent(), 1),
            "threads": _PROCESS.num_threads(),
            "create_time": _iso(create_time),
            "uptime_seconds": int(time.time() - create_time),
        }


def get_system_metrics(log_limit: int = 100) -> dict[str, Any]:
    """采集一次系统监控快照；所有指标均应可序列化为 JSON。"""
    limit = max(0, min(log_limit, _LOG_LIMIT_MAX))
    memory, swap = _memory_metrics()
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "host": _host_metrics(),
        "cpu": _cpu_metrics(),
        "memory": memory,
        "swap": swap,
        "disk": _disk_metrics(),
        "gpu": _gpu_metrics(),
        "process": _process_metrics(),
        "logs": _LOG_HANDLER.snapshot(limit),
    }
