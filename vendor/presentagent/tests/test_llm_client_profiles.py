from types import SimpleNamespace
import sys

from src.llm.client import LLMClient


class DummyCompletions:
    last_create_kwargs = None

    def create(self, **kwargs):
        DummyCompletions.last_create_kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )


class DummyOpenAI:
    last_init_kwargs = None

    def __init__(self, **kwargs):
        DummyOpenAI.last_init_kwargs = kwargs
        self.chat = SimpleNamespace(completions=DummyCompletions())


def test_general_profile_forwards_json_mode(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=DummyOpenAI))

    client = LLMClient(
        api_key="key",
        api_base="http://example.com/v1",
        model="claude-sonnet-4-6",
        model_profile="general",
    )

    client.chat([{"role": "user", "content": "hi"}], response_format="json")

    assert DummyCompletions.last_create_kwargs["response_format"] == {"type": "json_object"}


def test_qwen_profile_forwards_json_mode(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=DummyOpenAI))

    client = LLMClient(
        api_key="key",
        api_base="http://127.0.0.1:18000/v1",
        model="Qwen3.5-27B-Claude-4.6-Opus-Reasoning-Distilled",
        model_profile="qwen",
    )

    client.chat([{"role": "user", "content": "hi"}], response_format="json")

    assert DummyCompletions.last_create_kwargs["response_format"] == {"type": "json_object"}


def test_claude_profile_forwards_json_mode(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=DummyOpenAI))

    client = LLMClient(
        api_key="key",
        api_base="http://example.com/v1",
        model="claude-sonnet-4-6",
        model_profile="claude",
    )

    client.chat([{"role": "user", "content": "hi"}], response_format="json")

    assert DummyCompletions.last_create_kwargs["response_format"] == {"type": "json_object"}


def test_client_does_not_forward_max_tokens_even_if_provided(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=DummyOpenAI))

    client = LLMClient(
        api_key="key",
        api_base="http://example.com/v1",
        model="claude-sonnet-4-6",
        model_profile="general",
    )

    client.chat([{"role": "user", "content": "hi"}])

    assert "max_tokens" not in DummyCompletions.last_create_kwargs
