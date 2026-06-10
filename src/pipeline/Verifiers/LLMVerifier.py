import json
import logging
from typing import List, Optional

from presidio_analyzer import RecognizerResult

from src.pipeline.Verifiers.BaseVerifier import BaseVerifier


logger = logging.getLogger(__name__)


# Presidio entity types this pipeline targets. The adjudicator may re-label a
# span to any of these; anything else is treated as "drop".
ENTITY_TYPES = [
    "PERSON",
    "LOCATION",
    "ORGANIZATION",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "BANK_ACCOUNT",
    "ID",
    "DATE_TIME",
    "MISC",
]


SYSTEM_PROMPT = """You are a precision adjudicator for a Vietnamese PII detection pipeline.

An upstream system (regex rules, a spaCy model, and a transformer NER model) has \
already detected candidate PII spans in a Vietnamese document and resolved \
overlaps. Your job is to take each tool's conclusion into account and decide, \
per candidate, whether it is genuinely PII — and if so, of which type.

You will receive the full source text and a list of candidate spans. Each \
candidate has: an id, the exact substring, the proposed entity type, the \
detecting recognizer (`source`), the recognizer's confidence `score`, and a \
`context` snippet with the span delimited by ⟦ ⟧.

For each candidate, return a decision:
- `keep`: true if the span is real PII, false if it is a false positive.
- `entity_type`: the correct type from the allowed list. If the upstream type is \
right, repeat it; if the recognizer mislabeled it, correct it. Ignored when keep \
is false.
- `reason`: one short clause justifying the decision.

Guidance specific to this pipeline:
- Regex recognizers (phone/ID/bank-account/tax-id) match on digit shape alone and \
over-fire. A bare number that is an order id, a quantity, a date, or a product \
code is NOT a BANK_ACCOUNT/ID — drop it. Keep it only when the surrounding \
Vietnamese context (e.g. "số tài khoản", "STK", "CCCD", "mã số thuế") supports it.
- Use context to disambiguate numeric types (CCCD vs tax id vs bank account vs \
phone) and re-label to the correct one.
- Do NOT invent new spans and do NOT change offsets — judge only the candidates \
given. Return exactly one decision per candidate id.
"""


DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "keep": {"type": "boolean"},
                    "entity_type": {"type": "string", "enum": ENTITY_TYPES},
                    "reason": {"type": "string"},
                },
                "required": ["id", "keep", "entity_type", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


class LLMVerifier(BaseVerifier):
    """Claude-backed adjudication pass over resolved Presidio results.

    Sends the candidate spans (with provenance + local context) to Claude and
    applies its keep/drop/re-label decisions. Any error degrades to a no-op so
    evaluation runs are never interrupted.

    Args:
        model: Claude model id.
        context_window: characters of context to include each side of a span.
        effort: thinking/effort level for the adjudication call.
        max_tokens: output cap for the decisions response.
        client: optional pre-built anthropic.Anthropic client (else lazily created).
    """

    def __init__(
        self,
        model: str = "claude-opus-4-8",
        context_window: int = 40,
        effort: str = "low",
        max_tokens: int = 8192,
        client=None,
    ):
        self.model = model
        self.context_window = context_window
        self.effort = effort
        self.max_tokens = max_tokens
        self._client = client

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
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
        except Exception as exc:  # never break the pipeline on a model/network error
            logger.warning("LLMVerifier falling back to no-op: %s", exc)
            return results

        return self._apply(results, decisions)

    def _adjudicate(self, text: str, candidates: List[dict]) -> dict:
        client = self._get_client()
        user_payload = json.dumps(
            {"source_text": text, "candidates": candidates},
            ensure_ascii=False,
        )
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": DECISION_SCHEMA},
            },
            messages=[{"role": "user", "content": user_payload}],
        )
        text_block = next(b.text for b in response.content if b.type == "text")
        return json.loads(text_block)

    def _apply(
        self, results: List[RecognizerResult], decisions: dict
    ) -> List[RecognizerResult]:
        by_id = {d["id"]: d for d in decisions.get("decisions", [])}
        adjudicated: List[RecognizerResult] = []
        for idx, result in enumerate(results):
            decision = by_id.get(idx)
            if decision is None:
                # Model omitted this candidate — keep it (conservative on recall).
                adjudicated.append(result)
                continue
            if not decision.get("keep", True):
                continue
            corrected = decision.get("entity_type")
            if corrected and corrected != result.entity_type:
                result.entity_type = corrected
            adjudicated.append(result)
        return adjudicated
