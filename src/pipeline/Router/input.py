"""Build the router input package from a canonical ``safety_v0`` row.

This is the "merge before model" step: the sanitized text, redacted image, OCR
text, and detection metadata become one compact input contract (see
``docs/vlm-safety-router.md``). The router only ever sees this package, never the
raw row, so the model interface stays stable as the row schema grows.

The router consumes the REDACTED image by default (PII already removed); the
original path is kept only for audit.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

PathLike = Union[str, Path]

# Repo root: src/pipeline/Router/input.py
REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_image(path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p if p.exists() else None


def build_router_input(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a canonical row to the router input contract.

    Prefers the redacted image; falls back to the original only if no redacted
    artifact exists. ``presidio_spans`` / ``redaction_metadata`` are compact
    summaries (type/offsets/method), not the full detection records.
    """
    content = row.get("content", {})
    detections = row.get("detections", {})

    redacted = content.get("redacted_image_path")
    image_path = redacted or content.get("original_image_path")

    ocr_text = content.get("sanitized_ocr_text") or content.get("ocr_text") or ""
    input_text = content.get("sanitized_text") or content.get("input_text") or ""

    presidio_spans = [
        {"start": s.get("start"), "end": s.get("end"), "entity_type": s.get("entity_type")}
        for s in detections.get("pii_spans", [])
    ]
    redaction_metadata = [
        {"entity_type": None, "box": r.get("merged_box"), "method": r.get("method")}
        for r in detections.get("redaction_metadata", [])
    ]

    has_image = bool(image_path)
    has_ocr = bool(ocr_text.strip())
    return {
        "input_id": row.get("input_id"),
        "image_path": image_path,
        "image_is_redacted": bool(redacted),
        "input_text": input_text,
        "ocr_text": ocr_text,
        "presidio_spans": presidio_spans,
        "redaction_metadata": redaction_metadata,
        "input_modalities": {
            "image": has_image,
            "text": bool(input_text.strip()),
            "ocr_text": has_ocr,
            "presidio_metadata": bool(presidio_spans),
        },
    }


def encode_image_data_url(path: PathLike) -> str:
    """Return a ``data:image/...;base64,...`` URL for an image file."""
    p = Path(path)
    suffix = p.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{data}"


def render_text_payload(router_input: Dict[str, Any]) -> str:
    """Human/model-readable text block summarizing the non-image parts."""
    lines: List[str] = [f"input_id: {router_input.get('input_id')}"]
    mods = router_input.get("input_modalities", {})
    lines.append("modalities: " + ", ".join(k for k, v in mods.items() if v) or "none")
    if router_input.get("input_text"):
        lines.append(f"input_text (sanitized): {router_input['input_text']}")
    if router_input.get("ocr_text"):
        lines.append(f"ocr_text (sanitized): {router_input['ocr_text']}")
    spans = router_input.get("presidio_spans") or []
    if spans:
        types = sorted({s.get("entity_type") for s in spans if s.get("entity_type")})
        lines.append(f"detected_pii_types: {', '.join(types)}")
    reds = router_input.get("redaction_metadata") or []
    if reds:
        methods = sorted({r.get("method") for r in reds if r.get("method")})
        lines.append(f"image_redactions: {len(reds)} region(s), method(s): {', '.join(methods)}")
    if router_input.get("image_path"):
        kind = "redacted" if router_input.get("image_is_redacted") else "original (unredacted)"
        lines.append(f"image: present ({kind})")
    return "\n".join(lines)
