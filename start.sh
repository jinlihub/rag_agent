#!/usr/bin/env bash
# 一键启动开发环境：FastAPI 后端 + Vite 前端
#
# 用法（git-bash / Linux / macOS）:
#   bash start.sh            启动（已在运行的服务跳过），就绪后自动打开浏览器
#   bash start.sh stop       停止前后端
#   bash start.sh restart    重启
#   bash start.sh status     查看运行状态
#
# 日志与 PID 存放在 .run/；Windows 下通过命令行匹配停止服务，与启动方式无关。
set -u
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
RUN="$ROOT/.run"; mkdir -p "$RUN"

BACKEND_PORT=8000
FRONTEND_PORT=5173
BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
FRONTEND_URL="http://localhost:$FRONTEND_PORT"
CHAT_URL="$FRONTEND_URL/chat"

log() { printf '%s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }

backend_up()  { curl -sf -m 2 "$BACKEND_URL/api/health" 2>/dev/null | grep -q '"status"'; }
# Vite 7 默认只绑 IPv6 回环（::1），必须用 localhost 而非 127.0.0.1 探测
frontend_up() { curl -sf -m 2 -o /dev/null "$FRONTEND_URL/" 2>/dev/null; }

ensure_deps() {
  [ -d "$ROOT/.venv" ] || { log "首次运行：安装后端依赖 (uv sync)…"; uv sync || die "uv sync 失败"; }
  [ -d "$ROOT/frontend/node_modules" ] || {
    log "首次运行：安装前端依赖 (npm install)…"
    (cd frontend && npm install) || die "npm install 失败"
  }
}

start_backend() {
  if backend_up; then log "✓ 后端已在运行  $BACKEND_URL"; return 0; fi
  log "启动后端 → $BACKEND_URL （日志 .run/backend.log）"
  nohup uv run uvicorn rag_agent.api.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload \
    >"$RUN/backend.log" 2>&1 &
  echo $! >"$RUN/backend.pid"
}

start_frontend() {
  if frontend_up; then log "✓ 前端已在运行  $FRONTEND_URL"; return 0; fi
  log "启动前端 → $FRONTEND_URL （日志 .run/frontend.log）"
  (cd frontend && nohup npm run dev >"$RUN/frontend.log" 2>&1) &
  echo $! >"$RUN/frontend.pid"
}

wait_for() { # $1 名称  $2 检测函数名
  local i=0
  until "$2"; do
    i=$((i + 1))
    [ "$i" -gt 60 ] && die "$1 等待超时（60s），请查看 .run 下的日志"
    sleep 1
  done
  log "✓ $1 就绪"
}

open_browser() {
  case "$(uname -s)" in
    # //c 双斜杠防止 MSYS 把 /c 改写成 C:\ 路径
    MINGW* | MSYS* | CYGWIN*) cmd.exe //c start '""' "$1" ;;
    Darwin*) open "$1" ;;
    *) command -v xdg-open >/dev/null 2>&1 && xdg-open "$1" ;;
  esac
}

stop_win() { # $1 powershell CommandLine -match 正则（排除 powershell 自身防误杀）
  powershell.exe -NoProfile -Command "
    \$ps = Get-CimInstance Win32_Process -Filter \"Name != 'powershell.exe'\" |
      Where-Object { \$_.CommandLine -match '$1' }
    foreach (\$p in \$ps) { taskkill /F /T /PID \$p.ProcessId 2>\$null | Out-Null }
  " >/dev/null 2>&1 || true
}

do_stop() {
  # 按命令行特征结束进程（/T 连子进程树）；注意：全机范围匹配 uvicorn/vite/npm run dev
  log "停止后端…"
  stop_win 'rag_agent\.api\.main'
  log "停止前端…"
  stop_win 'vite[\\/]bin[\\/]vite\.js'     # vite 实际命令行带 node_modules\.bin\..\，不能用 node_modules[\\/]vite 匹配
  stop_win 'npm[\\/]bin[\\/]npm-cli\.js'   # npm run dev 包装进程
  for f in backend.pid frontend.pid; do
    if [ -f "$RUN/$f" ]; then
      kill "$(cat "$RUN/$f")" 2>/dev/null || true
      rm -f "$RUN/$f"
    fi
  done
  local i=0
  while backend_up || frontend_up; do
    i=$((i + 1)); [ "$i" -gt 10 ] && break
    sleep 1
  done
  log "✓ 已停止"
}

do_status() {
  backend_up  && log "✓ 后端  $BACKEND_URL"  || log "✗ 后端未运行"
  frontend_up && log "✓ 前端  $FRONTEND_URL" || log "✗ 前端未运行"
}

do_start() {
  ensure_deps
  start_backend
  start_frontend
  log "等待服务就绪…"
  wait_for "后端" backend_up
  wait_for "前端" frontend_up
  log "✓ 全部就绪 → $CHAT_URL （登录 admin / admin123）"
  open_browser "$CHAT_URL"
}

case "${1:-start}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; sleep 1; do_start ;;
  status)  do_status ;;
  *)       die "用法: bash start.sh [start|stop|restart|status]" ;;
esac
