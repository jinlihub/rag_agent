"""以脱离控制台的方式启动 PostgreSQL（供 启动PG.bat 调用）。

pg_ctl 启动的 postgres 会留在当前控制台的进程组里，用户按 Ctrl+C 会把
postgres 一起杀掉（日志里的 0xC000013A）。这里用 DETACHED_PROCESS 启动，
postgres 拥有独立会话，不受终端按键影响。
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

PG_BIN = Path(r"D:\MySoftware\Anaconda3\envs\pg\Library\bin")
DATA = Path(r"D:\pgdata")
LOG = DATA / "server.log"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
CREATE_BREAKAWAY_FROM_JOB = 0x01000000  # 尝试脱离调用方的作业对象（父进程若不允许会失败，需降级重试）


def port_open() -> bool:
    s = socket.socket()
    s.settimeout(2)
    try:
        return s.connect_ex(("127.0.0.1", 5432)) == 0
    finally:
        s.close()


def main() -> int:
    if port_open():
        print("PostgreSQL 已在运行（5432 已监听），无需启动。")
        return 0

    pid_file = DATA / "postmaster.pid"
    if pid_file.exists():
        lines = pid_file.read_text(errors="replace").strip().splitlines()
        pid = lines[0].strip() if lines else ""
        alive = False
        if pid.isdigit():
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, errors="replace",
            ).stdout
            alive = pid in out
        if alive:
            print(f"postgres 进程仍在（PID {pid}），等待端口就绪…")
            for _ in range(10):
                if port_open():
                    print("已就绪。")
                    return 0
                time.sleep(1)
        else:
            pid_file.unlink()
            print("清理了残留的 postmaster.pid")

    log_handle = open(LOG, "ab", buffering=0)
    args = [str(PG_BIN / "postgres.exe"), "-D", str(DATA)]
    try:
        # 优先脱离调用方的作业对象，避免终端/父进程退出时被连带终止
        proc = subprocess.Popen(
            args,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
            | CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True,
        )
    except OSError:
        # 父进程的作业对象不允许 breakaway 时退回普通分离模式
        proc = subprocess.Popen(
            args,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
            close_fds=True,
        )
    print(f"已启动 postgres（PID {proc.pid}），等待就绪…")

    for _ in range(15):
        time.sleep(1)
        if port_open():
            print("PostgreSQL 已就绪，端口 5432 监听中。")
            return 0
        if proc.poll() is not None:
            print(f"启动失败，退出码 {proc.returncode}，见日志 {LOG}")
            return 1

    print("启动超时，请查看日志。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
