"""Canonical `safety_v0` row: builders, label helpers, and a validator.

This is the single source of truth for the dataset schema described in
``DATA_PLAN.md`` (see "Unified Dataset Format" and "Step 1: Lock Schema And
Validator"). Every converter, the weak-label scripts under
``scripts/safety_v0/``, the web review tool, and the final build all read and
write rows in this shape.

Core rule from the plan:

    null means unknown, not false.

Training masks are derived from ``labels[field] is not None`` (see
``derive_label_mask``). The compact model target (``model_target``) is the flat
object the router actually learns to generate.

Path helpers and stable source names live in ``safety_v0_sources.py``; this
module is intentionally limited to schema constants, row construction, and
validation so it has no dependency on dataset/source configuration.
"""

from typing import Any, Dict, List, Optional


# --- Label space (single source of truth) ------------------------------------
# The action field is categorical; the rest are booleans. All may be null
# (unknown). Order is fixed so derived masks / targets are stable.
ACTION_FIELD = "action"
ACTION_VALUES = ("safe", "reject", "unsure")
RISK_FIELDS = (
    "pii_visible",
    "prompt_injection",
    "sexual",
    "violence",
    "blood_gore",
    "political",
    "religious",
)
LABEL_FIELDS = (ACTION_FIELD,) + RISK_FIELDS

# Required top-level keys every canonical row must carry.
REQUIRED_TOP_LEVEL_KEYS = (
    "input_id",
    "source",
    "modality",
    "content",
    "geometry",
    "detections",
    "labels",
    "label_source",
    "source_labels",
    "review",
)

REVIEW_STATUSES = ("unreviewed", "human_reviewed", "needs_review", "skipped")


# --- Builders ----------------------------------------------------------------
def empty_labels() -> Dict[str, Any]:
    """All labels unknown (``None``)."""
    return {field: None for field in LABEL_FIELDS}


def empty_label_source() -> Dict[str, Optional[str]]:
    """Provenance per label, parallel to ``labels``; ``None`` until set."""
    return {field: None for field in LABEL_FIELDS}


def new_ocr_box(
    box_id: str,
    text: str,
    start: int,
    end: int,
    box: List[float],
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "box_id": box_id,
        "text": text,
        "start": int(start),
        "end": int(end),
        "box": list(box),
        "confidence": confidence,
    }


def new_pii_span(
    span_id: str,
    entity_type: str,
    start: int,
    end: int,
    text: str,
    score: Optional[float] = None,
    box_ids: Optional[List[str]] = None,
    detector: str = "presidio",
) -> Dict[str, Any]:
    return {
        "span_id": span_id,
        "entity_type": entity_type,
        "start": int(start),
        "end": int(end),
        "text": text,
        "score": score,
        "box_ids": list(box_ids or []),
        "detector": detector,
    }


def new_prompt_injection_span(
    span_id: str,
    attack_type: str,
    start: int,
    end: int,
    text: str,
    score: Optional[float] = None,
    box_ids: Optional[List[str]] = None,
    detector: str = "rule",
) -> Dict[str, Any]:
    return {
        "span_id": span_id,
        "attack_type": attack_type,
        "start": int(start),
        "end": int(end),
        "text": text,
        "score": score,
        "box_ids": list(box_ids or []),
        "detector": detector,
    }


def new_redaction(
    redaction_id: str,
    source_span_ids: List[str],
    box_ids: List[str],
    merged_box: Optional[List[float]] = None,
    reason: str = "pii",
    method: str = "blur",
) -> Dict[str, Any]:
    return {
        "redaction_id": redaction_id,
        "reason": reason,
        "source_span_ids": list(source_span_ids),
        "box_ids": list(box_ids),
        "merged_box": list(merged_box) if merged_box is not None else None,
        "method": method,
    }


def new_row(
    input_id: str,
    source_name: str,
    *,
    split: str = "train",
    source_sample_id: Optional[str] = None,
    license_status: str = "needs_verification",
    has_image: bool = False,
    has_text: bool = False,
    has_ocr: bool = False,
    original_image_path: Optional[str] = None,
    redacted_image_path: Optional[str] = None,
    input_text: str = "",
    sanitized_text: str = "",
    ocr_text: str = "",
    sanitized_ocr_text: str = "",
) -> Dict[str, Any]:
    """Build a canonical row with empty detections and all-unknown labels.

    Detections, geometry, labels, and review are filled in by later stages
    (converter -> weak-label scripts -> human/API review).
    """
    return {
        "input_id": input_id,
        "source": {
            "name": source_name,
            "split": split,
            "source_sample_id": source_sample_id,
            "license_status": license_status,
        },
        "modality": {
            "has_image": bool(has_image),
            "has_text": bool(has_text),
            "has_ocr": bool(has_ocr),
        },
        "content": {
            "original_image_path": original_image_path,
            "redacted_image_path": redacted_image_path,
            "input_text": input_text,
            "sanitized_text": sanitized_text,
            "ocr_text": ocr_text,
            "sanitized_ocr_text": sanitized_ocr_text,
        },
        "geometry": {"ocr_boxes": []},
        "detections": {
            "pii_spans": [],
            "prompt_injection_spans": [],
            "redaction_metadata": [],
        },
        "labels": empty_labels(),
        "label_source": empty_label_source(),
        "source_labels": {},
        "review": {"status": "unreviewed", "reviewer": None, "notes": ""},
    }


# --- Derived views -----------------------------------------------------------
def derive_label_mask(row: Dict[str, Any]) -> Dict[str, int]:
    """1 where a label is known (not ``None``), else 0. Never invents negatives."""
    labels = row.get("labels", {})
    return {field: int(labels.get(field) is not None) for field in LABEL_FIELDS}


