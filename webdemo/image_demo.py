"""Image-aware demo pipeline for the webdemo Analyze tab.

Mirrors the per-row image flow the Annotate tab works over, but starting from a
freshly uploaded image instead of a canonical ``safety_v0`` row:

    upload -> OCR (text + word boxes) -> PII detection on the OCR text
           -> span->box mapping + localized redaction -> (optional) VLM router

It reuses the exact same building blocks as the batch pipeline and the review
tab (``Image.ocr``, ``Image.redaction``, the PII pipeline, ``Router``) so the
demo shows the real pipeline, not a re-implementation.

Uploads and redacted previews are written under the ``safety_v0`` data root so
they are servable through the existing ``/api/review/image`` route (which is
constrained to that root). A small in-memory cache keeps the built row around so
the paid VLM router can be run on the same artifact without re-doing OCR.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.pipeline.Datasets.safety_v0_schema import new_ocr_box, new_pii_span, new_row
from src.pipeline.Datasets.safety_v0_sources import DEFAULT_DATA_ROOT, REPO_ROOT
from src.pipeline.Image.ocr import get_ocr_adapter
from src.pipeline.Image.redaction import recompute_redactions

DATA_ROOT = DEFAULT_DATA_ROOT
UPLOAD_DIR = DATA_ROOT / "review" / "demo" / "uploads"
REDACTED_DIR = DATA_ROOT / "review" / "demo" / "redacted"
ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

# Cache the heavy OCR adapter (PaddleOCR warms up slowly) and the built demo
# rows (so "Run router" reuses the same artifact instead of re-running OCR).
_ocr_adapter = None
_demo_rows: Dict[str, Dict[str, Any]] = {}


def get_ocr_adapter_cached(adapter_name: str = "paddleocr", lang: str = "vi"):
    global _ocr_adapter
    if _ocr_adapter is None:
        _ocr_adapter = get_ocr_adapter(adapter_name, lang=lang)
    return _ocr_adapter


def _rel(path: Path) -> str:
    """Repo-root-relative POSIX path (the form the image route expects)."""
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _save_upload(file_storage) -> Path:
    """Persist an uploaded image under the data root; return its path.

    The suffix is validated against an allowlist; the stored name is a fresh
    UUID so concurrent demo users never collide.
    """
    suffix = Path(file_storage.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(
            f"Unsupported image type {suffix!r}. Allowed: "
            f"{', '.join(sorted(ALLOWED_SUFFIXES))}."
        )
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dst = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    file_storage.save(dst)
    return dst


def _anonymize(text: str, spans: List[Dict[str, Any]]) -> str:
    """Replace each PII span with ``<ENTITY_TYPE>`` right-to-left (offsets stay
    valid). Mirrors the converter / review-tab anonymization so the sanitized
    preview the router sees matches what we display."""
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


def detect_pii_spans(pii_pipeline, text: str, id_prefix: str) -> List[Dict[str, Any]]:
    """Run the PII pipeline on ``text`` and return canonical ``pii_span`` dicts.

    Offsets index into ``text`` exactly, so spans over the OCR text map straight
    back to OCR word boxes for redaction. Exact-duplicate spans are collapsed
    (highest score wins) to match the Analyze text card.
    """
    if not text.strip():
        return []
    results = pii_pipeline.predict(text)
    best: Dict[tuple, Any] = {}
    for r in results:
        key = (r.start, r.end)
        if key not in best or r.score > best[key].score:
            best[key] = r
    spans = []
    for i, r in enumerate(sorted(best.values(), key=lambda x: (x.start, x.end)), 1):
        spans.append(
            new_pii_span(
                f"{id_prefix}_{i:04d}",
                r.entity_type,
                r.start,
                r.end,
                text[r.start : r.end],
                score=round(float(r.score), 4),
                detector="pipeline",
            )
        )
    return spans


def process_image(
    file_storage,
    input_text: str,
    pii_pipeline,
    pipeline_name: str,
    *,
    adapter_name: str = "paddleocr",
    lang: str = "vi",
    redaction_method: str = "blur",
) -> Dict[str, Any]:
    """Run the full image safety pipeline on an uploaded image.

    Returns a JSON-serializable dict with the OCR text, detected PII spans
    (offset into the OCR text), the unified redaction regions (pixel boxes),
    image dimensions, and repo-relative URLs for the original and redacted
    images. A ``demo_id`` references the cached row for a later router call.
    """
    src_image = _save_upload(file_storage)

    adapter = get_ocr_adapter_cached(adapter_name, lang=lang)
    ocr_result = adapter.run(src_image)
    ocr_boxes = [
        new_ocr_box(f"box_{i:04d}", seg.text, seg.start, seg.end, seg.box, seg.confidence)
        for i, seg in enumerate(ocr_result.segments, 1)
    ]
    ocr_text = ocr_result.full_text

    ocr_spans = detect_pii_spans(pii_pipeline, ocr_text, "ocr_pii")

    demo_id = uuid.uuid4().hex
    row = new_row(
        f"demo_{demo_id}",
        f"webdemo_upload/{pipeline_name}",
        has_image=True,
        has_text=bool(input_text.strip()),
        has_ocr=bool(ocr_boxes),
        original_image_path=_rel(src_image),
        input_text=input_text,
        ocr_text=ocr_text,
    )
    row["geometry"]["ocr_boxes"] = ocr_boxes
    row["detections"]["pii_spans"] = ocr_spans

    REDACTED_DIR.mkdir(parents=True, exist_ok=True)
    dst = REDACTED_DIR / f"{demo_id}.png"
    result = recompute_redactions(
        row, src_image=src_image, dst_path=dst, method=redaction_method
    )

    # Persist sanitized text + redacted path on the row so the router sees the
    # same redacted artifact the Annotate tab would feed it.
    row["content"]["redacted_image_path"] = _rel(dst)
    row["content"]["sanitized_ocr_text"] = _anonymize(ocr_text, ocr_spans)
    row["detections"]["redaction_metadata"] = result["redaction_metadata"]
    from src.pipeline.Image.redaction import image_size as _image_size

    size = _image_size(src_image)
    _demo_rows[demo_id] = row

    return {
        "demo_id": demo_id,
        "original_url": _rel(src_image),
        "redacted_url": _rel(dst),
        "ocr_text": ocr_text,
        "sanitized_ocr_text": row["content"]["sanitized_ocr_text"],
        "image_size": size,
        "ocr_box_count": len(ocr_boxes),
        "pii_spans": ocr_spans,
        "regions": result["regions"],
    }


def get_demo_row(demo_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the cached row for a demo image, or ``None`` if expired/unknown."""
    if not demo_id:
        return None
    return _demo_rows.get(demo_id)
