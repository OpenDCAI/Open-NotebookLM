#!/bin/bash
# ThinkFlow — 仅前台启动后端，适合单独开终端看报错
# 用法: ./scripts/start_backend_dev.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

resolve_python() {
    local candidates=(
        "/mnt/paper2any/dingcheng/conda-envs/thinkflow/bin/python"
        "/mnt/paper2any/conda-envs/envs/thinkflow/bin/python"
        "${CONDA_PREFIX:-}/bin/python"
        "$(command -v python3 2>/dev/null || true)"
        "$(command -v python 2>/dev/null || true)"
    )
    for p in "${candidates[@]}"; do
        [[ -x "$p" ]] && echo "$p" && return 0
    done
    echo "错误: 找不到可用的 Python" >&2
    return 1
}

PYTHON_BIN="$(resolve_python)"
BACKEND_PORT=8213

echo "前台启动 ThinkFlow 后端..."
echo "Python: ${PYTHON_BIN}"
echo "Backend: http://127.0.0.1:${BACKEND_PORT}"
echo "停止: Ctrl+C"

exec "$PYTHON_BIN" -m uvicorn fastapi_app.main:app \
    --host 0.0.0.0 \
    --port "${BACKEND_PORT}"
