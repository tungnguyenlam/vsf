"""OCR adapters behind one narrow interface.

The pipeline only ever sees :class:`OcrResult` (a ``full_text`` string plus
character-aligned :class:`OcrSegment` word boxes). Concrete OCR engines are
hidden behind :class:`OcrAdapter` and selected by name via
:func:`get_ocr_adapter`, so a different engine is one config flip, not a code
change (see the swappability principle in ``CLAUDE.md``).

``full_text`` is built by joining segment texts; each segment carries the exact
``[start, end)`` character offsets into ``full_text`` so PII spans detected on
``full_text`` map straight back to image boxes (see ``redaction.py``).

The real engine (PaddleOCR) is imported lazily inside the adapter so importing
this module — and running the test suite — never requires the heavy dependency.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]


@dataclass
class OcrSegment:
    """One recognized word/line, aligned to ``OcrResult.full_text``.

    ``box`` is an axis-aligned ``[x0, y0, x1, y1]`` in pixels.
    """

    text: str
    start: int
    end: int
    box: List[float]
    confidence: Optional[float] = None


@dataclass
class OcrResult:
    full_text: str
    segments: List[OcrSegment] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.segments


def build_full_text(
    items: Sequence[Tuple[str, List[float], Optional[float]]],
    *,
    separator: str = " ",
) -> OcrResult:
    """Assemble an :class:`OcrResult` from ``(text, box, confidence)`` items.

    Offsets are computed here so every adapter shares identical text/offset
    semantics regardless of engine. ``separator`` is inserted between segments
    and counted in the offsets so spans over ``full_text`` stay exact.
    """
    parts: List[str] = []
    segments: List[OcrSegment] = []
    cursor = 0
    for i, (text, box, conf) in enumerate(items):
        if i > 0 and separator:
            parts.append(separator)
            cursor += len(separator)
        start = cursor
        end = cursor + len(text)
        parts.append(text)
        cursor = end
        segments.append(OcrSegment(text=text, start=start, end=end, box=list(box), confidence=conf))
    return OcrResult(full_text="".join(parts), segments=segments)


def quad_to_aabb(quad: Sequence[Sequence[float]]) -> List[float]:
    """Convert a 4-point polygon ``[[x,y],...]`` to ``[x0,y0,x1,y1]``."""
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    return [min(xs), min(ys), max(xs), max(ys)]


def _is_flat_box(box: Any) -> bool:
    try:
        return len(box) == 4 and all(not hasattr(v, "__len__") for v in box)
    except TypeError:
        return False


def _normalize_box(box_or_poly: Any) -> List[float]:
    if _is_flat_box(box_or_poly):
        return [float(v) for v in box_or_poly]
    return quad_to_aabb(box_or_poly)


class OcrAdapter(ABC):
    """Narrow OCR interface: image path in, normalized :class:`OcrResult` out."""

    name: str = "ocr"

    @abstractmethod
    def run(self, image_path: PathLike) -> OcrResult:  # pragma: no cover - interface
        raise NotImplementedError


class PaddleOcrAdapter(OcrAdapter):
    """PaddleOCR backend. The ``paddleocr`` package is imported lazily on first
    :meth:`run`, so this class can be constructed (and unit-tested for offset
    logic) without the dependency installed.
    """

    name = "paddleocr"

    def __init__(
        self,
        lang: str = "vi",
        use_angle_cls: bool = True,
        enable_mkldnn: bool = False,
        **engine_kwargs: Any,
    ):
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        # oneDNN (MKLDNN) is off by default: paddlepaddle 3.3.x crashes in its
        # PIR executor (ConvertPirAttribute2RuntimeAttribute) when oneDNN is on
        # for these models on CPU. Overridable for builds where it works.
        self.enable_mkldnn = enable_mkldnn
        self.engine_kwargs = engine_kwargs
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:  # pragma: no cover - depends on install
                raise ImportError(
                    "PaddleOCR is not installed. Install it (e.g. "
                    "`pip install paddleocr paddlepaddle`) or select a different "
                    "OCR adapter via get_ocr_adapter(name=...)."
                ) from exc
            sig = inspect.signature(PaddleOCR)
            params = sig.parameters
            kwargs = {"lang": self.lang, **self.engine_kwargs}
            if "enable_mkldnn" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            ):
                kwargs.setdefault("enable_mkldnn", self.enable_mkldnn)
            if "use_doc_orientation_classify" in params:
                kwargs.setdefault("use_doc_orientation_classify", False)
                kwargs.setdefault("use_doc_unwarping", False)
                kwargs.setdefault("use_textline_orientation", self.use_angle_cls)
            else:
                kwargs.setdefault("use_angle_cls", self.use_angle_cls)
                kwargs.setdefault("show_log", False)
            self._engine = PaddleOCR(**kwargs)
        return self._engine

    def run(self, image_path: PathLike) -> OcrResult:
        engine = self._get_engine()
        raw = engine.ocr(str(image_path))
        return self._normalize(raw)

    @staticmethod
    def _normalize(raw: Any) -> OcrResult:
        """Normalize PaddleOCR output to an :class:`OcrResult`.

        PaddleOCR returns ``[[ [quad, (text, conf)], ... ]]`` (one list per
        page). We read page 0 and keep engine reading order.
        """
        if not raw:
            return OcrResult(full_text="", segments=[])
        page = raw[0] if isinstance(raw, list) and raw else raw
        if isinstance(page, dict) or all(hasattr(page, attr) for attr in ("get", "keys")):
            # Values may be numpy arrays, so use explicit length checks instead of
            # truthiness (`np.ndarray or ...` raises on non-scalar arrays). An
            # image with no detected text yields empty arrays here.
            texts = page.get("rec_texts")
            texts = list(texts) if texts is not None and len(texts) else []
            scores = page.get("rec_scores")
            scores = list(scores) if scores is not None and len(scores) else [None] * len(texts)
            polys = page.get("rec_polys")
            if polys is None or len(polys) == 0:
                polys = page.get("rec_boxes")
            polys = list(polys) if polys is not None and len(polys) else []
            items = []
            for text, poly, conf in zip(texts, polys, scores):
                if not text:
                    continue
                items.append((str(text), _normalize_box(poly), float(conf) if conf is not None else None))
            return build_full_text(items)
        items: List[Tuple[str, List[float], Optional[float]]] = []
        for entry in page or []:
            try:
                quad, (text, conf) = entry[0], entry[1]
            except (TypeError, ValueError, IndexError):
                continue
            if not text:
                continue
            items.append((str(text), quad_to_aabb(quad), float(conf) if conf is not None else None))
        return build_full_text(items)


# --- Registry (single source of truth for adapter selection) -----------------
_OCR_ADAPTERS: Dict[str, type] = {
    "paddleocr": PaddleOcrAdapter,
}


def list_ocr_adapter_names() -> List[str]:
    return sorted(_OCR_ADAPTERS)


def get_ocr_adapter(name: str = "paddleocr", **kwargs: Any) -> OcrAdapter:
    """Construct an OCR adapter by name. Default engine is PaddleOCR."""
    try:
        cls = _OCR_ADAPTERS[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown OCR adapter {name!r}. Available: {list_ocr_adapter_names()}"
        ) from exc
    return cls(**kwargs)
