"""OpenRouter fallback backend for paid Gemini calls.

Used as a secondary model when a Gemini call exhausts its retries on a transient
error (free-tier daily cap, 429, 5xx). The fallback is **opt-in**: each call
site (translator, safety router) decides whether to wire it in. The fallback is
deliberately narrow:

- One model: ``xiaomi/mimo-v2.5`` (text-only chat completions; not a VLM).
- One base URL: ``https://openrouter.ai/api/v1`` (single source of truth).
- One API key: ``OPENROUTER_API_KEY`` (falls back to ``OPENAI_API_KEY``).
- No retries inside the fallback: by the time we get here the primary has
  already retried, and a second long retry loop is the wrong shape for a
  budget-controlled fallback. We make one attempt and surface the error.

Selection is configuration, not automatic runtime switching. Call sites that do
not pass a ``fallback_client`` (or a model override) never hit this code path.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# --- Provider / model configuration (single source of truth) -----------------
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "xiaomi/mimo-v2.5"
# Same env-var precedence as the LLMVerifier: OpenRouter first, OpenAI as
# fallback. Either works against the OpenRouter endpoint.
API_KEY_ENV_VARS = ("OPENROUTER_API_KEY", "OPENAI_API_KEY")


class OpenRouterFallback:
    """Thin OpenRouter Chat Completions client for the fallback path.

    Mirrors the small surface that ``GeminiTranslator`` / ``GeminiVlmRouter``
    need: build a chat-completions call and return the assistant text. The
    ``openai`` client is imported lazily on first use, so importing this module
    never requires the dependency or an API key. Inject a pre-built ``client``
    (any object with ``.chat.completions.create``) to unit-test without network.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        client: Any = None,
    ):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = client

    def _resolve_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        for env_var in API_KEY_ENV_VARS:
            value = os.getenv(env_var)
            if value:
                return value
        return None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            key = self._resolve_api_key()
            if not key:
                raise RuntimeError(
                    "No API key for the OpenRouter fallback. Set "
                    f"{' or '.join(API_KEY_ENV_VARS)} or pass api_key=."
                )
            self._client = OpenAI(base_url=self.base_url, api_key=key)
        return self._client

    def chat(self, messages: List[dict], *, response_format: Optional[dict] = None) -> str:
        """Make one chat-completions call and return the assistant text.

        No retries: the caller has already exhausted its primary retries. Any
        exception propagates so the caller can decide how to surface it.
        """
        client = self._get_client()
        request: dict = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if response_format is not None:
            request["response_format"] = response_format
        response = client.chat.completions.create(**request)
        content = response.choices[0].message.content
        return (content or "").strip()
