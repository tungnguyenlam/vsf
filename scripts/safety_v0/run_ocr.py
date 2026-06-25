"""OCR stage: fill ``geometry.ocr_boxes`` + ``content.ocr_text`` for image rows.

Reads canonical ``safety_v0`` rows (converter output), runs an OCR adapter on
each row's ``original_image_path``, and writes rows with normalized word boxes
and extracted text. Text-only rows pass through unchanged. The OCR engine is
selected by ``--adapter`` (default ``paddleocr``) so it is a config flip.

Default paths come from the source registry::

    python scripts/safety_v0/run_ocr.py --slug webpii
    # data/safety_v0/converted/webpii/source_canonical.jsonl
    #   -> data/safety_v0/ocr/webpii/ocr.jsonl

Override with ``--input`` / ``--output`` to run on arbitrary files (the webdemo
sample, smoke tests, etc.).
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import new_ocr_box, new_pii_span, validate_row  # noqa: E402
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    ocr_path,
)
from src.pipeline.Image.ocr import get_ocr_adapter  # noqa: E402

SOURCE_PII_ALIGNMENT_DETECTOR = "source_webpii_ocr_alignment"

# WebPII source keys we never turn into redaction spans (see
# docs/redaction-policy.md and convert_webpii.py:map_webpii_key_to_presidio).
# Two groups:
#   - Free-text fields (MISC): a whole personalized message/instruction whose only
#     real PII (name, address) is already captured by dedicated boxes, so redacting
#     the entire field over-masks non-PII text.
#   - Transaction identifiers (order/job/promo codes): not personal identity.
# New conversions no longer create boxes for these, but already-converted data may
# still carry them; this set drops them at alignment time (cheap --realign, no
# re-OCR). The source box is kept for the record but yields no span. Numeric copy
# suffixes are stripped before the membership check.
NON_REDACTABLE_SOURCE_KEYS = {
    "PII_GIFT_MESSAGE",
    "PII_DELIVERY_INSTRUCTIONS",
    "PII_PO_NUMBER",
    "PII_JOB_CODE",
    "PII_PROMO_CODE",
}


def _source_key_base(source_box: Dict[str, Any]) -> str:
    key = str(source_box.get("source_key") or "").upper()
    return re.sub(r"\d+$", "", key)


def _resolve_image(path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p if p.exists() else None


def _area(box: Sequence[float]) -> float:
    if len(box) != 4:
        return 0.0
    return max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1]))


def _intersection_area(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != 4 or len(b) != 4:
        return 0.0
    x0 = max(float(a[0]), float(b[0]))
    y0 = max(float(a[1]), float(b[1]))
    x1 = min(float(a[2]), float(b[2]))
    y1 = min(float(a[3]), float(b[3]))
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _ocr_coverage(source_box: Sequence[float], ocr_box: Sequence[float]) -> float:
    denom = _area(ocr_box)
    if denom <= 0:
        return 0.0
    return _intersection_area(source_box, ocr_box) / denom


def _source_coverage(source_box: Sequence[float], ocr_box: Sequence[float]) -> float:
    """Fraction of the *source* PII box that an OCR box covers.

    Complements :func:`_ocr_coverage`: a tight source box (e.g. a card last-4)
    sitting inside a wide OCR line box has low OCR-coverage but ~full
    source-coverage, so this catches sub-token PII the OCR tokenizes into a line.
    """
    denom = _area(source_box)
    if denom <= 0:
        return 0.0
    return _intersection_area(source_box, ocr_box) / denom


def _norm_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text).casefold()).strip()
    return re.sub(r"[^\w @.+-]+", "", text)


def _text_compatible(source_text: str, ocr_text: str) -> bool:
    source = _norm_text(source_text)
    ocr = _norm_text(ocr_text)
    if not source or not ocr:
        return True
    return ocr in source or source in ocr


def source_box_ocr_matches(
    source_box: Dict[str, Any],
    ocr_boxes: Sequence[Dict[str, Any]],
    *,
    min_ocr_coverage: float = 0.5,
    min_source_coverage: float = 0.6,
) -> List[Dict[str, Any]]:
    """Return OCR boxes geometrically inside one WebPII source PII box.

    WebPII gives UI element boxes, while OCR gives word/line boxes. A match is
    accepted when EITHER the OCR box is mostly inside the source box
    (``min_ocr_coverage`` — large field containing OCR words) OR the source box
    is mostly inside the OCR box (``min_source_coverage`` — a tight PII token the
    OCR merged into a wider line, e.g. a card last-4 inside "ending in 2522
    Change"). Text compatibility is a precision boost; geometry still wins when
    OCR text is noisy.
    """
    source_geom = source_box.get("box") or []
    source_text = str(source_box.get("text") or "")
    candidates: List[Tuple[bool, int, Dict[str, Any]]] = []
    for index, ocr_box in enumerate(ocr_boxes):
        ocr_box_geom = ocr_box.get("box") or []
        if (
            _ocr_coverage(source_geom, ocr_box_geom) < min_ocr_coverage
            and _source_coverage(source_geom, ocr_box_geom) < min_source_coverage
        ):
            continue
        text_ok = _text_compatible(source_text, str(ocr_box.get("text") or ""))
        candidates.append((text_ok, index, ocr_box))

    if any(item[0] for item in candidates):
        candidates = [item for item in candidates if item[0]]

    candidates.sort(
        key=lambda item: (
            int(item[2].get("start", 0)),
            int(item[2].get("end", 0)),
            item[1],
        )
    )
    return [item[2] for item in candidates]


def _narrow_to_source_text(
    ocr_text: str, start: int, end: int, source_text: Optional[str]
) -> Tuple[int, int]:
    """Narrow ``[start, end)`` to where ``source_text`` occurs in the window.

    A tight source PII box (e.g. a name) often aligns to a wider OCR line/block
    box whose char range ``[start, end)`` covers the whole line. Redacting that
    range masks the entire line ("FREE Two-Day Shipping ... Alexa Copeland ...").
    When the source text appears inside the matched window, narrow the span to
    just that occurrence (whitespace-flexible match, so OCR line breaks vs the
    source's single spaces still align). Falls back to the full range — the safe,
    over-redacting direction — when no clean match is found.
    """
    window = ocr_text[start:end]
    src = str(source_text or "").strip()
    if not src or not window:
        return start, end
    tokens = [t for t in re.split(r"\s+", src) if t]
    if not tokens:
        return start, end
    pattern = re.compile(r"\s+".join(re.escape(t) for t in tokens), re.IGNORECASE)
    match = pattern.search(window)
    if match is None:
        return start, end
    return start + match.start(), start + match.end()


def align_source_pii_spans(
    row: Dict[str, Any],
    *,
    min_ocr_coverage: float = 0.5,
    min_source_coverage: float = 0.6,
) -> Dict[str, Any]:
    """Create PII spans from WebPII source boxes once OCR boxes exist."""
    source_boxes = row.get("geometry", {}).get("source_pii_boxes") or []
    ocr_boxes = row.get("geometry", {}).get("ocr_boxes") or []
    ocr_text = row.get("content", {}).get("ocr_text") or ""
    if not source_boxes or not ocr_boxes or not ocr_text:
        return row

    existing = [
        span for span in row.get("detections", {}).get("pii_spans", [])
        if span.get("detector") != SOURCE_PII_ALIGNMENT_DETECTOR
    ]
    spans: List[Dict[str, Any]] = []
    for source_box in source_boxes:
        if _source_key_base(source_box) in NON_REDACTABLE_SOURCE_KEYS:
            continue
        matches = source_box_ocr_matches(
            source_box,
            ocr_boxes,
            min_ocr_coverage=min_ocr_coverage,
            min_source_coverage=min_source_coverage,
        )
        if not matches:
            continue
        start = min(int(match["start"]) for match in matches)
        end = max(int(match["end"]) for match in matches)
        if end <= start:
            continue
        start, end = _narrow_to_source_text(ocr_text, start, end, source_box.get("text"))
        if end <= start:
            continue
        # Keep only the boxes the (possibly narrowed) char range still overlaps,
        # so box_ids match what actually gets redacted; never drop to empty.
        overlapping = [
            match for match in matches
            if int(match["start"]) < end and start < int(match["end"])
        ] or matches
        box_ids = [str(match["box_id"]) for match in overlapping if match.get("box_id")]
        span = new_pii_span(
            f"source_pii_{len(spans) + 1:04d}",
            str(source_box.get("entity_type")),
            start,
            end,
            ocr_text[start:end],
            score=1.0,
            box_ids=box_ids,
            detector=SOURCE_PII_ALIGNMENT_DETECTOR,
        )
        span["source_box_id"] = source_box.get("box_id")
        span["source_key"] = source_box.get("source_key")
        span["source_text"] = source_box.get("text")
        spans.append(span)

    row["detections"]["pii_spans"] = existing + spans
    row["source_labels"]["source_aligned_pii_span_count"] = len(spans)
    return row


def ocr_row(
    row: Dict[str, Any],
    adapter,
    *,
    align_source_pii: bool = True,
    min_ocr_coverage: float = 0.5,
    min_source_coverage: float = 0.6,
) -> Dict[str, Any]:
    """Fill OCR boxes/text for one image row in place; return it."""
    if not row.get("modality", {}).get("has_image"):
        return row
    image_path = _resolve_image(row.get("content", {}).get("original_image_path"))
    if image_path is None:
        return row

    result = adapter.run(image_path)
    boxes = [
        new_ocr_box(f"box_{i:04d}", seg.text, seg.start, seg.end, seg.box, seg.confidence)
        for i, seg in enumerate(result.segments, 1)
    ]
    row["geometry"]["ocr_boxes"] = boxes
    row["content"]["ocr_text"] = result.full_text
    row["modality"]["has_ocr"] = bool(boxes)
    if align_source_pii:
        row = align_source_pii_spans(
            row,
            min_ocr_coverage=min_ocr_coverage,
            min_source_coverage=min_source_coverage,
        )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OCR over safety_v0 image rows.")
    parser.add_argument("--slug", help="Source slug for default input/output paths.")
    parser.add_argument("--input", help="Input JSONL (overrides --slug default).")
    parser.add_argument("--output", help="Output JSONL (overrides --slug default).")
    parser.add_argument("--adapter", default="paddleocr", help="OCR adapter name.")
    parser.add_argument("--lang", default="vi", help="OCR language.")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N rows.")
    parser.add_argument(
        "--no-source-pii-alignment",
        action="store_true",
        help="Skip WebPII source box -> OCR span alignment.",
    )
    parser.add_argument(
        "--min-ocr-coverage",
        type=float,
        default=0.5,
        help="Minimum fraction of an OCR box covered by a source PII box.",
    )
    parser.add_argument(
        "--min-source-coverage",
        type=float,
        default=0.6,
        help="Minimum fraction of a source PII box covered by an OCR box "
             "(catches a tight PII token nested in a wider OCR line).",
    )
    parser.add_argument(
        "--realign",
        action="store_true",
        help="Skip OCR and only re-run source-box -> OCR-span alignment over an "
             "input that already has ocr_boxes (defaults to the slug's ocr.jsonl, "
             "rewritten in place). Cheap way to re-align after a coverage change.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Append to an existing output, skipping input_ids already present. "
             "Each row is flushed as it is written so an interrupted run "
             "(OOM/crash over a long image set) converges on a plain re-run.",
    )
    args = parser.parse_args()

    # --realign reads an already-OCR'd file (default: the slug's ocr.jsonl) and
    # rewrites it; no OCR engine is loaded.
    if args.realign:
        if args.input:
            in_path = Path(args.input)
        elif args.slug:
            in_path = ocr_path(args.slug)
        else:
            parser.error("provide --input or --slug")
        out_path = Path(args.output) if args.output else in_path
        if not in_path.exists():
            print(f"Input not found: {in_path}", file=sys.stderr)
            return 1
        rows = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        total = aligned = invalid = 0
        out_lines: List[str] = []
        for row in rows:
            if args.limit is not None and total >= args.limit:
                out_lines.append(json.dumps(row, ensure_ascii=False))
                continue
            total += 1
            if not args.no_source_pii_alignment:
                row = align_source_pii_spans(
                    row,
                    min_ocr_coverage=args.min_ocr_coverage,
                    min_source_coverage=args.min_source_coverage,
                )
            aligned += row.get("source_labels", {}).get("source_aligned_pii_span_count", 0)
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid {row.get('input_id')}: {errors[0]}", file=sys.stderr)
            out_lines.append(json.dumps(row, ensure_ascii=False))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"Realign: {total} rows, {aligned} aligned spans, {invalid} invalid -> {out_path}")
        return 1 if invalid else 0

    if args.input:
        in_path = Path(args.input)
    elif args.slug:
        in_path = converted_path(args.slug)
    else:
        parser.error("provide --input or --slug")
    if args.output:
        out_path = Path(args.output)
    elif args.slug:
        out_path = ocr_path(args.slug, create=True)
    else:
        parser.error("provide --output or --slug")

    if not in_path.exists():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1

    # --resume: skip input_ids already in the output and append to it. Otherwise
    # truncate and start fresh.
    done_ids: set = set()
    if args.resume and out_path.exists():
        with open(out_path, encoding="utf-8") as existing:
            for line in existing:
                line = line.strip()
                if line:
                    done_ids.add(json.loads(line).get("input_id"))
        print(f"Resume: {len(done_ids)} rows already in {out_path}; skipping those.")

    adapter = get_ocr_adapter(args.adapter, lang=args.lang)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = ocred = invalid = skipped = 0
    open_mode = "a" if (args.resume and out_path.exists()) else "w"
    with open(in_path, encoding="utf-8") as src, open(out_path, open_mode, encoding="utf-8") as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            if args.limit is not None and total >= args.limit:
                break
            row = json.loads(line)
            if done_ids and row.get("input_id") in done_ids:
                skipped += 1
                continue
            total += 1
            had_image = row.get("modality", {}).get("has_image")
            row = ocr_row(
                row,
                adapter,
                align_source_pii=not args.no_source_pii_alignment,
                min_ocr_coverage=args.min_ocr_coverage,
                min_source_coverage=args.min_source_coverage,
            )
            if had_image and row["modality"].get("has_ocr"):
                ocred += 1
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid {row.get('input_id')}: {errors[0]}", file=sys.stderr)
                continue
            dst.write(json.dumps(row, ensure_ascii=False) + "\n")
            if args.resume:
                dst.flush()  # converge on crash: each row durable as written

    suffix = f", {skipped} already done" if skipped else ""
    print(f"OCR: {total} rows, {ocred} with text, {invalid} invalid{suffix} -> {out_path}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
