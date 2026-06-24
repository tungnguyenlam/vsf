import json
import logging
import os
from typing import List, Optional

from presidio_analyzer import RecognizerResult

from src.pipeline.Verifiers.BaseVerifier import BaseVerifier


logger = logging.getLogger(__name__)


# --- Provider / model configuration (single source of truth) -----------------
# The verifier talks to any OpenAI-compatible Chat Completions endpoint. We
# default to OpenRouter so the model/provider is a one-line swap: change
# DEFAULT_MODEL (or pass `model=`/`base_url=`) to move between DeepSeek, Alibaba
# (Qwen), or a direct OpenAI endpoint without touching call-site logic.
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
# OpenRouter provider routing default. Strict structured output is required for
# the verifier, so the default only routes to endpoints that support requested
# parameters. For reproducible benchmark runs, pass pin_provider("provider-slug").
DEFAULT_PROVIDER = {"require_parameters": True}
# Env vars checked in order for the API key. OpenRouter first, OpenAI as fallback.
API_KEY_ENV_VARS = ("OPENROUTER_API_KEY", "OPENAI_API_KEY")

# Sentinel: distinguishes "caller said nothing" (use DEFAULT_PROVIDER pin) from
# an explicit provider=None (opt out of pinning -> let OpenRouter load-balance).
_PROVIDER_UNSET = object()


# Presidio entity types this pipeline targets. The adjudicator may re-label a
# span to any of these; anything else is treated as "drop".
ENTITY_TYPES = [
    # Original 8 (recognizers exist)
    "PERSON",
    "LOCATION",
    "ORGANIZATION",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "BANK_ACCOUNT",
    "ID",
    "DATE_TIME",
    # Expanded PII taxonomy (see VI_PII_LABEL_TO_PRESIDIO)
    "CREDIT_CARD",
    "CRYPTO",
    "IP_ADDRESS",
    "URL",
    "CREDENTIAL",
    "FINANCIAL",
    "MEDICAL",
    "VEHICLE",
    "USERNAME",
    "NRP",
    "OCCUPATION",
    "EDUCATION",
    "PROPERTY",
    "MISC",
]


SYSTEM_PROMPT = """You are a precision adjudicator for a Vietnamese PII detection pipeline.

An upstream system (regex rules, a spaCy model, and a transformer NER model) has \
already detected candidate PII spans in a Vietnamese document and resolved \
overlaps. Your job is to take each tool's conclusion into account and decide, \
which candidate spans need correction.

You will receive the full source text and a list of candidate spans. Each \
candidate has: an id, the exact substring, the proposed entity type, the \
detecting recognizer (`source`), the recognizer's confidence `score`, and a \
`context` snippet with the span delimited by ⟦ ⟧.

Most candidates should be left unchanged. Return only corrections:
- `drop`: candidate ids that are false positives.
- `relabel`: candidate ids whose span is real PII but whose proposed entity type \
is wrong, with the corrected type from the allowed list.

Guidance specific to this pipeline:
- Regex recognizers (phone/ID/bank-account/tax-id) match on digit shape alone and \
over-fire. A bare number that is an order id, a quantity, a date, or a product \
code is NOT a BANK_ACCOUNT/ID — drop it. Keep it only when the surrounding \
Vietnamese context (e.g. "số tài khoản", "STK", "CCCD", "mã số thuế") supports it.
- Use context to disambiguate numeric types (CCCD vs tax id vs bank account vs \
phone) and re-label to the correct one.
- Do NOT invent new spans and do NOT change offsets — judge only the candidates \
given. Do not include unchanged candidates in the output.
"""


DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "drop": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "relabel": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "entity_type": {"type": "string", "enum": ENTITY_TYPES},
                },
                "required": ["id", "entity_type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["drop", "relabel"],
    "additionalProperties": False,
}


