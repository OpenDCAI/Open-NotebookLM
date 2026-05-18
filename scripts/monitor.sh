#!/bin/bash
# ThinkFlow — 监控并自动重启前后端服务

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p logs

BACKEND_PORT=8000
FRONTEND_PORT=3001
EMBEDDING_PORT=8899
BACKEND_HEALTH_URL="http://127.0.0.1:${BACKEND_PORT}/health"
FRONTEND_HEALTH_URL="http://127.0.0.1:${FRONTEND_PORT}/"
EMBEDDING_HEALTH_URL="http://127.0.0.1:${EMBEDDING_PORT}/health"
LOCK_FILE="$PROJECT_ROOT/logs/monitor.lock"
STARTUP_GRACE_SECONDS=15
# paper2video continue（refine+TTS+ffmpeg）常超过 2 分钟；过短会在长任务中途误杀后端
BACKEND_STARTUP_TIMEOUT=900
FRONTEND_STARTUP_TIMEOUT=60
EMBEDDING_STARTUP_TIMEOUT=180
MONITOR_INITIALIZED=0

PYTHON_BIN="${PYTHON_BIN:-}"
NPM_BIN="${NPM_BIN:-$(command -v npm 2>/dev/null || true)}"

# 解析 Python（优先 conda 环境）
if [[ -z "$PYTHON_BIN" ]]; then
    for candidate in \
        "/mnt/paper2any/conda-envs/envs/thinkflow2/bin/python" \
        "/mnt/paper2any/conda-envs/envs/thinkflow/bin/python" \
        "${CONDA_PREFIX:-}/bin/python" \
        "/root/miniconda3/envs/szl-dev/bin/python" \
        "$(command -v python3 2>/dev/null || true)" \
        "$(command -v python  2>/dev/null || true)"
    do
        [[ -x "$candidate" ]] && PYTHON_BIN="$candidate" && break
    done
fi

[[ -z "$PYTHON_BIN" ]] && { echo "[$(date)] No Python found" >> logs/monitor.log; exit 1; }
[[ -z "$NPM_BIN"    ]] && { echo "[$(date)] No npm found"    >> logs/monitor.log; exit 1; }

# 防止重复监控
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock -n 9 || { echo "[$(date)] Monitor already running" >> logs/monitor.log; exit 0; }
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> logs/monitor.log; }

is_port_up()   { ss -tlnH "sport = :$1" 2>/dev/null | grep -q LISTEN; }
# paper2video / MinerU 等重任务可能短暂占用线程池；过短超时易误判为宕机并杀死正在跑的长请求。
http_ok()       { curl --max-time 25 -fsS -o /dev/null "$1"; }
proc_age()      { ps -o etimes= -p "$1" 2>/dev/null | awk '{print $1}'; }
find_backend()  { pgrep -f "uvicorn fastapi_app.main:app.*--port ${BACKEND_PORT}" | head -1; }
find_frontend() { pgrep -f "vite.*--port ${FRONTEND_PORT}" | head -1; }
find_embedding(){ pgrep -f "start_embedding_4b.sh" | head -1; }

restart_backend() {
    log "Backend down — restarting"
    pkill -9 -f "uvicorn fastapi_app.main:app" 2>/dev/null || true
    sleep 2
    nohup "$PYTHON_BIN" -m uvicorn fastapi_app.main:app \
        --host 0.0.0.0 --port "$BACKEND_PORT" >> logs/backend.log 2>&1 &
    log "Backend restarted PID=$!"
}

restart_frontend() {
    log "Frontend down — restarting"
    pkill -9 -f "vite.*--port ${FRONTEND_PORT}" 2>/dev/null || true
    sleep 2
    (
        cd "$PROJECT_ROOT/frontend"
        nohup "$NPM_BIN" run dev -- --port "$FRONTEND_PORT" --host 0.0.0.0 \
            >> "$PROJECT_ROOT/logs/frontend.log" 2>&1 &
        log "Frontend restarted PID=$!"
    )
}

restart_embedding() {
    log "Embedding down — restarting"
    pkill -9 -f "start_embedding_4b.sh" 2>/dev/null || true
    sleep 2
    nohup bash "$PROJECT_ROOT/scripts/start_embedding_4b.sh" "$EMBEDDING_PORT" 0.8 \
        >> "$PROJECT_ROOT/logs/embedding.log" 2>&1 &
    log "Embedding restarted PID=$!"
}

log "Monitor started"

while true; do
    if [[ "$MONITOR_INITIALIZED" -eq 0 ]]; then
        sleep "$STARTUP_GRACE_SECONDS"
        MONITOR_INITIALIZED=1
    fi

    # Backend 健康检查
    if ! is_port_up "$BACKEND_PORT" || ! http_ok "$BACKEND_HEALTH_URL"; then
        pid="$(find_backend || true)"
        age="$([ -n "$pid" ] && proc_age "$pid" || echo 9999)"
        if [[ -n "$pid" && "${age:-9999}" -lt "$BACKEND_STARTUP_TIMEOUT" ]]; then
            log "Backend starting (PID=$pid age=${age}s) — skip"
        else
            restart_backend
        fi
    fi

    # Frontend 健康检查
    if ! is_port_up "$FRONTEND_PORT" || ! http_ok "$FRONTEND_HEALTH_URL"; then
        pid="$(find_frontend || true)"
        age="$([ -n "$pid" ] && proc_age "$pid" || echo 9999)"
        if [[ -n "$pid" && "${age:-9999}" -lt "$FRONTEND_STARTUP_TIMEOUT" ]]; then
            log "Frontend starting (PID=$pid age=${age}s) — skip"
        else
            restart_frontend
        fi
    fi

    # Embedding 健康检查
    if ! is_port_up "$EMBEDDING_PORT"; then
        pid="$(find_embedding || true)"
        age="$([ -n "$pid" ] && proc_age "$pid" || echo 9999)"
        if [[ -n "$pid" && "${age:-9999}" -lt "$EMBEDDING_STARTUP_TIMEOUT" ]]; then
            log "Embedding starting (PID=$pid age=${age}s) — skip"
        else
            restart_embedding
        fi
    fi

    sleep 30
done