def model_target(row: Dict[str, Any]) -> Dict[str, Any]:
    """Compact flat target the router learns to generate.

    Unknown risks collapse to ``False`` here ONLY for generation convenience;
    masking for the loss must use ``derive_label_mask`` against the row, not
    this view, so unknowns are not trained as negatives.
    """
    labels = row.get("labels", {})
    target: Dict[str, Any] = {ACTION_FIELD: labels.get(ACTION_FIELD) or "unsure"}
    for field in RISK_FIELDS:
        target[field] = bool(labels.get(field))
    return target


# --- Validation --------------------------------------------------------------
def _valid_box(box: Any) -> bool:
    return (
        isinstance(box, (list, tuple))
        and len(box) == 4
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)
    )


def validate_row(row: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable schema errors; empty means valid.

    Implements the Step-1 checklist from ``DATA_PLAN.md``:
    unique IDs within a row, span ``box_ids`` reference existing OCR boxes,
    redaction ``source_span_ids`` reference existing span IDs, and ``labels``
    only contain booleans, an allowed action, or ``None``.
    """
    errors: List[str] = []

    if not isinstance(row, dict):
        return ["row is not a dict"]

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in row:
            errors.append(f"missing required top-level key: {key!r}")
    if errors:
        # Without the core containers the rest of the checks are meaningless.
        return errors

    if not row.get("input_id"):
        errors.append("input_id is empty")

    # --- labels -------------------------------------------------------------
    labels = row["labels"]
    if not isinstance(labels, dict):
        errors.append("labels is not a dict")
        labels = {}
    extra = set(labels) - set(LABEL_FIELDS)
    if extra:
        errors.append(f"labels has unknown fields: {sorted(extra)}")
    for field in LABEL_FIELDS:
        if field not in labels:
            errors.append(f"labels missing field: {field!r}")
            continue
        value = labels[field]
        if field == ACTION_FIELD:
            if value is not None and value not in ACTION_VALUES:
                errors.append(
                    f"labels.action must be one of {ACTION_VALUES} or null, got {value!r}"
                )
        elif value is not None and not isinstance(value, bool):
            errors.append(f"labels.{field} must be bool or null, got {value!r}")

    label_source = row.get("label_source")
    if not isinstance(label_source, dict):
        errors.append("label_source is not a dict")

    # --- geometry: OCR + source PII boxes -----------------------------------
    # Spans may reference either OCR boxes (detected) or source PII boxes
    # (provided by the source dataset or added by a human reviewer), so both
    # contribute to the known ``box_ids`` set.
    geometry = row.get("geometry") or {}
    box_ids: set = set()
    for collection in ("ocr_boxes", "source_pii_boxes"):
        boxes = geometry.get(collection, [])
        if not isinstance(boxes, list):
            errors.append(f"geometry.{collection} is not a list")
            continue
        for i, ob in enumerate(boxes):
            bid = ob.get("box_id")
            if not bid:
                errors.append(f"geometry.{collection}[{i}] missing box_id")
            elif bid in box_ids:
                errors.append(f"duplicate box_id: {bid!r}")
            else:
                box_ids.add(bid)
            if not _valid_box(ob.get("box")):
                errors.append(
                    f"geometry.{collection}[{i}] box must be [x0,y0,x1,y1] numbers"
                )

    detections = row.get("detections") or {}

    # --- pii + prompt-injection spans --------------------------------------
    span_ids: set = set()
    for collection in ("pii_spans", "prompt_injection_spans"):
        spans = detections.get(collection, [])
        if not isinstance(spans, list):
            errors.append(f"detections.{collection} is not a list")
            continue
        for i, span in enumerate(spans):
            sid = span.get("span_id")
            if not sid:
                errors.append(f"detections.{collection}[{i}] missing span_id")
            elif sid in span_ids:
                errors.append(f"duplicate span_id: {sid!r}")
            else:
                span_ids.add(sid)
            for ref in span.get("box_ids", []) or []:
                if ref not in box_ids:
                    errors.append(
                        f"detections.{collection}[{i}] references unknown box_id {ref!r}"
                    )

    # --- redaction metadata -------------------------------------------------
    redactions = detections.get("redaction_metadata", [])
    redaction_ids: set = set()
    if not isinstance(redactions, list):
        errors.append("detections.redaction_metadata is not a list")
        redactions = []
    for i, red in enumerate(redactions):
        rid = red.get("redaction_id")
        if not rid:
            errors.append(f"detections.redaction_metadata[{i}] missing redaction_id")
        elif rid in redaction_ids:
            errors.append(f"duplicate redaction_id: {rid!r}")
        else:
            redaction_ids.add(rid)
        for ref in red.get("source_span_ids", []) or []:
            if ref not in span_ids:
                errors.append(
                    f"detections.redaction_metadata[{i}] references unknown span_id {ref!r}"
                )
        for ref in red.get("box_ids", []) or []:
            if ref not in box_ids:
                errors.append(
                    f"detections.redaction_metadata[{i}] references unknown box_id {ref!r}"
                )
        mb = red.get("merged_box")
        if mb is not None and not _valid_box(mb):
            errors.append(
                f"detections.redaction_metadata[{i}] merged_box must be null or 4 numbers"
            )

    # --- review -------------------------------------------------------------
    review = row.get("review") or {}
    status = review.get("status")
    if status not in REVIEW_STATUSES:
        errors.append(
            f"review.status must be one of {REVIEW_STATUSES}, got {status!r}"
        )

    return errors


def is_valid_row(row: Dict[str, Any]) -> bool:
    return not validate_row(row)
