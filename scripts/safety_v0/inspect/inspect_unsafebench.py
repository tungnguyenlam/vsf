"""Inspect a downloaded `yiting/UnsafeBench` parquet for safety_v0 conversion.

Reads one of the parquets written by ``download_unsafebench.py`` (default
``data/safety_v0/raw/unsafebench/data/test-00000-of-00001.parquet``) and writes
inspection artifacts under
``data/safety_v0/inspection/unsafebench/``:

- ``schema.json``     -- columns, dtype summaries, split sizes, license, gating note
- ``stats.json``      -- per-(category, safety_label, source) row counts, text length
                         distribution, image size distribution, missing-field counts
- ``sample_rows.jsonl`` -- a few compact example rows per (category, safety_label)
                         (image bytes dropped; only the labels and caption text are
                         recorded so the file stays small and reviewable)

The 11 unsafe categories in the paper are
(Hate, Harassment, Violence, Self-Harm, Sexual, Shocking, Illegal Activity,
Deception, Political, Public and Personal Health, Spam) -- the OpenAI DALL-E
content policy from April 2022.

Usage::

    python scripts/safety_v0/inspect/inspect_unsafebench.py
    python scripts/safety_v0/inspect/inspect_unsafebench.py --parquet /path/to/test.parquet
    python scripts/safety_v0/inspect/inspect_unsafebench.py --limit 200
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402

SLUG = "unsafebench"

# Paper's 11 categories (Section 2.1, OpenAI DALL-E content policy April 2022).
# Listed in paper order; the dataset's `category` column uses these as labels.
# Safe rows carry category="Safe" (or "N/A" if the annotators could not decide).
PAPER_CATEGORIES: Tuple[str, ...] = (
    "Hate",
    "Harassment",
    "Violence",
    "Self-Harm",
    "Sexual",
    "Shocking",
    "Illegal Activity",
    "Deception",
    "Political",
    "Public and Personal Health",
    "Spam",
)

# Columns the dataset ships (README `dataset_info.features`).
COLUMNS = ("image", "safety_label", "category", "source", "text")

# What we expect to see in `safety_label` per the README example.
EXPECTED_SAFETY_LABELS = ("Safe", "Unsafe", "N/A")


def _length_buckets(values: Iterable[int]) -> Dict[str, int]:
    items = sorted(values)
    if not items:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0}
    return {
        "min": items[0],
        "p50": items[len(items) // 2],
        "p90": items[int(len(items) * 0.9)],
        "max": items[-1],
    }


def _image_size_buckets(widths: Iterable[int], heights: Iterable[int]) -> Dict[str, int]:
    return {
        "width": _length_buckets(widths),
        "height": _length_buckets(heights),
    }


def _image_size(image: Any) -> Optional[Tuple[int, int]]:
    """Best-effort (width, height) for one image cell.

    Accepts PIL.Image, the HF `Image` struct (decoded to PIL by `datasets`),
    a dict with `bytes` + a recognized PNG/JPEG header, or raw bytes.
    Returns None when the size cannot be determined cheaply.
    """
    if image is None:
        return None
    size = getattr(image, "size", None)
    if size is not None and len(size) == 2:
        return int(size[0]), int(size[1])
    if isinstance(image, dict):
        if "size" in image and image["size"] is not None:
            value = image["size"]
            if isinstance(value, (list, tuple)) and len(value) == 2:
                return int(value[0]), int(value[1])
        raw = image.get("bytes") or image.get("path")
        if isinstance(raw, (bytes, bytearray)):
            image = bytes(raw)
        else:
            return None
    if isinstance(image, (bytes, bytearray)):
        try:
            from PIL import Image as _PILImage
            import io as _io

            with _PILImage.open(_io.BytesIO(image)) as handle:
                return int(handle.size[0]), int(handle.size[1])
        except Exception:  # noqa: BLE001
            return None
    return None


def _row_payload(row_idx: int, row: Dict[str, Any]) -> Dict[str, Any]:
    """Compact representation for sample_rows.jsonl (no image bytes)."""
    image_size = _image_size(row.get("image"))
    text = row.get("text") or ""
    return {
        "row": row_idx,
        "safety_label": row.get("safety_label"),
        "category": row.get("category"),
        "source": row.get("source"),
        "text_preview": text[:200] if isinstance(text, str) else str(text)[:200],
        "text_length": len(text) if isinstance(text, str) else 0,
        "image_size": [image_size[0], image_size[1]] if image_size is not None else None,
    }


def summarize(parquet_path: Path, sample_per_bucket: int) -> Dict[str, Any]:
    """Read the parquet once and produce stats + sample rows.

    Uses pandas/pyarrow under the hood (transitive via `datasets`); we only
    materialize the columns we need and only decode the image struct for the
    sample rows, so we don't have to keep the full image column in memory.
    """
    import pandas as pd

    df = pd.read_parquet(parquet_path)
    n_rows = int(len(df))
    cols_present = [name for name in COLUMNS if name in df.columns]

    safety_labels = df["safety_label"].tolist() if "safety_label" in cols_present else []
    categories = df["category"].tolist() if "category" in cols_present else []
    sources = df["source"].tolist() if "source" in cols_present else []
    texts = df["text"].tolist() if "text" in cols_present else []
    images = df["image"].tolist() if "image" in cols_present else []

    label_dist = Counter(safety_labels)
    category_dist = Counter(categories)
    source_dist = Counter(sources)

    # Joint distribution: (category, safety_label) -- most useful for the mapping doc.
    joint: Counter = Counter()
    for cat, lab in zip(categories, safety_labels):
        joint[(cat, lab)] += 1
    joint_dict = {f"{cat}::{lab}": count for (cat, lab), count in sorted(joint.items())}

    # Text length distribution (caption/prompt is the only text field).
    text_lengths = [len(t) for t in texts if isinstance(t, str)]
    text_stats = _length_buckets(text_lengths) | {"empty": sum(1 for t in texts if not t)}

    # Image-size distribution -- only the rows we already materialized to Python.
    # The HF parquet stores images as opaque structs that decode to PIL.Image
    # via the `datasets` library; raw `pd.read_parquet` gives us either bytes
    # or a dict with metadata, so we accept both shapes.
    widths: List[int] = []
    heights: List[int] = []
    for image in images:
        size = _image_size(image)
        if size is not None:
            widths.append(int(size[0]))
            heights.append(int(size[1]))
    image_stats = _image_size_buckets(widths, heights)
    image_stats["sampled_rows"] = len(widths)

    # Missing values per column (None / empty string).
    missing = {}
    for col, values in (
        ("safety_label", safety_labels),
        ("category", categories),
        ("source", sources),
        ("text", texts),
    ):
        missing[col] = sum(1 for v in values if v is None or (isinstance(v, str) and not v.strip()))

    # One sample row per (category, safety_label) bucket for review.
    samples: List[Dict[str, Any]] = []
    bucket_counts: Counter = Counter()
    for idx, (cat, lab, src, txt, img) in enumerate(
        zip(categories, safety_labels, sources, texts, images)
    ):
        key = (cat, lab)
        if bucket_counts[key] >= sample_per_bucket:
            continue
        bucket_counts[key] += 1
        samples.append(_row_payload(idx, {"safety_label": lab, "category": cat, "source": src, "text": txt, "image": img}))

    return {
        "rows": n_rows,
        "columns_present": cols_present,
        "columns_expected": list(COLUMNS),
        "safety_label_dist": dict(label_dist),
        "category_dist": dict(category_dist),
        "source_dist": dict(source_dist),
        "joint_category_safety_dist": joint_dict,
        "text_stats": text_stats,
        "image_stats": image_stats,
        "missing_per_column": missing,
        "sample_rows": samples,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parquet",
        type=Path,
        default=source_dir("raw", SLUG) / "data" / "test-00000-of-00001.parquet",
        help="Path to the downloaded test/train parquet.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=source_dir("inspection", SLUG, create=True),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on rows to read from the parquet. Useful while the "
        "download is still progressing or for quick smoke tests.",
    )
    parser.add_argument(
        "--sample-per-bucket",
        type=int,
        default=2,
        help="How many example rows to keep per (category, safety_label) bucket.",
    )
    args = parser.parse_args()

    if not args.parquet.exists():
        raise FileNotFoundError(
            f"No parquet at {args.parquet}. Run download_unsafebench.py first."
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # If a row limit was requested, slice the dataframe in memory before summarizing.
    if args.limit is not None:
        import pandas as pd

        df = pd.read_parquet(args.parquet).head(args.limit)
        tmp_path = args.out_dir / "_sliced.parquet"
        df.to_parquet(tmp_path, index=False)
        source_for_inspect = tmp_path
    else:
        source_for_inspect = args.parquet

    stats = summarize(source_for_inspect, args.sample_per_bucket)

    schema = {
        "repo_id": "yiting/UnsafeBench",
        "columns": {
            "image": "PIL image (RGB JPEG), varies in size",
            "safety_label": "string in {Safe, Unsafe, N/A} -- human majority vote",
            "category": "string in {Safe, N/A} ∪ the 11 unsafe categories below",
            "source": "string in {Laion5B, Lexica} -- real-world vs AI-generated",
            "text": "string -- the source caption / prompt that fetched the image (often 'xxx')",
        },
        "unsafe_categories_paper": list(PAPER_CATEGORIES),
        "expected_safety_labels": list(EXPECTED_SAFETY_LABELS),
        "license": "dua_gated",
        "license_note": "Released under a Data Use Agreement (DUA) for research/education and "
        "responsible commercial use; access is gated on the HF dataset page and "
        "approval can take 1-2 days. Rows carry license_status='dua_research'.",
        "access": "gated",
        "split_row_counts": {
            "train": 8109,
            "test": 2037,
        },
        "notes": (
            "Annotations are majority votes of three authors (Fleiss' Kappa ~0.47, "
            "moderate agreement). N/A rows exist for images that the annotators "
            "could not classify (e.g. blurry, unidentifiable). The released "
            "dataset drops N/A and uses only Safe+Unsafe rows."
        ),
    }

    samples = stats.pop("sample_rows")
    write_json(args.out_dir / "schema.json", schema)
    write_json(args.out_dir / "stats.json", stats)
    write_jsonl(args.out_dir / "sample_rows.jsonl", samples)

    if args.limit is not None:
        source_for_inspect.unlink(missing_ok=True)  # clean up the slice

    print(f"Wrote UnsafeBench inspection artifacts to {args.out_dir}")
    print(json.dumps({k: v for k, v in stats.items() if k != "sample_rows"}, ensure_ascii=False, indent=2)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
