"""Convert the local Vietnamese prompt-injection seeds into `safety_v0` rows.

Source: the hand-authored Vietnamese seed corpora under
``data/prompt_injection/`` (general seed, app seed, mentor seed). Each line is a
labelled instruction prompt:

    {"input_id": "vi-seed-009", "text": "...", "label": 1,
     "category": "instruction_override", "source": "local_vietnamese_seed", ...}

``label`` is the gold prompt-injection flag (1 = attack, 0 = benign). These are
text-only synthetic prompts: they carry no PII, no images, and no
sensitive-topic content, so we straight-convert them (no OCR, no redaction, no
LLM verifier). The gold flag becomes the ``prompt_injection`` label and, for
attack rows, a whole-text ``prompt_injection_span`` tagged with the source
``category`` as its ``attack_type``.

Label policy (see ``prompt_injection_text_labels``):

- ``prompt_injection`` -> bool(label)            (source_gold)
- ``action``           -> "reject" if attack else "safe"  (source_assumption)
- every other risk axis (``pii_visible``, ``sexual``, ``violence``,
  ``blood_gore``, ``political``, ``religious``) -> False   (asserted absent)

These are content axes judged from the text, so for these ordinary text-only
prompts they are asserted ``False`` (``source_assumption``), not left ``None``.
``None`` is reserved for axes we genuinely cannot judge (e.g. visual risks on an
image source before inspection); unknown is never written as a negative, but
here the content is known.

Usage::

    python scripts/safety_v0/convert/convert_local_vi_prompt_injection.py --limit 100
    python scripts/safety_v0/convert/convert_local_vi_prompt_injection.py --sources vietnamese_seed

Output: ``data/safety_v0/converted/local_vi_prompt_injection/source_canonical.jsonl``.
No network or token required (the seeds are local files).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import (  # noqa: E402
    new_prompt_injection_span,
    new_row,
    validate_row,
)
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    format_input_id,
)

SLUG = "local_vi_prompt_injection"

# Sub-source files under data/prompt_injection/. Keys are the --sources names.
SEED_DIR = PROJECT_ROOT / "data" / "prompt_injection"
DEFAULT_SUB_SOURCES = ["vietnamese_seed", "vietnamese_app_seed", "vietnamese_mentor_seed"]
SUB_SOURCE_FILES = {
    "vietnamese_seed": SEED_DIR / "vietnamese_seed.jsonl",
    "vietnamese_app_seed": SEED_DIR / "vietnamese_app_seed.jsonl",
    "vietnamese_mentor_seed": SEED_DIR / "vietnamese_mentor_seed.jsonl",
}


def prompt_injection_text_labels(is_attack: bool) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """Safety labels for one prompt-injection seed row, with provenance.

    The gold ``label`` drives ``prompt_injection`` (and thus ``action``).
    Visual labels stay ``None`` (no image); PII/topic labels are asserted absent
    because these are hand-authored instruction prompts with no personal data or
    sensitive-topic content.
    """
    labels = {
        "action": "reject" if is_attack else "safe",
        "pii_visible": False,
        "prompt_injection": bool(is_attack),
        "sexual": False,
        "violence": False,
        "blood_gore": False,
        "political": False,
        "religious": False,
    }
    label_source = {
        "action": "source_assumption",
        "pii_visible": "source_assumption",
        "prompt_injection": "source_gold",
        "sexual": "source_assumption",
        "violence": "source_assumption",
        "blood_gore": "source_assumption",
        "political": "source_assumption",
        "religious": "source_assumption",
    }
    return labels, label_source


def build_canonical_row(index: int, sub_source: str, record: Dict[str, Any]) -> Dict[str, Any]:
    text = record.get("text", "") or ""
    is_attack = int(record.get("label", 0)) == 1
    category = record.get("category") or ("prompt_injection" if is_attack else "benign")
    labels, label_source = prompt_injection_text_labels(is_attack)

    row = new_row(
        format_input_id(SLUG, index),
        record.get("source", sub_source),
        source_sample_id=record.get("input_id"),
        license_status="needs_verification",
        has_text=True,
        input_text=text,
        # No PII to remove: sanitized text equals the input text.
        sanitized_text=text,
    )
    if is_attack and text:
        row["detections"]["prompt_injection_spans"] = [
            new_prompt_injection_span(
                "pi_0001",
                category,
                0,
                len(text),
                text,
                score=1.0,
                box_ids=None,
                detector="source_gold",
            )
        ]
    row["labels"] = labels
    row["label_source"] = label_source
    row["source_labels"] = {
        "label": int(record.get("label", 0)),
        "category": record.get("category"),
        "expected_action": record.get("expected_action"),
        "language": record.get("language"),
    }
    return row


def load_records(sub_source: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    path = SUB_SOURCE_FILES.get(sub_source)
    if path is None:
        raise ValueError(
            f"Unknown sub-source {sub_source!r}. Available: {sorted(SUB_SOURCE_FILES)}"
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


def iter_canonical_rows(
    sub_source: str, records: List[Dict[str, Any]], start_index: int = 1
) -> Iterator[Dict[str, Any]]:
    index = start_index
    for record in records:
        yield build_canonical_row(index, sub_source, record)
        index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="*", default=DEFAULT_SUB_SOURCES)
    parser.add_argument("--limit", type=int, default=None, help="Rows per sub-source.")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    out_path = args.out or converted_path(SLUG, create=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    invalid = 0
    index = 1
    with open(out_path, "w", encoding="utf-8") as handle:
        for sub_source in args.sources:
            records = load_records(sub_source, limit=args.limit)
            print(f"Loading {sub_source} ({len(records)} rows)...")
            for row in iter_canonical_rows(sub_source, records, start_index=index):
                errors = validate_row(row)
                if errors:
                    invalid += 1
                    print(f"  invalid row {row['input_id']}: {errors[0]}", file=sys.stderr)
                    continue
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
                index += 1

    print(f"Wrote {written} rows to {out_path} ({invalid} invalid skipped).")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
