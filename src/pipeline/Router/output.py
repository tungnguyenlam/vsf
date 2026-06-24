"""Router output: the flat label schema, parsing, and validation.

The label space is reused from ``safety_v0_schema`` (single source of truth):
``action`` plus the seven risk flags. Per ``docs/vlm-safety-router.md``, output
that fails to parse or validate must route to ``unsure`` — never to ``safe`` —
and unknown/invalid risk flags stay ``None`` (unknown), never coerced to False.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from src.pipeline.Datasets.safety_v0_schema import ACTION_VALUES, RISK_FIELDS


@dataclass
class RouterResult:
    """Validated router decision.

    - ``action``: one of ``safe``/``reject``/``unsure`` (``unsure`` on any failure).
    - ``flags``: risk flags that parsed as proper booleans; absent/invalid flags
      are simply not present (i.e. stay unknown).
    - ``valid``: whether the raw output passed full validation.
    - ``raw``/``error``: audit trail for the call.
    """

    action: str
    flags: Dict[str, bool] = field(default_factory=dict)
    valid: bool = True
    raw: Any = None
    error: Optional[str] = None

    def to_labels(self) -> Dict[str, Any]:
        """Flat label dict over all 8 fields; unknown risk flags are ``None``."""
        labels: Dict[str, Any] = {"action": self.action}
        for fld in RISK_FIELDS:
            labels[fld] = self.flags.get(fld)  # None when not present/valid
        return labels

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "flags": dict(self.flags),
            "valid": self.valid,
            "error": self.error,
        }


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(content: Any) -> Optional[dict]:
    """Best-effort: pull a JSON object out of a model message.

    Accepts a dict as-is, or a string that is JSON / fenced JSON / JSON embedded
    in prose. Returns ``None`` if nothing parseable is found.
    """
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    text = content.strip()
    for candidate in (text,):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    for pattern in (_JSON_FENCE, _JSON_OBJECT):
        match = pattern.search(text)
        if match:
            try:
                obj = json.loads(match.group(1) if pattern is _JSON_FENCE else match.group(0))
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def parse_router_output(content: Any) -> RouterResult:
    """Parse + validate a router response into a :class:`RouterResult`.

    Routes to ``unsure`` (``valid=False``) when the content is not a JSON object,
    ``action`` is missing/invalid, or any risk flag is missing/non-boolean.
    Boolean flags that are present are always kept (even on an invalid result)
    so the audit log shows what the model claimed.
    """
    obj = extract_json(content)
    if obj is None:
        return RouterResult("unsure", {}, valid=False, raw=content, error="no JSON object found")

    flags: Dict[str, bool] = {}
    errors = []
    for fld in RISK_FIELDS:
        value = obj.get(fld)
        if isinstance(value, bool):
            flags[fld] = value
        else:
            errors.append(f"{fld} missing or not boolean")

    action = obj.get("action")
    if action not in ACTION_VALUES:
        errors.append(f"action must be one of {ACTION_VALUES}, got {action!r}")

    if errors:
        return RouterResult("unsure", flags, valid=False, raw=obj, error="; ".join(errors))
    return RouterResult(action, flags, valid=True, raw=obj, error=None)
