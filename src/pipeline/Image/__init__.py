"""Image safety preprocessing: OCR adapters and span-to-box redaction.

These are the deterministic image-path stages from ``docs/image-safety-pipeline.md``
and ``docs/full-safety-pipeline.md``:

1. ``ocr`` — turn an image into normalized text + word boxes behind a narrow,
   swappable :class:`~src.pipeline.Image.ocr.OcrAdapter` interface.
2. ``redaction`` — map PII text spans back to OCR boxes and blur/fill those
   regions in the image.

The VLM safety router (the final decision) is intentionally NOT here; it lives
behind its own interface and is fired explicitly.
"""

from src.pipeline.Image.ocr import (
    OcrAdapter,
    OcrResult,
    OcrSegment,
    get_ocr_adapter,
    list_ocr_adapter_names,
)
from src.pipeline.Image.redaction import (
    RedactionBox,
    map_span_to_box,
    map_spans_to_boxes,
    redact_image,
)

__all__ = [
    "OcrAdapter",
    "OcrResult",
    "OcrSegment",
    "get_ocr_adapter",
    "list_ocr_adapter_names",
    "RedactionBox",
    "map_span_to_box",
    "map_spans_to_boxes",
    "redact_image",
]
