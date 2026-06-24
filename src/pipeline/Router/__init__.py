"""Shared VLM safety router (the final safe/reject/unsure decision).

This is stage 4 of ``docs/full-safety-pipeline.md`` / ``docs/vlm-safety-router.md``:
after deterministic preprocessing (text PII, OCR, span-to-box redaction) the
merged artifact is routed by one shared model.

Design:

- ``SafetyRouter`` is the narrow interface; concrete backends are hidden behind
  it and selected by name via :func:`get_router` (config flip, not code change).
- ``GeminiVlmRouter`` is the default backend — Gemini Flash (vision) over an
  OpenAI-compatible Chat Completions endpoint. The ``openai`` client is imported
  lazily so importing this package never requires the dependency or a key.
- The router output is validated against the flat label schema; anything that
  fails to parse/validate routes to ``unsure`` (never silently to ``safe``).
- The router is fired EXPLICITLY (the webdemo "Run router" button), never on
  every analyze, because it costs paid API budget.
"""

from src.pipeline.Router.input import build_router_input, encode_image_data_url
from src.pipeline.Router.output import RouterResult, parse_router_output
from src.pipeline.Router.router import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    GeminiVlmRouter,
    SafetyRouter,
    get_router,
    list_router_names,
)

__all__ = [
    "build_router_input",
    "encode_image_data_url",
    "RouterResult",
    "parse_router_output",
    "SafetyRouter",
    "GeminiVlmRouter",
    "get_router",
    "list_router_names",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
]
