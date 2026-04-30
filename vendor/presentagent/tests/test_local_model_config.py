from src.utils.config import Config


def test_config_prefers_explicit_local_llm_endpoint(monkeypatch):
    monkeypatch.setenv("PRESENT_AGENT_USE_LOCAL_LLM", "1")
    monkeypatch.setenv("PRESENT_AGENT_LOCAL_LLM_API_BASE", "http://127.0.0.1:18081/v1")
    monkeypatch.setenv("PRESENT_AGENT_LOCAL_LLM_MODEL", "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled")

    config = Config()

    assert config.llm_backend == "local"
    assert config.llm_api_base == "http://127.0.0.1:18081/v1"
    assert config.llm_model == "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled"
    assert config.local_llm_api_base == "http://127.0.0.1:18081/v1"
    assert config.local_llm_model == "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled"


def test_config_keeps_remote_defaults_when_local_llm_not_enabled(monkeypatch):
    monkeypatch.delenv("PRESENT_AGENT_USE_LOCAL_LLM", raising=False)
    monkeypatch.delenv("PRESENT_AGENT_LOCAL_LLM_API_BASE", raising=False)
    monkeypatch.delenv("PRESENT_AGENT_LOCAL_LLM_MODEL", raising=False)
    monkeypatch.delenv("PRESENT_AGENT_LLM_API_BASE", raising=False)
    monkeypatch.delenv("PRESENT_AGENT_LLM_MODEL", raising=False)
    monkeypatch.delenv("PRESENT_AGENT_MODEL_PROFILE", raising=False)

    config = Config()

    assert config.llm_backend == "remote"
    assert config.llm_api_base == "http://123.129.219.111:3000/v1"
    assert config.llm_model == "claude-sonnet-4-6"
    assert config.model_profile == "general"
    assert config.local_llm_api_base == "http://127.0.0.1:18081/v1"
    assert config.local_llm_model == "Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled"


def test_config_allows_explicit_qwen_model_profile(monkeypatch):
    monkeypatch.setenv("PRESENT_AGENT_MODEL_PROFILE", "qwen")

    config = Config()

    assert config.model_profile == "qwen"