class LLMVerifier(BaseVerifier):
    """LLM adjudication pass over resolved Presidio results.

    Sends the candidate spans (with provenance + local context) to an
    OpenAI-compatible Chat Completions endpoint (OpenRouter by default) and
    applies its sparse drop/re-label corrections. Unmentioned candidates are
    kept unchanged. By default, errors degrade to a no-op for interactive use;
    evaluation should set ``raise_on_error=True`` so routing/auth/schema failures
    stop the run instead of corrupting metrics.

    The provider is just configuration: ``model``/``base_url``/``api_key`` select
    the backend. Defaults target DeepSeek V4 Flash on OpenRouter; point them at a
    Qwen slug or another OpenAI-compatible base URL to swap without code changes.

    Args:
        model: model id (e.g. "deepseek/deepseek-v4-flash", "qwen/qwen3-max").
        base_url: OpenAI-compatible API base URL.
        api_key: API key; falls back to OPENROUTER_API_KEY / OPENAI_API_KEY.
        context_window: characters of context to include each side of a span.
        effort: optional reasoning effort ("low"/"medium"/"high"); None disables
            reasoning (correct for non-reasoning flash models).
        max_tokens: output cap for the sparse correction response.
        temperature: sampling temperature (0 for deterministic adjudication).
        provider: OpenRouter provider-routing object passed through as
            `extra_body.provider`. Defaults to ``{"require_parameters": True}``
            so OpenRouter only routes to endpoints that support strict structured
            output. Pass pin_provider("slug") for a reproducible single-provider
            benchmark, an explicit dict for custom OpenRouter routing, or
            provider=None to opt out and let OpenRouter load-balance.
        raise_on_error: raise model/API/parse errors instead of falling back to a
            no-op. Use this for evaluation integrity.
        client: optional pre-built OpenAI client (else lazily created).
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        api_key: Optional[str] = None,
        context_window: int = 40,
        effort: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        provider=_PROVIDER_UNSET,
        raise_on_error: bool = False,
        client=None,
    ):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.context_window = context_window
        self.effort = effort
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.provider = DEFAULT_PROVIDER if provider is _PROVIDER_UNSET else provider
        self.raise_on_error = raise_on_error
        self._client = client

    @staticmethod
    def pin_provider(name: str, allow_fallbacks: bool = False) -> dict:
        """Build an OpenRouter provider-routing object pinned to one provider.

        With allow_fallbacks=False the call sticks to `name` and errors if it is
        unavailable or does not support required parameters. In evaluation,
        combine this with raise_on_error=True so bad routing stops the run. Set
        allow_fallbacks=True to prefer `name` but tolerate outages.
        """
        return {"order": [name], "allow_fallbacks": allow_fallbacks}

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

            self._client = OpenAI(base_url=self.base_url, api_key=self._resolve_api_key())
        return self._client

    def _build_candidate(self, text: str, idx: int, result: RecognizerResult) -> dict:
        start, end = result.start, result.end
        w = self.context_window
        prefix = text[max(0, start - w):start]
        suffix = text[end:end + w]
        context = f"{prefix}⟦{text[start:end]}⟧{suffix}"
        return {
            "id": idx,
            "text": text[start:end],
            "type": result.entity_type,
            "source": self.source_of(result),
            "score": round(float(result.score), 2),
            "context": context,
        }

    def verify(
        self,
        text: str,
        results: List[RecognizerResult],
        *,
        language: str = "vi",
    ) -> List[RecognizerResult]:
        if not results:
            return results

        candidates = [
            self._build_candidate(text, i, r) for i, r in enumerate(results)
        ]

        try:
            decisions = self._adjudicate(text, candidates)
        except Exception as exc:
            if self.raise_on_error:
                raise
            logger.warning("LLMVerifier falling back to no-op: %s", exc)
            return results

        return self._apply(results, decisions)

    def _adjudicate(self, text: str, candidates: List[dict]) -> dict:
        client = self._get_client()
        user_payload = json.dumps(
            {"source_text": text, "candidates": candidates},
            ensure_ascii=False,
        )
        # The system prompt is a stable prefix; DeepSeek caches it automatically
        # and OpenRouter's sticky routing keeps the cache warm. No cache_control
        # field is needed for OpenAI-compatible providers.
        request = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "pii_decisions",
                    "strict": True,
                    "schema": DECISION_SCHEMA,
                },
            },
        }
        extra_body = {}
        if self.effort:
            # OpenRouter's unified reasoning control; ignored by non-reasoning models.
            extra_body["reasoning"] = {"effort": self.effort}
        if self.provider:
            # Pin/scope the OpenRouter provider (e.g. for reproducible evaluation).
            extra_body["provider"] = self.provider
        if extra_body:
            request["extra_body"] = extra_body

        response = client.chat.completions.create(**request)
        content = response.choices[0].message.content
        return json.loads(content)

    def _apply(
        self, results: List[RecognizerResult], decisions: dict
    ) -> List[RecognizerResult]:
        drop_ids = set(decisions.get("drop", []))
        relabel_by_id = {
            d["id"]: d["entity_type"]
            for d in decisions.get("relabel", [])
            if "id" in d and "entity_type" in d
        }
        adjudicated: List[RecognizerResult] = []
        for idx, result in enumerate(results):
            if idx in drop_ids:
                continue
            corrected = relabel_by_id.get(idx)
            if corrected and corrected != result.entity_type:
                result.entity_type = corrected
            adjudicated.append(result)
        return adjudicated
