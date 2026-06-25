"""Convert `yiting/UnsafeBench` parquet rows into canonical safety_v0 rows.

UnsafeBench is a single-image classifier benchmark: every row is one image with
a human majority-vote ``safety_label`` (Safe / Unsafe / N/A), the unsafe
``category`` the image was sampled for (one of the 11 OpenAI DALL-E
content-policy categories), the image ``source`` (Laion5B real-world vs Lexica
AI-generated), and the retrieval ``text`` (caption/prompt that fetched the
image -- audit metadata only, NOT a reliable instruction).

This converter emits **one canonical row per image**. The mapping mirrors
``docs/datasets/unsafebench.md`` exactly:

- ``safety_label`` drives the row. ``category`` only refines the visual axes
  for rows that are actually ``Unsafe`` -- a ``Sexual``-bucket image labeled
  ``Safe`` is a safe row with every axis ``false``.
- Safe rows: ``action=safe`` and every boolean axis ``false`` (visual axes
  ``source_gold``; ``pii_visible`` / ``prompt_injection`` ``source_assumption``
  -- single-image classifier rows with no OCR text in the source).
- N/A rows: every label ``null`` (annotators could not decide -> review).
- Unsafe rows: ``action`` and the visual axes come from the per-category table;
  ``pii_visible`` / ``prompt_injection`` stay ``null`` until the OCR/PII and
  prompt-injection passes actually fire.

It does not decode image bytes; ``content.original_image_path`` points at where
``extract_unsafebench_images.py`` will write the JPEG for each ``input_id``.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

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

SLUG = "unsafebench"
LICENSE_STATUS = "dua_research"

# Columns the parquet ships; we only need the label/metadata ones (no image bytes).
METADATA_COLUMNS = ("safety_label", "category", "source", "text")

# Canonical safety_label values (case-insensitive match below).
SAFE = "safe"
UNSAFE = "unsafe"
NA = "n/a"

# Per-(unsafe) category -> visual axes, mirroring docs/datasets/unsafebench.md.
# Keys are normalized (lowercase). Only consulted for Unsafe rows. Each entry is
# (action, {axis: value}). Axes absent from the dict are left null (unknown).
# pii_visible / prompt_injection are handled separately (always null here).
_T, _F = True, False
CATEGORY_MAP: Dict[str, Tuple[Optional[str], Dict[str, Optional[bool]]]] = {
    "hate": ("reject", {}),
    "harassment": ("reject", {}),
    "violence": (
        "reject",
        {"sexual": _F, "violence": _T, "political": _F, "religious": _F},
        # blood_gore left null: UnsafeBench does not sub-label it (same gap as VLGuard).
    ),
    "self-harm": ("reject", {}),
    "sexual": (
        "reject",
        {"sexual": _T, "violence": _F, "blood_gore": _F, "political": _F, "religious": _F},
    ),
    "shocking": ("reject", {}),
    "illegal activity": ("reject", {}),
    "deception": ("reject", {}),
    # action deferred to review (policy-debatable) but the topic axis is asserted.
    "political": (
        None,
        {"sexual": _F, "violence": _F, "blood_gore": _F, "political": _T, "religious": _F},
    ),
    "public and personal health": (
        None,
        {"sexual": _F, "violence": _F, "blood_gore": _F, "political": _F, "religious": _F},
    ),
    "spam": (
        None,
        {"sexual": _F, "violence": _F, "blood_gore": _F, "political": _F, "religious": _F},
    ),
}

ALL_AXES = ("sexual", "violence", "blood_gore", "political", "religious")


def _normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def _project_relative(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def map_labels(
    safety_label: str, category: str
) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """Return (labels, label_source) for one row.

    See module docstring / docs/datasets/unsafebench.md for the contract.
    """
    norm_label = _normalize(safety_label)
    norm_cat = _normalize(category)

    if norm_label == SAFE:
        # Safe image: every axis false. Visual axes are source_gold; the two
        # text-derived axes are source_assumption (no OCR text in the source).
        labels = {"action": "safe", "pii_visible": False, "prompt_injection": False}
        label_source = {
            "action": "source_gold",
            "pii_visible": "source_assumption",
            "prompt_injection": "source_assumption",
        }
        for axis in ALL_AXES:
            labels[axis] = False
            label_source[axis] = "source_gold"
        return labels, label_source

    if norm_label != UNSAFE:
        # N/A (or any unexpected value): annotators could not decide -> all unknown.
        labels = {field: None for field in ("action", "pii_visible", "prompt_injection", *ALL_AXES)}
        label_source = {field: None for field in labels}
        return labels, label_source

    # Unsafe: drive the visual axes from the category; text-derived axes stay
    # null until the OCR/PII + prompt-injection passes fire.
    action, axis_values = CATEGORY_MAP.get(norm_cat, (None, {}))
    labels: Dict[str, Any] = {"action": action, "pii_visible": None, "prompt_injection": None}
    label_source: Dict[str, Optional[str]] = {
        "action": "source_gold" if action is not None else None,
        "pii_visible": None,
        "prompt_injection": None,
    }
    for axis in ALL_AXES:
        if axis in axis_values:
            labels[axis] = axis_values[axis]
            label_source[axis] = "source_gold"
        else:
            labels[axis] = None
            label_source[axis] = None
    return labels, label_source


def build_canonical_row(
    index: int,
    split: str,
    row_idx: int,
    record: Dict[str, Any],
    *,
    images_root: Path,
) -> Dict[str, Any]:
    input_id = format_input_id(SLUG, index)
    labels, label_source = map_labels(record.get("safety_label"), record.get("category"))

    image_path = images_root / f"{input_id}.jpg"
    text = record.get("text") or ""

    row = new_row(
        input_id,
        get_source(SLUG).name,
        split=split,
        source_sample_id=f"{split}:{row_idx}",
        license_status=LICENSE_STATUS,
        has_image=True,
        has_text=False,  # `text` is retrieval caption / audit metadata, not content
        has_ocr=False,
        original_image_path=_project_relative(image_path),
        input_text="",
        sanitized_text="",
    )
    row["labels"] = labels
    row["label_source"] = label_source
    row["source_labels"] = {
        "safety_label": record.get("safety_label"),
        "category": record.get("category"),
        "source": record.get("source"),
        "text": text,  # audit only; never used as a PII / prompt-injection source
        "parquet_row": row_idx,
        "split": split,
    }
    return row


def iter_canonical_rows(
    parquet_path: Path,
    *,
    split: str,
    images_root: Path,
    limit: Optional[int] = None,
) -> Iterator[Dict[str, Any]]:
    import pandas as pd

    columns = [c for c in METADATA_COLUMNS]
    df = pd.read_parquet(parquet_path, columns=columns)
    if limit is not None:
        df = df.head(limit)
    index = 1
    for row_idx, record in enumerate(df.to_dict("records")):
        yield build_canonical_row(
            index, split, row_idx, record, images_root=images_root
        )
        index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parquet",
        type=Path,
        default=source_dir("raw", SLUG) / "data" / "test-00000-of-00001.parquet",
        help="Downloaded UnsafeBench parquet (test or train).",
    )
    parser.add_argument("--split", default="test", choices=("train", "test"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--images-root",
        type=Path,
        default=source_dir("raw", SLUG) / "images",
        help="Root where extract_unsafebench_images.py will write <input_id>.jpg.",
    )
    args = parser.parse_args()

    if not args.parquet.exists():
        raise FileNotFoundError(
            f"No parquet at {args.parquet}. Run download_unsafebench.py first."
        )

    out_path = args.output or converted_path(SLUG, create=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = invalid = 0
    with open(out_path, "w", encoding="utf-8") as handle:
        for row in iter_canonical_rows(
            args.parquet,
            split=args.split,
            images_root=args.images_root,
            limit=args.limit,
        ):
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid row {row['input_id']}: {errors[0]}", file=sys.stderr)
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1

    print(f"Converted {written} UnsafeBench rows ({invalid} invalid) -> {out_path}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
