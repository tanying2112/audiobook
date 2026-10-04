#!/usr/bin/env bash
# 一键启动 Audiobook Studio：Redis + 后端 + 前端
#
# 用法:
#   ./scripts/dev/start_dev.sh          # 启动全部
#   ./scripts/dev/start_dev.sh stop     # 停止全部
#   ./scripts/dev/start_dev.sh status   # 查看状态
#
# 不做开机自启，只在启动项目前端时按需拉起 Redis（以及后端）。

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BACKEND_PORT=8000
FRONTEND_PORT=5173
REDIS_PORT=6379

REDIS_SERVER="$(command -v redis-server || true)"
REDIS_CLI="$(command -v redis-cli || true)"

PID_DIR="$ROOT/.dev_pids"
mkdir -p "$PID_DIR"

BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"
REDIS_PID_FILE="$PID_DIR/redis.pid"

# ── 工具函数 ──────────────────────────────────────────────────────────────

log()  { printf '\033[1;32m[dev]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[dev]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[dev]\033[0m %s\n' "$*"; }

is_port_open() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti:"$port" >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null && { exec 3>&- 3<&-; return 0; } || return 1
  fi
}

redis_running() {
  if [ -n "$REDIS_CLI" ] && "$REDIS_CLI" -p "$REDIS_PORT" ping >/dev/null 2>&1; then
    return 0
  fi
  is_port_open "$REDIS_PORT"
}

# ── 启动 Redis ────────────────────────────────────────────────────────────

start_redis() {
  if redis_running; then
    log "Redis 已在运行 (端口 $REDIS_PORT)"
    return 0
  fi
  if [ -z "$REDIS_SERVER" ]; then
    err "未找到 redis-server，请先安装: brew install redis"
    return 1
  fi
  log "启动 Redis ..."
  "$REDIS_SERVER" --daemonize yes --port "$REDIS_PORT" \
    --pidfile "$REDIS_PID_FILE" \
    --dir "$ROOT" 2>&1 | tail -3
  sleep 1
  if redis_running; then
    log "Redis 启动成功"
  else
    warn "Redis 可能未启动，请检查日志"
  fi
}

# ── 启动后端 ──────────────────────────────────────────────────────────────

start_backend() {
  if is_port_open "$BACKEND_PORT"; then
    log "后端已在运行 (端口 $BACKEND_PORT)"
    return 0
  fi
  log "启动后端 (端口 $BACKEND_PORT) ..."
  if command -v uv >/dev/null 2>&1; then
    nohup uv run uvicorn src.audiobook_studio.main:app \
      --host 0.0.0.0 --port "$BACKEND_PORT" \
      > "$ROOT/backend.log" 2>&1 &
  else
    nohup python -m uvicorn src.audiobook_studio.main:app \
      --host 0.0.0.0 --port "$BACKEND_PORT" \
      > "$ROOT/backend.log" 2>&1 &
  fi
  echo $! > "$BACKEND_PID_FILE"
  sleep 3
  if is_port_open "$BACKEND_PORT"; then
    log "后端启动成功 → http://localhost:$BACKEND_PORT"
  else
    warn "后端可能启动失败，请查看 backend.log"
  fi
}

# ── 启动前端 ──────────────────────────────────────────────────────────────

start_frontend() {
  if is_port_open "$FRONTEND_PORT"; then
    log "前端已在运行 (端口 $FRONTEND_PORT)"
    return 0
  fi
  log "启动前端 (端口 $FRONTEND_PORT) ..."
  if [ ! -d "$ROOT/web" ]; then
    err "未找到 web/ 目录"
    return 1
  fi
  (
    cd "$ROOT/web"
    nohup npm run dev > "$ROOT/frontend.log" 2>&1 &
    echo $! > "$FRONTEND_PID_FILE"
  )
  sleep 3
  if is_port_open "$FRONTEND_PORT"; then
    log "前端启动成功 → http://localhost:$FRONTEND_PORT"
  else
    warn "前端可能启动失败，请查看 frontend.log"
  fi
}

# ── 停止 ─────────────────────────────────────────────────────────────────

stop_by_pidfile() {
  local pidfile="$1" name="$2"
  if [ -f "$pidfile" ]; then
    local pid
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && log "已停止 $name (pid $pid)"
    fi
    rm -f "$pidfile"
  fi
}

stop_all() {
  log "停止服务 ..."
  stop_by_pidfile "$BACKEND_PID_FILE" "后端"
  stop_by_pidfile "$FRONTEND_PID_FILE" "前端"

  # 停止 Redis（若通过本项目启动）
  if [ -f "$REDIS_PID_FILE" ]; then
    local pid
    pid="$(cat "$REDIS_PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && log "已停止 Redis (pid $pid)"
    fi
    rm -f "$REDIS_PID_FILE"
  fi

  # 兜底：按端口清理
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti:"$BACKEND_PORT"  | xargs kill 2>/dev/null || true
    lsof -ti:"$FRONTEND_PORT" | xargs kill 2>/dev/null || true
  fi
  log "全部已停止"
}

status_all() {
  echo "── 服务状态 ──"
  if is_port_open "$BACKEND_PORT"; then
    printf '  %-10s %s\n' "后端" "✅ 运行中 (http://localhost:$BACKEND_PORT)"
  else
    printf '  %-10s %s\n' "后端" "❌ 未运行"
  fi
  if is_port_open "$FRONTEND_PORT"; then
    printf '  %-10s %s\n' "前端" "✅ 运行中 (http://localhost:$FRONTEND_PORT)"
  else
    printf '  %-10s %s\n' "前端" "❌ 未运行"
  fi
  if redis_running; then
    printf '  %-10s %s\n' "Redis" "✅ 运行中 (端口 $REDIS_PORT)"
  else
    printf '  %-10s %s\n' "Redis" "❌ 未运行"
  fi
}

# ── 主流程 ───────────────────────────────────────────────────────────────

case "${1:-start}" in
  start)
    log "启动 Audiobook Studio 开发环境"
    start_redis
    start_backend
    start_frontend
    log "全部就绪：前端 http://localhost:$FRONTEND_PORT / 后端 http://localhost:$BACKEND_PORT/docs"
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    sleep 1
    "$0" start
    ;;
  status)
    status_all
    ;;
  *)
    echo "用法: $0 {start|stop|restart|status}"
    exit 1
    ;;
esac