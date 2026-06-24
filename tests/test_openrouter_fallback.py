"""Tests for the standalone OpenRouter fallback client."""

from types import SimpleNamespace

import pytest

from src.pipeline.Fallbacks import OpenRouterFallback
from src.pipeline.Fallbacks.openrouter_fallback import (
    API_KEY_ENV_VARS,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
)


def test_defaults_target_openrouter_and_mimo_v25():
    assert DEFAULT_BASE_URL == "https://openrouter.ai/api/v1"
    assert DEFAULT_MODEL == "xiaomi/mimo-v2.5"
    assert "OPENROUTER_API_KEY" in API_KEY_ENV_VARS


def test_chat_uses_injected_client():
    captured = {}

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="vi::ok"))]
            )

    fake = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    fb = OpenRouterFallback(client=fake, model="custom/model", temperature=0.1, max_tokens=128)
    out = fb.chat([{"role": "user", "content": "hi"}])
    assert out == "vi::ok"
    assert captured["model"] == "custom/model"
    assert captured["temperature"] == 0.1
    assert captured["max_tokens"] == 128
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    # No response_format -> not in the call.
    assert "response_format" not in captured


def test_chat_passes_response_format_when_supplied():
    captured = {}

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    fake = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    fb = OpenRouterFallback(client=fake)
    fb.chat(
        [{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
    )
    assert captured["response_format"] == {"type": "json_object"}


def test_chat_strips_empty_content():
    class _Completions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
            )

    fake = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    fb = OpenRouterFallback(client=fake)
    assert fb.chat([{"role": "user", "content": "hi"}]) == ""


def test_get_client_raises_without_key(monkeypatch):
    for var in API_KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    fb = OpenRouterFallback()
    with pytest.raises(RuntimeError) as exc_info:
        fb._get_client()
    assert "OPENROUTER_API_KEY" in str(exc_info.value)
