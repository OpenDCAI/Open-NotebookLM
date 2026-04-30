import importlib.util
from pathlib import Path


def _load_server_module():
    module_path = Path(__file__).resolve().parents[1] / "local_qwen35_c500_server.py"
    spec = importlib.util.spec_from_file_location("local_qwen35_c500_server", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_default_completion_budget_is_capped_when_request_omits_max_tokens():
    server = _load_server_module()

    max_new_tokens = server._resolve_max_new_tokens(
        prompt_tokens=6042,
        context_window=262144,
        configured_cap=262144,
        request_max_tokens=None,
        json_mode=False,
    )

    assert max_new_tokens == server.DEFAULT_TEXT_MAX_NEW_TOKENS_CAP


def test_request_max_tokens_is_respected_but_clamped_by_available_budget():
    server = _load_server_module()

    max_new_tokens = server._resolve_max_new_tokens(
        prompt_tokens=260000,
        context_window=262144,
        configured_cap=8192,
        request_max_tokens=5000,
        json_mode=False,
    )

    assert max_new_tokens == 2144


def test_json_mode_uses_smaller_default_budget():
    server = _load_server_module()

    max_new_tokens = server._resolve_max_new_tokens(
        prompt_tokens=3431,
        context_window=262144,
        configured_cap=8192,
        request_max_tokens=None,
        json_mode=True,
    )

    assert max_new_tokens == server.DEFAULT_JSON_MAX_NEW_TOKENS_CAP


def test_json_mode_uses_shorter_generation_time_limit():
    server = _load_server_module()

    assert server._resolve_max_time_seconds(json_mode=True) == server.DEFAULT_JSON_MAX_TIME_SECONDS
    assert server._resolve_max_time_seconds(json_mode=False) == server.DEFAULT_TEXT_MAX_TIME_SECONDS
