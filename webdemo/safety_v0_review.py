"""Helpers for the webdemo `safety_v0` review/annotation tab.

Loads canonical `safety_v0` rows from a JSONL file, merges any human overrides
recorded for that file, and appends new overrides. Human overrides are written
per the DATA_PLAN layout to ``data/safety_v0/review/human_overrides/<slug>.jsonl``
when the file belongs to a known source, otherwise next to a stable name derived
from the file. Overrides are applied last (latest line per ``input_id`` wins),
matching ``scripts/safety_v0/apply_review_overrides.py`` semantics.

This module owns no Flask state; ``app.py`` wraps thin routes around it.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.pipeline.Datasets.safety_v0_schema import (
    ACTION_FIELD,
    ACTION_VALUES,
    LABEL_FIELDS,
    RISK_FIELDS,
    derive_label_mask,
    new_pii_span,
    new_prompt_injection_span,
)
from src.pipeline.Datasets.safety_v0_sources import (
    DEFAULT_DATA_ROOT,
    REPO_ROOT,
    list_source_slugs,
    shared_dir,
)

DATA_ROOT = DEFAULT_DATA_ROOT


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_canonical_files(root: Path = DATA_ROOT) -> List[Dict[str, str]]:
    """Discover canonical JSONL files under the data root, newest stage first.

    Returns ``[{path, label}]`` with ``path`` relative to the repo root so it is
    a stable identifier the client can pass back.
    """
    root = Path(root)
    found: List[Dict[str, str]] = []
    patterns = [
        ("weak", "weak/*/weak_labeled.jsonl"),
        ("redacted", "redacted/*/redacted.jsonl"),
        ("ocr", "ocr/*/ocr.jsonl"),
        ("converted", "converted/*/source_canonical.jsonl"),
        ("sample", "samples/**/*.jsonl"),
    ]
    seen = set()
    for stage, pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            rel = path.relative_to(REPO_ROOT).as_posix()
            found.append({"path": rel, "label": f"[{stage}] {rel}"})
    return found


def _resolve_under_root(rel_or_abs: str, base: Path) -> Optional[Path]:
    """Resolve a path and confirm it stays within ``base`` (no traversal)."""
    candidate = Path(rel_or_abs)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    candidate = candidate.resolve()
    base = base.resolve()
    if base == candidate or base in candidate.parents:
        return candidate
    return None


def resolve_data_file(rel_path: str) -> Optional[Path]:
    """Resolve a client-supplied JSONL path, constrained to the data root."""
    resolved = _resolve_under_root(rel_path, DATA_ROOT)
    if resolved and resolved.is_file():
        return resolved
    return None


def resolve_image(path_str: Optional[str]) -> Optional[Path]:
    """Resolve an image path from a row, constrained to the data root."""
    if not path_str:
        return None
    resolved = _resolve_under_root(path_str, DATA_ROOT)
    if resolved and resolved.is_file():
        return resolved
    return None


def _layer_path_for(data_file: Path, kind: str) -> Path:
    """Per-source label-layer file (human overrides or API labels) for a data file.

    ``converted/<slug>/...``, ``ocr/<slug>/...``, ``redacted/<slug>/...``, and
    ``weak/<slug>/...`` map to the per-source file; anything else (e.g. a demo
    sample) uses the file stem.
    """
    layer_dir = shared_dir(kind, create=True)
    try:
        rel = data_file.resolve().relative_to(DATA_ROOT.resolve())
        parts = rel.parts
        if (
            parts[0] in {"converted", "ocr", "redacted", "weak"}
            and len(parts) >= 2
            and parts[1] in set(list_source_slugs())
        ):
            return layer_dir / f"{parts[1]}.jsonl"
    except ValueError:
        pass
    return layer_dir / f"{data_file.stem}.jsonl"


def override_path_for(data_file: Path) -> Path:
    """Where human overrides for ``data_file`` are stored."""
    return _layer_path_for(data_file, "review/human_overrides")


def api_labels_path_for(data_file: Path) -> Path:
    """Where router/API labels for ``data_file`` are stored."""
    return _layer_path_for(data_file, "review/api_labels")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_overrides(override_path: Path) -> Dict[str, Dict[str, Any]]:
    """Latest override per ``input_id`` (later lines win)."""
    if not override_path.exists():
        return {}
    latest: Dict[str, Dict[str, Any]] = {}
    with open(override_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            iid = rec.get("input_id")
            if iid:
                latest[iid] = rec
    return latest


def _apply_label_layer(
    row: Dict[str, Any], record: Dict[str, Any], default_source: str
) -> Dict[str, Any]:
    """Apply a label-layer record (API or human) onto a copy of ``row``.

    Known labels overwrite the row's labels; provenance comes from the record's
    own ``label_source`` when present, else ``default_source``. Unknown (``None``)
    values leave the existing label/source untouched. ``review`` is replaced when
    present in the record.
    """
    merged = json.loads(json.dumps(row))  # cheap deep copy
    labels = record.get("labels") or {}
    rec_source = record.get("label_source") or {}
    for field in LABEL_FIELDS:
        if field in labels and labels[field] is not None:
            merged["labels"][field] = labels[field]
            merged.setdefault("label_source", {})[field] = rec_source.get(field) or default_source
    if "review" in record:
        merged["review"] = record["review"]
    return merged


# --- manual span / box annotation (human-added detections) -------------------
# A reviewer can add detections the pipeline missed (a PII span, an injection
# span, or an image PII box) or delete a wrong one. These edits layer on top of
# the row's detections exactly like label overrides layer on labels: human items
# carry ``detector="human"`` so provenance stays explicit and gold is never
# silently overwritten. The stored edit is minimal (offsets + type); span_ids,
# scores, and the ``human`` detector are stamped at apply time so re-applying is
# idempotent.
HUMAN_DETECTOR = "human"

# Text-span collections and the field naming their type.
_SPAN_COLLECTIONS = (
    ("pii_spans", "entity_type"),
    ("prompt_injection_spans", "attack_type"),
)


def _span_key(span: Dict[str, Any], type_field: str) -> Tuple[int, int, str]:
    """Stable identity for a text span: (start, end, type). Used for deletes."""
    return (
        int(span.get("start", -1)),
        int(span.get("end", -1)),
        str(span.get(type_field) or ""),
    )


def _next_id(prefix: str, existing: set) -> str:
    n = 1
    while f"{prefix}_{n:04d}" in existing:
        n += 1
    return f"{prefix}_{n:04d}"


def _anonymize(text: str, spans: List[Dict[str, Any]]) -> str:
    """Replace each PII span's slice with ``<ENTITY_TYPE>`` (right-to-left so
    offsets stay valid). Mirrors the converter's deterministic anonymization so
    a manually added span is reflected in ``sanitized_text``."""
    if not text or not spans:
        return text
    ordered = sorted(
        (s for s in spans if isinstance(s.get("start"), int)),
        key=lambda s: s["start"],
        reverse=True,
    )
    out = text
    for s in ordered:
        st, en = int(s.get("start", -1)), int(s.get("end", -1))
        if 0 <= st < en <= len(out):
            out = out[:st] + f"<{s.get('entity_type', 'MISC')}>" + out[en:]
    return out


def clean_span_edits(
    span_edits: Optional[Dict[str, Any]], row: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Validate and normalize incoming span edits; returns ``None`` if empty.

    Added text spans must have ``0 <= start < end`` (bounded by the row's text
    when known) and a non-empty type; deletes are normalized to ``[start, end,
    type]`` keys. Image boxes need a 4-number ``box`` and a non-empty type.
    Entity-type strings are taken as-is from the UI dropdown (the canonical enum
    is enforced there); we only require non-empty.
    """
    if not span_edits:
        return None
    content = (row or {}).get("content") or {}
    max_len = max(
        len(content.get("input_text") or ""), len(content.get("ocr_text") or "")
    )
    clean: Dict[str, Any] = {}

    for coll, type_field in _SPAN_COLLECTIONS:
        edit = span_edits.get(coll) or {}
        added: List[Dict[str, Any]] = []
        for s in edit.get("added") or []:
            start, end = int(s.get("start")), int(s.get("end"))
            if not 0 <= start < end or (max_len and end > max_len):
                raise ValueError(f"{coll} span out of range: {start}-{end}")
            typ = str(s.get(type_field) or "").strip()
            if not typ:
                raise ValueError(f"{coll} span missing {type_field}")
            added.append(
                {type_field: typ, "start": start, "end": end, "text": str(s.get("text") or "")}
            )
        deleted = [
            [int(k[0]), int(k[1]), str(k[2])] for k in (edit.get("deleted") or [])
        ]
        if added or deleted:
            clean[coll] = {"added": added, "deleted": deleted}

    bedit = span_edits.get("boxes") or {}
    badded: List[Dict[str, Any]] = []
    for b in bedit.get("added") or []:
        box = b.get("box") or []
        if len(box) != 4 or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in box
        ):
            raise ValueError("box must be [x0,y0,x1,y1] numbers")
        typ = str(b.get("entity_type") or "").strip()
        if not typ:
            raise ValueError("box missing entity_type")
        badded.append(
            {"entity_type": typ, "box": [float(v) for v in box], "text": str(b.get("text") or "")}
        )
    bdeleted = [str(x) for x in (bedit.get("deleted") or [])]
    if badded or bdeleted:
        clean["boxes"] = {"added": badded, "deleted": bdeleted}

    return clean or None


