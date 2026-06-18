"""Convert cyberseceval3-visual-prompt-injection raw JSONL into `safety_v0` rows.

Source: the raw split written by
``scripts/safety_v0/download/download_cyberseceval3_visual_prompt_injection.py``.
Every row is a visual prompt-injection **attack** (the benchmark has no benign
control). The injection lives in the image, so we map it to OCR text:

- ``content.input_text``  <- ``user_input_text`` (the benign-looking user question)
- ``content.ocr_text``    <- ``image_text`` (text embedded in the image = the
  injection; empty for ~100 rows whose attack is carried by the image scene, e.g.
  figstep / query_relevant_images)

The dataset ships no image binaries, so ``modality.has_image`` is ``False``;
``has_ocr`` is set only when ``image_text`` is non-empty. The gold injection span
is recorded over the OCR text (``field="ocr_text"``) when present.

Label policy (mirrors the deepset converter; "null means unknown, not false"):

- ``prompt_injection`` -> True                              (source_gold)
- ``action``           -> "reject"                          (source_assumption)
- ``pii_visible`` / ``sexual`` / ``violence`` / ``blood_gore`` -> False
  (source_assumption: synthetic security/logic tests, no depicted PII/topic content)
- ``political`` / ``religious`` -> None (UNKNOWN)

Rich source metadata (injection_type/technique, risk_category, system_prompt,
image_description, judge_question) is preserved in ``source_labels`` for a later
topic teacher, an image-render step, or human review.

Language: the corpus is English. safety_v0 keeps English/Vietnamese
(``ALLOWED_LANGUAGES``); rows whose combined text is not an allowed language are
dropped and counted.

Usage::

    python scripts/safety_v0/convert/convert_cyberseceval3_visual_prompt_injection.py
    python scripts/safety_v0/convert/convert_cyberseceval3_visual_prompt_injection.py --limit 50

Output:
``data/safety_v0/converted/cyberseceval3_visual_prompt_injection/source_canonical.jsonl``.
No network or token required (reads the local raw JSONL).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.language import ALLOWED_LANGUAGES, is_allowed_language  # noqa: E402
from src.pipeline.Datasets.safety_v0_schema import (  # noqa: E402
    new_prompt_injection_span,
    new_row,
    validate_row,
)
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    format_input_id,
    get_source,
    source_dir,
)

SLUG = "cyberseceval3_visual_prompt_injection"
SPLIT = "test"


def cyberseceval3_labels() -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """Safety labels for one row, with provenance. Every row is an attack."""
    labels = {
        "action": "reject",
        "pii_visible": False,
        "prompt_injection": True,
        "sexual": False,
        "violence": False,
        "blood_gore": False,
        "political": None,
        "religious": None,
    }
    label_source = {
        "action": "source_assumption",
        "pii_visible": "source_assumption",
        "prompt_injection": "source_gold",
        "sexual": "source_assumption",
        "violence": "source_assumption",
        "blood_gore": "source_assumption",
        "political": None,
        "religious": None,
    }
    return labels, label_source


def build_canonical_row(index: int, record: Dict[str, Any]) -> Dict[str, Any]:
    user_text = record.get("user_input_text", "") or ""
    image_text = record.get("image_text", "") or ""
    has_ocr = bool(image_text.strip())
    labels, label_source = cyberseceval3_labels()

    row = new_row(
        format_input_id(SLUG, index),
        get_source(SLUG).name,  # canonical "facebook/cyberseceval3-visual-prompt-injection"
        split=SPLIT,
        source_sample_id=str(record.get("id", index)),
        license_status="needs_verification",
        has_text=True,
        has_ocr=has_ocr,
        input_text=user_text,
        sanitized_text=user_text,
        ocr_text=image_text,
        sanitized_ocr_text=image_text,
    )

    # Gold injection span over the OCR text when there is text to localize.
    if has_ocr:
        span = new_prompt_injection_span(
            "pi_0001",
            "visual_prompt_injection",
            0,
            len(image_text),
            image_text,
            score=1.0,
            box_ids=None,
            detector="source_gold",
        )
        span["field"] = "ocr_text"
        row["detections"]["prompt_injection_spans"] = [span]

    row["labels"] = labels
    row["label_source"] = label_source
    row["source_labels"] = {
        "id": record.get("id"),
        "injection_type": record.get("injection_type"),
        "injection_technique": list(record.get("injection_technique", []) or []),
        "risk_category": record.get("risk_category"),
        "system_prompt": record.get("system_prompt"),
        "image_description": record.get("image_description"),
        "judge_question": record.get("judge_question"),
        "has_image_text": has_ocr,
        "split": SPLIT,
    }
    return row


def load_records(raw_dir: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    path = raw_dir / f"{SPLIT}.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing raw split {path}. "
            "Run download_cyberseceval3_visual_prompt_injection.py first."
        )
    records: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if limit is not None and len(records) >= limit:
                break
    return records


def filter_by_language(
    records: List[Dict[str, Any]], *, allowed=ALLOWED_LANGUAGES, detector=None
) -> Tuple[List[Dict[str, Any]], int]:
    """Keep records whose combined user/image text is an allowed language."""
    kept = []
    for r in records:
        text = ((r.get("user_input_text") or "") + " " + (r.get("image_text") or "")).strip()
        if is_allowed_language(text, allowed=allowed, detector=detector):
            kept.append(r)
    return kept, len(records) - len(kept)


def iter_canonical_rows(records: List[Dict[str, Any]], start_index: int = 1) -> Iterator[Dict[str, Any]]:
    index = start_index
    for record in records:
        yield build_canonical_row(index, record)
        index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--languages",
        nargs="*",
        default=list(ALLOWED_LANGUAGES),
        help="Keep only rows detected as these ISO 639-1 languages.",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    out_path = args.out or converted_path(SLUG, create=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records = load_records(args.raw_dir, limit=args.limit)
    records, dropped_lang = filter_by_language(records, allowed=args.languages)
    print(f"Loaded {len(records)} rows kept ({dropped_lang} dropped by language).")

    written = invalid = 0
    with open(out_path, "w", encoding="utf-8") as handle:
        for row in iter_canonical_rows(records):
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid row {row['input_id']}: {errors[0]}", file=sys.stderr)
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1

    print(
        f"Wrote {written} rows to {out_path} "
        f"({dropped_lang} dropped by language, {invalid} invalid skipped)."
    )
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
