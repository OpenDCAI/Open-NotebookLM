import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "local_qwen35_c500_server.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("local_qwen35_c500_server", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_visible_gpus_supports_multiple_devices():
    module = _load_module()

    assert module._parse_visible_gpus("0,2,4") == [0, 2, 4]


def test_parse_visible_gpus_defaults_to_single_gpu_when_empty():
    module = _load_module()

    assert module._parse_visible_gpus("") == [0]


def test_default_model_dir_points_to_vendored_models_dir():
    module = _load_module()

    expected = MODULE_PATH.parent / "models" / "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled"
    assert module.DEFAULT_MODEL_DIR == str(expected)


def test_remap_visible_gpus_for_process_local_indices():
    module = _load_module()

    assert module._remap_visible_gpus_for_process([0, 1, 4, 5], "0,1,4,5") == [0, 1, 2, 3]
    assert module._remap_visible_gpus_for_process([0, 1, 2, 3], "") == [0, 1, 2, 3]


def test_render_prompt_prefills_json_object_for_json_mode():
    module = _load_module()

    prompt = module._render_prompt(
        [{"role": "user", "content": "Return a JSON object."}],
        {"type": "json_object"},
    )

    assert "Start immediately with {" in prompt
    assert prompt.endswith("<|im_start|>assistant\n{")


def test_postprocess_content_recovers_json_body_after_object_prefill():
    module = _load_module()

    content = module._postprocess_content(
        '\n"title": "Deck title", "items": ["a", "b"]\n}',
        json_mode=True,
    )

    assert json.loads(content) == {"title": "Deck title", "items": ["a", "b"]}
