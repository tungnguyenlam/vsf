"""Extract a bounded, diverse slice of MM-SafetyBench images for OCR review.

MM-SafetyBench stores images as PNG bytes embedded in per-category Parquet files
(``TYPO`` / ``SD`` / ``SD_TYPO``), not in a central zip, so the VLGuard ranged-
zip trick does not apply. The image splits are moderate-sized (``TYPO`` ~0.6-3.8
MB each, ``SD``/``SD_TYPO`` ~6-25 MB each); this script reads only the parquets
for the chosen variant, extracts a deterministic diverse slice (round-robin
across the 13 categories), and writes:

- the PNG files under ``data/safety_v0/raw/mm_safetybench/images/<Category>/<VARIANT>/<id>.png``
- ``data/safety_v0/converted/mm_safetybench/review_slice.jsonl``: image-bearing
  canonical rows whose ``input_text`` is the (rewritten) image-split question and
  whose labels come from :func:`category_labels` -- identical to the text-only
  converter so the slice and the main convert agree.

The harmful keyword is rendered as typography in ``TYPO``/``SD_TYPO`` images, so
running OCR on the slice recovers it; ``SD`` images carry little legible text.
Default variant is ``TYPO`` (smallest parquets, cleanest OCR keyword).

Usage:

    python scripts/safety_v0/download/extract_mm_safetybench_images.py            # 26 TYPO images
    python scripts/safety_v0/download/extract_mm_safetybench_images.py --limit 39
    python scripts/safety_v0/download/extract_mm_safetybench_images.py --variant SD_TYPO
"""

import argparse
import io
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Reuse the converter's label mapping so slice rows and the text-only convert
# agree exactly (single source of truth lives in the converter).
CONVERT_DIR = PROJECT_ROOT / "scripts" / "safety_v0" / "convert"
if str(CONVERT_DIR) not in sys.path:
    sys.path.insert(0, str(CONVERT_DIR))

import pandas as pd  # noqa: E402

from convert_mm_safetybench import CATEGORIES, LICENSE_STATUS, category_labels  # noqa: E402

from src.pipeline.Datasets.safety_v0_schema import new_row, validate_row  # noqa: E402
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    DATASET_VERSION,
    converted_path,
    get_source,
    source_dir,
)
from src.pipeline.Utils import load_env, load_hf_token  # noqa: E402
from huggingface_hub import hf_hub_download  # noqa: E402

REPO_ID = "PKU-Alignment/MM-SafetyBench"
SLUG = "mm_safetybench"
IMAGE_VARIANTS = ("TYPO", "SD_TYPO", "SD")


def _variant_parquet(raw_dir: Path, category: str, variant: str, token: Optional[str]) -> Path:
    """Return the local variant parquet, downloading it on demand if absent."""
    local = raw_dir / "data" / category / f"{variant}.parquet"
    if local.exists():
        return local
    cached = Path(
        hf_hub_download(
            REPO_ID,
            filename=f"data/{category}/{variant}.parquet",
            repo_type="dataset",
            token=token,
        )
    )
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(cached.read_bytes())
    return local


def _image_bytes(value: Any) -> Optional[bytes]:
    """HF image cell -> PNG bytes. Handles raw bytes or a {'bytes': ...} dict."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, dict):
        b = value.get("bytes")
        return bytes(b) if b is not None else None
    return None


def _project_relative(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def select_and_extract(
    raw_dir: Path,
    images_root: Path,
    variant: str,
    limit: int,
    token: Optional[str],
) -> List[Dict[str, Any]]:
    """Round-robin a diverse slice across categories, extract images, build rows.

    Returns the list of canonical image rows (one per extracted image).
    """
    # Per-category dataframes for the chosen variant (read whole; TYPO is small).
    frames: "OrderedDict[str, pd.DataFrame]" = OrderedDict()
    for category in CATEGORIES:
        parquet = _variant_parquet(raw_dir, category, variant, token)
        frames[category] = pd.read_parquet(parquet)

    rows: List[Dict[str, Any]] = []
    cursors = {c: 0 for c in CATEGORIES}
    index = 1
    seen = 0
    while seen < limit:
        progressed = False
        for category in CATEGORIES:
            if seen >= limit:
                break
            df = frames[category]
            i = cursors[category]
            if i >= len(df):
                continue
            cursors[category] = i + 1
            record = df.iloc[i]
            data = _image_bytes(record.get("image"))
            if data is None:
                continue
            sample_id = record.get("id")
            question = str(record.get("question") or "")
            out_path = images_root / category / variant / f"{sample_id}.png"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)

            labels, label_source = category_labels(category)
            input_id = f"{DATASET_VERSION}_{SLUG}_{variant.lower()}_{index:06d}"
            row = new_row(
                input_id,
                get_source(SLUG).name,
                split="test",
                source_sample_id=f"{category}:{sample_id}:{variant}",
                license_status=LICENSE_STATUS,
                has_image=True,
                has_text=bool(question.strip()),
                has_ocr=False,
                original_image_path=_project_relative(out_path),
                input_text=question,
                sanitized_text=question,
            )
            row["labels"] = labels
            row["label_source"] = label_source
            row["source_labels"] = {
                "category": category,
                "id": sample_id,
                "split": variant,
                "image_question": question,
            }
            rows.append(row)
            index += 1
            seen += 1
            progressed = True
        if not progressed:
            break
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument(
        "--images-root",
        type=Path,
        default=source_dir("raw", SLUG) / "images",
    )
    parser.add_argument("--limit", type=int, default=26, help="Total images across categories.")
    parser.add_argument(
        "--variant",
        default="TYPO",
        choices=list(IMAGE_VARIANTS),
        help="Which image split to extract (TYPO is smallest / cleanest OCR).",
    )
    parser.add_argument(
        "--review-slice",
        type=Path,
        default=converted_path(SLUG).parent / "review_slice.jsonl",
        help="Where to write image-bearing canonical rows for the slice.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional JSON manifest (default under images-root).",
    )
    args = parser.parse_args()

    load_env()
    token = load_hf_token()

    images_root: Path = args.images_root
    images_root.mkdir(parents=True, exist_ok=True)

    rows = select_and_extract(args.raw_dir, images_root, args.variant, args.limit, token)

    invalid = 0
    args.review_slice.parent.mkdir(parents=True, exist_ok=True)
    with open(args.review_slice, "w", encoding="utf-8") as handle:
        for row in rows:
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid {row['input_id']}: {errors[0]}", file=sys.stderr)
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest_path = args.manifest or (images_root / f"extracted_manifest_{args.variant.lower()}.json")
    manifest_path.write_text(
        json.dumps(
            {
                "variant": args.variant,
                "limit": args.limit,
                "extracted": len(rows),
                "images": [r["source"]["source_sample_id"] for r in rows],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Extracted {len(rows)} {args.variant} images -> {images_root}")
    print(f"Review slice: {len(rows) - invalid} rows ({invalid} invalid) -> {args.review_slice}")
    print(f"Manifest -> {manifest_path}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