def _merge_span_edits(
    row: Dict[str, Any], span_edits: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Apply human span/box edits onto ``row`` in place (row is already a copy).

    Deletes drop matching items; adds append items stamped with ``human``
    provenance. When PII spans change, ``sanitized_text`` is recomputed so the
    displayed redaction stays honest.
    """
    if not span_edits:
        return row
    det = row.setdefault("detections", {})
    geo = row.setdefault("geometry", {})
    pii_changed = False

    for coll, type_field in _SPAN_COLLECTIONS:
        edit = span_edits.get(coll)
        if not edit:
            continue
        spans = list(det.get(coll) or [])
        deleted = {tuple(k) for k in (edit.get("deleted") or [])}
        if deleted:
            kept = [s for s in spans if _span_key(s, type_field) not in deleted]
            if len(kept) != len(spans) and coll == "pii_spans":
                pii_changed = True
            spans = kept
        existing_ids = {s.get("span_id") for s in spans}
        for a in edit.get("added") or []:
            if coll == "pii_spans":
                sid = _next_id("human_pii", existing_ids)
                spans.append(
                    new_pii_span(
                        sid, a[type_field], a["start"], a["end"],
                        a.get("text", ""), score=1.0, detector=HUMAN_DETECTOR,
                    )
                )
                pii_changed = True
            else:
                sid = _next_id("human_pi", existing_ids)
                spans.append(
                    new_prompt_injection_span(
                        sid, a[type_field], a["start"], a["end"],
                        a.get("text", ""), score=1.0, detector=HUMAN_DETECTOR,
                    )
                )
            existing_ids.add(sid)
        det[coll] = spans

    bedit = span_edits.get("boxes")
    if bedit:
        boxes = list(geo.get("source_pii_boxes") or [])
        deleted = set(bedit.get("deleted") or [])
        if deleted:
            boxes = [b for b in boxes if b.get("box_id") not in deleted]
        existing_ids = {b.get("box_id") for b in boxes}
        for a in bedit.get("added") or []:
            bid = _next_id("human_box", existing_ids)
            existing_ids.add(bid)
            boxes.append(
                {
                    "box_id": bid,
                    "entity_type": a["entity_type"],
                    "text": a.get("text", ""),
                    "box": a["box"],
                    "detector": HUMAN_DETECTOR,
                }
            )
        geo["source_pii_boxes"] = boxes

    if pii_changed:
        content = row.setdefault("content", {})
        if content.get("input_text"):
            content["sanitized_text"] = _anonymize(
                content["input_text"], det.get("pii_spans") or []
            )
    return row


def _apply_override(row: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``row`` with human labels/review/span-edits applied."""
    merged = _apply_label_layer(row, override, "human")
    merged = _merge_span_edits(merged, override.get("span_edits"))
    merged["_overridden"] = True
    return merged


def load_rows(data_file: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Load rows with overrides applied, plus summary stats and a mask per row."""
    rows = load_jsonl(data_file)
    api_labels = load_overrides(api_labels_path_for(data_file))
    overrides = load_overrides(override_path_for(data_file))
    out: List[Dict[str, Any]] = []
    reviewed = 0
    routed = 0
    for row in rows:
        iid = row.get("input_id")
        # API/router labels are the base layer; human overrides win on top.
        if iid in api_labels:
            row = _apply_label_layer(row, api_labels[iid], "api")
            row["_routed"] = True
            routed += 1
        if iid in overrides:
            row = _apply_override(row, overrides[iid])
        row["_label_mask"] = derive_label_mask(row)
        status = (row.get("review") or {}).get("status")
        if status == "human_reviewed":
            reviewed += 1
        out.append(row)
    stats = {
        "total": len(out),
        "reviewed": reviewed,
        "remaining": len(out) - reviewed,
        "routed": routed,
        "override_path": override_path_for(data_file).relative_to(REPO_ROOT).as_posix(),
    }
    return out, stats


def get_row(data_file: Path, input_id: str) -> Optional[Dict[str, Any]]:
    """Return one row (overrides applied) by ``input_id``, or ``None``."""
    rows, _ = load_rows(data_file)
    for row in rows:
        if row.get("input_id") == input_id:
            return row
    return None


def _coerce_label(field: str, value: Any) -> Any:
    """Normalize incoming label values to bool / action-string / None."""
    if value is None or value == "null" or value == "":
        return None
    if field == ACTION_FIELD:
        if value not in ACTION_VALUES:
            raise ValueError(f"action must be one of {ACTION_VALUES} or null")
        return value
    if isinstance(value, bool):
        return value
    if value in ("true", "True", True, 1):
        return True
    if value in ("false", "False", False, 0):
        return False
    raise ValueError(f"{field} must be true/false/null")


def save_override(
    data_file: Path,
    input_id: str,
    labels: Dict[str, Any],
    review: Dict[str, Any],
    reviewer: Optional[str] = None,
    span_edits: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate and append a human override record; returns the written record.

    ``span_edits`` (optional) adds/deletes human detections; it is validated and
    bounded against the row's text before being persisted into the record.
    """
    clean_labels: Dict[str, Any] = {}
    for field in LABEL_FIELDS:
        clean_labels[field] = _coerce_label(field, labels.get(field))
    label_source = {
        field: ("human" if clean_labels[field] is not None else None)
        for field in LABEL_FIELDS
    }
    clean_edits = clean_span_edits(span_edits, get_row(data_file, input_id))
    status = (review or {}).get("status") or "human_reviewed"
    record = {
        "input_id": input_id,
        "labels": clean_labels,
        "label_source": label_source,
        "review": {
            "status": status,
            "reviewer": reviewer or (review or {}).get("reviewer"),
            "notes": (review or {}).get("notes", ""),
        },
        "timestamp": _now(),
    }
    if clean_edits:
        record["span_edits"] = clean_edits
    out_path = override_path_for(data_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
