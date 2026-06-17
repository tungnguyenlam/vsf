"""Span-to-box mapping and localized image redaction.

This is stage 4–5 of ``docs/image-safety-pipeline.md``: PII spans detected on
the OCR ``full_text`` are character-aligned to OCR segments, the overlapping
segment boxes are merged (with optional padding) into one region per span, and
those regions are blurred or filled in the image.

The mapping (:func:`map_spans_to_boxes`) is pure and dependency-free so it is
cheap to unit-test. Only :func:`redact_image` touches Pillow, imported lazily.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from src.pipeline.Image.ocr import OcrSegment

PathLike = Union[str, Path]


@dataclass
class RedactionBox:
    """One merged region to redact, with the boxes/segments it came from.

    - ``box``: merged ``[x0, y0, x1, y1]`` to redact (padding already applied).
    - ``segment_indices``: indices into the OCR segment list it covers.
    """

    box: List[float]
    segment_indices: List[int]


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open span overlap; zero-length spans never overlap."""
    return a_start < b_end and b_start < a_end


def _merge_boxes(boxes: Sequence[Sequence[float]]) -> List[float]:
    xs0 = [b[0] for b in boxes]
    ys0 = [b[1] for b in boxes]
    xs1 = [b[2] for b in boxes]
    ys1 = [b[3] for b in boxes]
    return [min(xs0), min(ys0), max(xs1), max(ys1)]


def _pad(box: Sequence[float], padding: float, bounds: Optional[Sequence[float]]) -> List[float]:
    x0, y0, x1, y1 = box[0] - padding, box[1] - padding, box[2] + padding, box[3] + padding
    if bounds is not None:
        bx0, by0, bx1, by1 = bounds
        x0, y0 = max(x0, bx0), max(y0, by0)
        x1, y1 = min(x1, bx1), min(y1, by1)
    return [x0, y0, x1, y1]


def _clip_segment_box(seg: OcrSegment, start: int, end: int) -> List[float]:
    """Horizontally clip a segment's box to the character sub-range ``[start, end)``.

    OCR segment boxes span a whole word/line; when a PII span only covers part of
    a segment's characters (e.g. a reviewer selects 2-3 words inside a longer OCR
    line box), redacting the full box over-masks. This linearly interpolates the
    box's x-extent by character offset so only the selected slice is covered.
    Assumes a single horizontal line of left-to-right text (true for OCR line
    boxes); it is proportional to character count, so variable-width fonts make
    it approximate but far tighter than the whole box. Vertical extent is kept.
    """
    cs, ce = seg.start, seg.end
    x0, y0, x1, y1 = seg.box
    width_chars = ce - cs
    os_, oe = max(start, cs), min(end, ce)
    if width_chars <= 0 or oe <= os_:
        return [x0, y0, x1, y1]
    f0 = (os_ - cs) / width_chars
    f1 = (oe - cs) / width_chars
    return [x0 + f0 * (x1 - x0), y0, x0 + f1 * (x1 - x0), y1]


def map_span_to_box(
    span: Dict[str, Any],
    segments: Sequence[OcrSegment],
    *,
    padding: float = 2.0,
    image_size: Optional[Sequence[int]] = None,
) -> Optional[RedactionBox]:
    """Map one PII span to a merged image region, or ``None`` if it touches no
    OCR segment (nothing to redact).

    Each overlapping segment box is clipped to the span's character sub-range
    before merging, so a span covering only part of an OCR line redacts only that
    part (see :func:`_clip_segment_box`). A span covering a full segment yields
    the full box, unchanged."""
    bounds = [0, 0, image_size[0], image_size[1]] if image_size else None
    s, e = int(span["start"]), int(span["end"])
    idxs, clipped = [], []
    for i, seg in enumerate(segments):
        if not _overlaps(s, e, seg.start, seg.end):
            continue
        idxs.append(i)
        clipped.append(_clip_segment_box(seg, s, e))
    if not idxs:
        return None
    merged = _merge_boxes(clipped)
    return RedactionBox(box=_pad(merged, padding, bounds), segment_indices=idxs)


def map_spans_to_boxes(
    spans: Sequence[Dict[str, Any]],
    segments: Sequence[OcrSegment],
    *,
    padding: float = 2.0,
    image_size: Optional[Sequence[int]] = None,
) -> List[RedactionBox]:
    """Map each PII span to a merged image region from overlapping OCR segments.

    ``spans`` are dicts with ``start``/``end`` character offsets into the same
    text the segments are aligned to. Spans that touch no segment are skipped
    (nothing to redact). ``image_size`` is ``(width, height)`` used to clamp
    padded boxes to the image bounds.
    """
    out: List[RedactionBox] = []
    for span in spans:
        box = map_span_to_box(span, segments, padding=padding, image_size=image_size)
        if box is not None:
            out.append(box)
    return out


