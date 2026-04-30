#!/bin/bash
# ThinkFlow — 仅前台启动前端，适合单独开终端看报错
# 用法: ./scripts/start_frontend_dev.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT/frontend_zh"

NPM_BIN="$(command -v npm 2>/dev/null)" || {
    echo "错误: 找不到 npm" >&2
    exit 1
}

FRONTEND_PORT="${FRONTEND_PORT:-3003}"

echo "前台启动 ThinkFlow 前端..."
echo "NPM: ${NPM_BIN}"
echo "Frontend: http://127.0.0.1:${FRONTEND_PORT}"
echo "Proxy backend: http://127.0.0.1:8213"
echo "停止: Ctrl+C"

if command -v fuser >/dev/null 2>&1 && fuser "${FRONTEND_PORT}/tcp" >/dev/null 2>&1; then
    echo "错误: 前端端口 ${FRONTEND_PORT} 已被占用，请先停止现有前端进程。" >&2
    exit 1
fi

exec "$NPM_BIN" run dev -- --port "${FRONTEND_PORT}" --host 0.0.0.0 --strictPort
