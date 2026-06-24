"""PII + redaction stage for image rows.

Runs the existing Vietnamese PII pipeline on each row's ``ocr_text``, maps the
detected spans back to OCR boxes, blurs/fills those regions in the image, and
records ``detections.pii_spans`` + ``detections.redaction_metadata`` plus the
sanitized OCR text and the redacted image path.

This stage is deterministic preprocessing only: it fills ``content`` /
``geometry`` / ``detections`` but NEVER sets ``labels`` (those stay unknown for
the weak-label / router / human stages — "null means unknown").

Default paths from the source registry::

    python scripts/safety_v0/run_pii_redaction.py --slug webpii
    # data/safety_v0/ocr/webpii/ocr.jsonl
    #   -> data/safety_v0/redacted/webpii/redacted.jsonl  (+ images/)

The PII pipeline (``--pipeline``) and redaction method (``--method``) are config
flips. Override paths with ``--input`` / ``--output`` / ``--images-dir``.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from presidio_anonymizer import AnonymizerEngine  # noqa: E402

from src.pipeline.Datasets.safety_v0_schema import (  # noqa: E402
    new_pii_span,
    validate_row,
)
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    ocr_path,
    redacted_images_dir,
    redacted_path,
)
from src.pipeline.Image.redaction import recompute_redactions  # noqa: E402
from src.pipeline.Pipelines import get_pipeline  # noqa: E402


def _dedupe(results):
    best = {}
    for r in results:
        key = (r.start, r.end)
        cur = best.get(key)
        if cur is None or r.score > cur.score:
            best[key] = r
    return sorted(best.values(), key=lambda r: (r.start, r.end))


def _sanitize_from_spans(text: str, spans: List[Dict[str, Any]]) -> str:
    out: List[str] = []
    cursor = 0
    for span in sorted(spans, key=lambda s: (int(s["start"]), int(s["end"]))):
        start, end = int(span["start"]), int(span["end"])
        if start < cursor or end <= start or start < 0 or end > len(text):
            continue
        out.append(text[cursor:start])
        out.append(f"<{span['entity_type']}>")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _resolve_image(path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p if p.exists() else None


def redact_row(
    row: Dict[str, Any],
    pipeline,
    anonymizer: AnonymizerEngine,
    *,
    images_dir: Path,
    method: str = "blur",
    padding: float = 3.0,
) -> Dict[str, Any]:
    """Detect PII on OCR text, redact image regions, fill detections in place."""
    if not row.get("modality", {}).get("has_ocr"):
        return row
    ocr_text = row.get("content", {}).get("ocr_text") or ""
    if not ocr_text.strip():
        return row

    results = _dedupe(pipeline.predict(ocr_text))
    existing_spans = list(row.get("detections", {}).get("pii_spans") or [])
    if not results and not existing_spans:
        return row

    new_spans = [
        new_pii_span(f"pii_{i:04d}", r.entity_type, r.start, r.end, ocr_text[r.start:r.end],
                     round(float(r.score), 4), [], detector="presidio")
        for i, r in enumerate(results, 1)
    ]
    combined_spans = existing_spans + new_spans
    row["detections"]["pii_spans"] = combined_spans

    # Shared core: map every span -> OCR boxes, build redaction metadata, render.
    src_image = _resolve_image(row["content"].get("original_image_path"))
    images_dir.mkdir(parents=True, exist_ok=True)
    dst = images_dir / f"{row['input_id']}_redacted.png"
    result = recompute_redactions(row, src_image=src_image, dst_path=dst,
                                  method=method, padding=padding)
    row["detections"]["redaction_metadata"] = result["redaction_metadata"]

    if existing_spans:
        row["content"]["sanitized_ocr_text"] = _sanitize_from_spans(ocr_text, combined_spans)
    else:
        row["content"]["sanitized_ocr_text"] = anonymizer.anonymize(
            text=ocr_text, analyzer_results=results
        ).text

    if src_image is not None:
        try:
            rel = dst.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            rel = str(dst)
        row["content"]["redacted_image_path"] = rel
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="PII detection + image redaction over OCR rows.")
    parser.add_argument("--slug", help="Source slug for default input/output paths.")
    parser.add_argument("--input", help="Input JSONL (overrides --slug default).")
    parser.add_argument("--output", help="Output JSONL (overrides --slug default).")
    parser.add_argument("--images-dir", help="Where to write redacted images.")
    parser.add_argument("--pipeline", default="regex_recall", help="PII pipeline name.")
    parser.add_argument("--method", default="blur", choices=("blur", "fill"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.input:
        in_path = Path(args.input)
    elif args.slug:
        in_path = ocr_path(args.slug)
    else:
        parser.error("provide --input or --slug")
    if args.output:
        out_path = Path(args.output)
    elif args.slug:
        out_path = redacted_path(args.slug, create=True)
    else:
        parser.error("provide --output or --slug")
    if args.images_dir:
        images_dir = Path(args.images_dir)
    elif args.slug:
        images_dir = redacted_images_dir(args.slug, create=True)
    else:
        images_dir = out_path.parent / "images"

    if not in_path.exists():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1

    pipeline = get_pipeline(args.pipeline, prediction_log_path=None)
    anonymizer = AnonymizerEngine()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = redacted = invalid = 0
    with open(in_path, encoding="utf-8") as src, open(out_path, "w", encoding="utf-8") as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            if args.limit is not None and total >= args.limit:
                break
            total += 1
            row = json.loads(line)
            row = redact_row(row, pipeline, anonymizer, images_dir=images_dir, method=args.method)
            if row["detections"].get("redaction_metadata"):
                redacted += 1
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid {row.get('input_id')}: {errors[0]}", file=sys.stderr)
                continue
            dst.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Redaction: {total} rows, {redacted} with redactions, {invalid} invalid -> {out_path}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
