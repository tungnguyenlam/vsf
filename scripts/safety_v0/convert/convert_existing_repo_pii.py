"""Convert the existing repo PII datasets into canonical `safety_v0` rows.

Source: the project's existing Vietnamese PII datasets (``pii_masking_95k`` and
``hoangha_vie_pii``), reached through the existing dataset registry so each
dataset's own ``label_to_presidio`` mapping is reused.

These are PII-only text corpora: they contain no prompt injection and no
sensitive-topic content, so we straight-convert them (no LLM verifier / weak
review pass). The gold PII spans become ``detections.pii_spans``, the text is
anonymized deterministically from those gold spans, and the safety labels are
filled from an explicit PII-only policy (see ``pii_only_text_labels``):

- ``pii_visible`` -> False  (gold PII is removed in ``sanitized_text``)
- every other risk axis (``prompt_injection``, ``sexual``, ``violence``,
  ``blood_gore``, ``political``, ``religious``) -> False  (asserted absent: the
  corpus is ordinary Vietnamese PII text with no sensitive content)
- ``action``      -> "safe"

These are content axes judged from the text itself, so for an ordinary
text-only row they are asserted ``False`` (``source_assumption``), not left
``None``. ``None`` is reserved for axes we genuinely cannot judge (e.g. visual
risks on an *image* source before the image is inspected); the DATA_PLAN rule is
that unknown is never written as a negative, but here the content is known.

Usage::

    python scripts/safety_v0/convert/convert_existing_repo_pii.py --limit 200
    python scripts/safety_v0/convert/convert_existing_repo_pii.py --sources pii_masking_95k

Output: ``data/safety_v0/converted/existing_repo_pii/source_canonical.jsonl``.
Requires HF_TOKEN for the gated source datasets when run on real data.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import (  # noqa: E402
    new_pii_span,
    new_row,
    validate_row,
)
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    format_input_id,
)

SLUG = "existing_repo_pii"
DEFAULT_SUB_DATASETS = ["pii_masking_95k", "hoangha_vie_pii"]


def map_pii_spans(
    source_text: str,
    privacy_mask: Iterable[Dict[str, Any]],
    label_to_presidio: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Map gold source spans to canonical ``pii_spans`` (drop unmapped labels).

    Span text is sliced from ``source_text`` so offsets stay authoritative.
    Spans whose label is not in the dataset mapping, or whose offsets are out of
    range, are dropped.
    """
    spans: List[Dict[str, Any]] = []
    for raw in privacy_mask or []:
        label = raw.get("label")
        entity_type = label_to_presidio.get(label)
        if entity_type is None:
            continue
        start, end = raw.get("start"), raw.get("end")
        if start is None or end is None or start < 0 or end > len(source_text) or start >= end:
            continue
        span_id = f"pii_{len(spans) + 1:04d}"
        spans.append(
            new_pii_span(
                span_id,
                entity_type,
                start,
                end,
                source_text[start:end],
                score=1.0,
                box_ids=None,
                detector="source_gold",
            )
        )
    return spans


def anonymize(source_text: str, pii_spans: List[Dict[str, Any]]) -> str:
    """Replace each PII span with ``<ENTITY_TYPE>``; overlapping spans are skipped.

    This is deterministic anonymization from gold spans, not a detector pass.
    """
    ordered = sorted(pii_spans, key=lambda s: (s["start"], s["end"]))
    out: List[str] = []
    cursor = 0
    for span in ordered:
        if span["start"] < cursor:  # overlap with an already-emitted span
            continue
        out.append(source_text[cursor : span["start"]])
        out.append(f"<{span['entity_type']}>")
        cursor = span["end"]
    out.append(source_text[cursor:])
    return "".join(out)


def pii_only_text_labels() -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """Safety labels for a PII-only text row, with provenance.

    Visual labels remain ``None`` (no image to judge); the rest are known from
    the dataset's nature and the user's assertion that it carries no prompt
    injection or sensitive-topic content.
    """
    labels = {
        "action": "safe",
        "pii_visible": False,
        "prompt_injection": False,
        "sexual": False,
        "violence": False,
        "blood_gore": False,
        "political": False,
        "religious": False,
    }
    label_source = {
        "action": "source_assumption",
        "pii_visible": "source_gold",
        "prompt_injection": "source_assumption",
        "sexual": "source_assumption",
        "violence": "source_assumption",
        "blood_gore": "source_assumption",
        "political": "source_assumption",
        "religious": "source_assumption",
    }
    return labels, label_source


def build_canonical_row(
    index: int,
    dataset_name: str,
    split: str,
    source_sample_id: Optional[str],
    source_text: str,
    privacy_mask: Iterable[Dict[str, Any]],
    label_to_presidio: Dict[str, str],
) -> Dict[str, Any]:
    pii_spans = map_pii_spans(source_text, privacy_mask, label_to_presidio)
    sanitized = anonymize(source_text, pii_spans)
    labels, label_source = pii_only_text_labels()

    row = new_row(
        format_input_id(SLUG, index),
        dataset_name,
        split=split,
        source_sample_id=source_sample_id,
        license_status="needs_verification",
        has_text=True,
        input_text=source_text,
        sanitized_text=sanitized,
    )
    row["detections"]["pii_spans"] = pii_spans
    row["labels"] = labels
    row["label_source"] = label_source
    row["source_labels"] = {
        "gold_span_count": len(list(privacy_mask or [])),
        "mapped_pii_count": len(pii_spans),
    }
    return row


def iter_canonical_rows(
    df,
    dataset_name: str,
    label_to_presidio: Dict[str, str],
    start_index: int = 1,
) -> Iterator[Dict[str, Any]]:
    """Yield canonical rows for a loaded dataframe (``source_text`` + ``privacy_mask``)."""
    index = start_index
    for record in df.to_dict("records"):
        yield build_canonical_row(
            index,
            dataset_name,
            split=record.get("split", "train"),
            source_sample_id=record.get("input_id"),
            source_text=record.get("source_text", "") or "",
            privacy_mask=record.get("privacy_mask", []) or [],
            label_to_presidio=label_to_presidio,
        )
        index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", nargs="*", default=DEFAULT_SUB_DATASETS)
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int, default=None, help="Rows per source.")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    from src.pipeline.Datasets import get_dataset

    out_path = args.out or converted_path(SLUG, create=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    invalid = 0
    index = 1
    with open(out_path, "w", encoding="utf-8") as handle:
        for name in args.sources:
            dataset = get_dataset(name)
            print(f"Loading {name} (split={args.split}, limit={args.limit})...")
            df = dataset.load(split=args.split, limit=args.limit)
            for row in iter_canonical_rows(df, name, dataset.label_to_presidio, start_index=index):
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
