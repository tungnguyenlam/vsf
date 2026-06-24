"""Convert the bounded UIT-ViHSD sample into canonical safety_v0 rows.

ViHSD labels Vietnamese social-media comments as CLEAN / OFFENSIVE / HATE. That
taxonomy is orthogonal to our seven risk axes: a hate/offensive comment is not
inherently sexual, violent, political, or religious, and DATA_PLAN explicitly
says not to blindly map hate to violence. So this converter is deliberately
conservative about what it asserts:

- ``prompt_injection`` -> ``False`` (source_assumption): ViHSD is not a
  prompt-injection dataset, so these comments are useful Vietnamese NEGATIVES for
  the PI classifier, which is otherwise positive-heavy.
- ``pii_visible`` -> ``False`` (source_assumption): text-only rows, no image.
- ``sexual`` / ``violence`` / ``blood_gore`` / ``political`` / ``religious`` ->
  ``None`` (unknown): a hate/offensive comment *may* be any of these, but ViHSD
  does not sub-label, so we leave them for the topic weak-labeler / human review
  ("null means unknown, not false").
- ``action`` -> ``None`` (unknown): whether a hate sample is reject vs unsure is
  a review decision, not a source fact.

The original label is preserved in ``source_labels`` so a deterministic mapping
(e.g. HATE -> reject) or a teacher pass can use it later.

Usage::

    python scripts/safety_v0/convert/convert_vihsd_topic_safety.py
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import new_row, validate_row  # noqa: E402
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    format_input_id,
    get_source,
    source_dir,
)

SLUG = "vihsd_topic_safety"
LABEL_NAMES = {0: "CLEAN", 1: "OFFENSIVE", 2: "HATE"}
# Order raw split files are processed so input_ids are stable.
SPLIT_ORDER = ["train", "dev", "test"]


def build_canonical_row(index: int, split: str, record: Dict[str, Any]) -> Dict[str, Any]:
    source = get_source(SLUG)
    text = record.get("free_text") or ""
    label_id = record.get("label_id")

    row = new_row(
        format_input_id(SLUG, index),
        source.name,  # canonical uitnlp/vihsd, regardless of download mirror
        split=split,
        source_sample_id=f"{split}:{index}",
        has_text=True,
        input_text=text,
        sanitized_text=text,
    )

    labels = row["labels"]
    label_source = row["label_source"]
    # Source assumptions: not a PI/image dataset.
    labels["prompt_injection"] = False
    label_source["prompt_injection"] = "source_assumption"
    labels["pii_visible"] = False
    label_source["pii_visible"] = "source_assumption"
    # Everything else stays unknown (None): sexual, violence, blood_gore,
    # political, religious, action.

    row["source_labels"] = {
        "label_id": label_id,
        "label_name": LABEL_NAMES.get(label_id),
        "split": split,
    }
    return row


def convert_split(path: Path, split: str, start_index: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for offset, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            rows.append(build_canonical_row(start_index + offset, split, record))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    out_path = args.output or converted_path(SLUG, create=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    index = 1
    total = invalid = 0
    label_counts: Dict[str, int] = {}
    with open(out_path, "w", encoding="utf-8") as dst:
        for split in SPLIT_ORDER:
            path = args.raw_dir / f"{split}.jsonl"
            if not path.exists():
                continue
            rows = convert_split(path, split, index)
            index += len(rows)
            for row in rows:
                total += 1
                name = row["source_labels"].get("label_name")
                label_counts[name] = label_counts.get(name, 0) + 1
                errors = validate_row(row)
                if errors:
                    invalid += 1
                    print(f"  invalid {row['input_id']}: {errors[0]}", file=sys.stderr)
                    continue
                dst.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Converted {total} rows ({invalid} invalid) -> {out_path}")
    print(f"  source label distribution: {label_counts}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
