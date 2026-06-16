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


def map_span_to_box(
    span: Dict[str, Any],
    segments: Sequence[OcrSegment],
    *,
    padding: float = 2.0,
    image_size: Optional[Sequence[int]] = None,
) -> Optional[RedactionBox]:
    """Map one PII span to a merged image region, or ``None`` if it touches no
    OCR segment (nothing to redact)."""
    bounds = [0, 0, image_size[0], image_size[1]] if image_size else None
    s, e = int(span["start"]), int(span["end"])
    idxs = [i for i, seg in enumerate(segments) if _overlaps(s, e, seg.start, seg.end)]
    if not idxs:
        return None
    merged = _merge_boxes([segments[i].box for i in idxs])
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
