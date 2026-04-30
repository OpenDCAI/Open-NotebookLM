from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "run_local_qwen35_c500_server.sh"


def test_launch_script_uses_thinkflow_vendor_project_defaults():
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'ROOT="${LOCAL_QWEN35_C500_PROJECT_ROOT:-${SCRIPT_DIR}}"' in text
    assert 'VENV="${LOCAL_QWEN35_C500_VENV:-${ROOT}/.venv}"' in text
    assert 'LOCAL_QWEN35_C500_MODEL_DIR="${LOCAL_QWEN35_C500_MODEL_DIR:-${ROOT}/models/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled}"' in text
    assert 'LOCAL_QWEN35_C500_VISIBLE_GPUS="${LOCAL_QWEN35_C500_VISIBLE_GPUS:-0,1,2,3}"' in text
    assert 'LOCAL_QWEN35_C500_PORT="${LOCAL_QWEN35_C500_PORT:-18081}"' in text


def test_launch_script_explains_where_to_download_model():
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "config.json" in text
    assert "LOCAL_QWEN35_C500_MODEL_DIR" in text
    assert "models/Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled" in text
