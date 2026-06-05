#!/usr/bin/env bash
# 启动本地 OpenAI-compatible embedding API 服务
# 用法: bash start_4b.sh [port] [gpu_mem]
# 示例: bash start_4b.sh 8899 0.8

PORT="${1:-8899}"
GPU_MEM="${2:-0.8}"
MODEL_PATH="${EMBEDDING_MODEL:-/root/user/ldh/models/Qwen3-Embedding-0.6B}"
EMBEDDING_PYTHON_BIN="${EMBEDDING_PYTHON_BIN:-/opt/conda/bin/python}"

export TORCHDYNAMO_DISABLE=1
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
export HF_ENDPOINT=https://hf-mirror.com
export EMBEDDING_MODEL="${MODEL_PATH}"

# 检查 config.json 是否已 patch
ARCH=$("${EMBEDDING_PYTHON_BIN}" -c "import json; print(json.load(open('${MODEL_PATH}/config.json'))['architectures'][0])")
if [ "$ARCH" != "Qwen3ForCausalLM" ]; then
    echo "Patching config.json: ${ARCH} -> Qwen3ForCausalLM"
    "${EMBEDDING_PYTHON_BIN}" -c "
import json
cfg = json.load(open('${MODEL_PATH}/config.json'))
cfg['architectures'] = ['Qwen3ForCausalLM']
json.dump(cfg, open('${MODEL_PATH}/config.json', 'w'), indent=2)
"
fi

echo "Model:    ${MODEL_PATH}"
echo "Python:   ${EMBEDDING_PYTHON_BIN}"
echo "Port:     ${PORT}"
echo "GPU mem:  ${GPU_MEM}"
echo "---"

exec "${EMBEDDING_PYTHON_BIN}" -m uvicorn scripts.local_embedding_server:app \
    --host 0.0.0.0 \
    --port "${PORT}"
