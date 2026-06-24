"""Convert `deepset/prompt-injections` raw JSONL into `safety_v0` rows.

Source: the raw splits written by
``scripts/safety_v0/download/download_deepset_prompt_injections.py``. Each record
is ``{"text": "...", "label": 0|1}`` where ``label`` is the gold
prompt-injection flag (1 = attack, 0 = benign). Content is English + German;
there are no images and no PII/topic gold (see
``docs/datasets/deepset_prompt_injections.md``).

Label policy (see ``deepset_text_labels``):

- ``prompt_injection`` -> bool(label)                       (source_gold)
- ``action``           -> "reject" if attack else "safe"    (source_assumption)
- ``pii_visible`` / ``sexual`` / ``violence`` / ``blood_gore`` -> False
  (source_assumption: short text prompts, no images, no depicted content)
- ``political`` / ``religious`` -> None (UNKNOWN)

The topic axes are left ``None`` on purpose: deepset gives no topic gold and the
corpus visibly contains political/religious prompts (e.g. party/electability and
religion questions), so asserting ``False`` would invent a wrong negative.
"null means unknown, not false" (DATA_PLAN.md).

Language filter: the corpus is English + German with no Vietnamese, but
safety_v0 keeps only English/Vietnamese (``ALLOWED_LANGUAGES``). Rows whose text
is not detected as English/Vietnamese are dropped at conversion via
``src.pipeline.Datasets.language``; the number dropped is reported per split.

The source train/test split is preserved into ``source.split`` so the final
build can keep deepset's own split boundary.

Usage::

    python scripts/safety_v0/convert/convert_deepset_prompt_injections.py
    python scripts/safety_v0/convert/convert_deepset_prompt_injections.py --limit 50

Output: ``data/safety_v0/converted/deepset_prompt_injections/source_canonical.jsonl``.
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
    source_dir,
)

SLUG = "deepset_prompt_injections"
SOURCE_NAME = "deepset/prompt-injections"
DEFAULT_SPLITS = ["train", "test"]


def deepset_text_labels(is_attack: bool) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """Safety labels for one deepset row, with provenance.

    Only ``prompt_injection`` is gold. Visual/PII axes are asserted absent
    (text prompts, no images); ``political``/``religious`` stay ``None`` because
    deepset provides no topic gold and the corpus contains topic prompts.
    """
    labels = {
        "action": "reject" if is_attack else "safe",
        "pii_visible": False,
        "prompt_injection": bool(is_attack),
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


def build_canonical_row(index: int, split: str, record: Dict[str, Any]) -> Dict[str, Any]:
    text = record.get("text", "") or ""
    is_attack = int(record.get("label", 0)) == 1
    labels, label_source = deepset_text_labels(is_attack)

    row = new_row(
        format_input_id(SLUG, index),
        SOURCE_NAME,
        split=split,
        source_sample_id=f"{split}:{index}",
        license_status="needs_verification",
        has_text=True,
        input_text=text,
        # No PII removal at convert time: sanitized text equals the input text.
        sanitized_text=text,
    )
    if is_attack and text:
        row["detections"]["prompt_injection_spans"] = [
            new_prompt_injection_span(
                "pi_0001",
                "prompt_injection",  # deepset carries no attack sub-type
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
    row["source_labels"] = {"label": int(record.get("label", 0)), "split": split}
    return row


def load_records(raw_dir: Path, split: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    path = raw_dir / f"{split}.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing raw split {path}. Run download_deepset_prompt_injections.py first."
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
    """Keep only records whose ``text`` is an allowed language; return (kept, dropped)."""
    kept = [
        r for r in records
        if is_allowed_language(r.get("text", "") or "", allowed=allowed, detector=detector)
    ]
    return kept, len(records) - len(kept)


def iter_canonical_rows(
    split: str, records: List[Dict[str, Any]], start_index: int = 1
) -> Iterator[Dict[str, Any]]:
    index = start_index
    for record in records:
        yield build_canonical_row(index, split, record)
        index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--splits", nargs="*", default=DEFAULT_SPLITS)
    parser.add_argument("--limit", type=int, default=None, help="Rows per split.")
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

    written = 0
    invalid = 0
    dropped_lang = 0
    index = 1
    with open(out_path, "w", encoding="utf-8") as handle:
        for split in args.splits:
            records = load_records(args.raw_dir, split, limit=args.limit)
            records, dropped = filter_by_language(records, allowed=args.languages)
            dropped_lang += dropped
            print(f"Loading {split} ({len(records)} rows kept, {dropped} dropped by language)...")
            for row in iter_canonical_rows(split, records, start_index=index):
                errors = validate_row(row)
                if errors:
                    invalid += 1
                    print(f"  invalid row {row['input_id']}: {errors[0]}", file=sys.stderr)
                    continue
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
                index += 1

    print(
        f"Wrote {written} rows to {out_path} "
        f"({dropped_lang} dropped by language, {invalid} invalid skipped)."
    )
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