def recompute_redactions(
    row: Dict[str, Any],
    *,
    src_image: PathLike,
    dst_path: PathLike,
    method: str = "blur",
    padding: float = 3.0,
) -> Dict[str, Any]:
    """Re-derive box mappings + redaction from a row's current ``pii_spans``.

    Shared core for the batch redaction stage and the webdemo's live recompute.
    Given a row that already has ``geometry.ocr_boxes`` and ``detections.pii_spans``
    (whatever their provenance — source-aligned, pipeline, or human), this:

    - maps each PII span to overlapping OCR segment boxes (char-offset overlap),
      fills the span's ``box_ids`` in place, and records one ``redaction_metadata``
      entry per mapped span;
    - additionally redacts human image-drawn boxes — ``geometry.source_pii_boxes``
      with ``detector == "human"`` carry a raw pixel ``box`` and no OCR offsets, so
      their box is redacted directly;
    - renders the redacted image to ``dst_path``.

    Returns ``{"pii_spans", "redaction_metadata", "regions"}`` where ``regions`` is
    the unified UI list (one entry per redactable item, pixel ``box`` included).
    The row's ``pii_spans`` are mutated in place (``box_ids`` filled).
    """
    from src.pipeline.Datasets.safety_v0_schema import new_redaction

    geometry = row.get("geometry") or {}
    ocr_boxes = geometry.get("ocr_boxes") or []
    segments = [
        OcrSegment(text=b["text"], start=b["start"], end=b["end"], box=b["box"],
                   confidence=b.get("confidence"))
        for b in ocr_boxes
    ]
    box_ids_by_index = [b.get("box_id") for b in ocr_boxes]
    size = image_size(src_image) if src_image else None

    pii_spans = list((row.get("detections") or {}).get("pii_spans") or [])
    redactions: List[Dict[str, Any]] = []
    redaction_boxes: List[List[float]] = []
    regions: List[Dict[str, Any]] = []

    for span in pii_spans:
        rbox = map_span_to_box(span, segments, padding=padding, image_size=size)
        if rbox is None:
            span["box_ids"] = []
            continue
        box_ids = [box_ids_by_index[j] for j in rbox.segment_indices if box_ids_by_index[j]]
        span["box_ids"] = box_ids
        redactions.append(
            new_redaction(
                f"redact_{len(redactions) + 1:04d}",
                [span["span_id"]],
                box_ids,
                rbox.box,
                reason="pii",
                method=method,
            )
        )
        redaction_boxes.append(rbox.box)
        regions.append({
            "span_id": span.get("span_id"),
            "entity_type": span.get("entity_type"),
            "text": span.get("text", ""),
            "box": rbox.box,
            "box_ids": box_ids,
            "detector": span.get("detector"),
            "source_box_id": span.get("source_box_id"),
        })

    # Human image-drawn boxes: pixel regions with no OCR char offsets.
    for hb in geometry.get("source_pii_boxes") or []:
        if hb.get("detector") != "human":
            continue
        box = hb.get("box")
        if not (isinstance(box, (list, tuple)) and len(box) == 4):
            continue
        padded = _pad(box, padding, [0, 0, size[0], size[1]] if size else None)
        redactions.append(
            new_redaction(
                f"redact_{len(redactions) + 1:04d}",
                [],
                [hb.get("box_id")] if hb.get("box_id") else [],
                padded,
                reason="pii",
                method=method,
            )
        )
        redaction_boxes.append(padded)
        regions.append({
            "span_id": None,
            "entity_type": hb.get("entity_type"),
            "text": hb.get("text", ""),
            "box": padded,
            "box_ids": [],
            "detector": "human",
            "source_box_id": hb.get("box_id"),
        })

    if src_image is not None:
        redact_image(src_image, dst_path, redaction_boxes, method=method)
    return {"pii_spans": pii_spans, "redaction_metadata": redactions, "regions": regions}


def redact_image(
    src_path: PathLike,
    dst_path: PathLike,
    boxes: Sequence[Sequence[float]],
    *,
    method: str = "blur",
    blur_radius: int = 12,
) -> str:
    """Write a redacted copy of ``src_path`` to ``dst_path``.

    ``method`` is ``"blur"`` (Gaussian over each region) or ``"fill"`` (solid
    black rectangle). Returns the destination path. Always writes a file, even
    when ``boxes`` is empty, so the redacted artifact exists for every image row.
    """
    from PIL import Image, ImageDraw, ImageFilter

    if method not in ("blur", "fill"):
        raise ValueError(f"Unknown redaction method {method!r}; use 'blur' or 'fill'.")

    img = Image.open(src_path).convert("RGB")
    for box in boxes:
        region = tuple(int(round(v)) for v in box)
        x0, y0, x1, y1 = region
        if x1 <= x0 or y1 <= y0:
            continue
        if method == "blur":
            crop = img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(blur_radius))
            img.paste(crop, (x0, y0))
        else:
            ImageDraw.Draw(img).rectangle((x0, y0, x1, y1), fill="black")

    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)
    return str(dst)


def image_size(src_path: PathLike) -> List[int]:
    """Return ``[width, height]`` of an image (lazy Pillow import)."""
    from PIL import Image

    with Image.open(src_path) as img:
        return [img.width, img.height]
