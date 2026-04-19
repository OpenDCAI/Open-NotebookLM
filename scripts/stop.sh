#!/bin/bash
# ThinkFlow — 停止所有服务

echo "停止服务..."

BACKEND_PORT=18213
FRONTEND_PORT=13001

kill_port() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti:"${port}" | xargs kill -9 2>/dev/null || true
        return 0
    fi
    if command -v fuser >/dev/null 2>&1; then
        fuser -k "${port}"/tcp 2>/dev/null || true
    fi
}

kill_port "${BACKEND_PORT}"
kill_port "${FRONTEND_PORT}"
pkill -9 -f "uvicorn fastapi_app.main:app" 2>/dev/null || true
pkill -9 -f "vite.*--port ${FRONTEND_PORT}" 2>/dev/null || true
pkill -9 -f "bash scripts/monitor.sh"      2>/dev/null || true
tmux kill-session -t thinkflow             2>/dev/null || true

echo "已停止。"
