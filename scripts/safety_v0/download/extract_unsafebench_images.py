"""Extract the UnsafeBench image bytes out of the parquet onto disk as JPEGs.

The converter (``convert_unsafebench.py``) emits one canonical row per image and
points ``content.original_image_path`` at
``data/safety_v0/raw/unsafebench/images/<input_id>.jpg`` -- but the actual pixels
are still inside the parquet's ``image`` column. This script PIL-decodes that
column and writes each image to the path the converter already references, using
the **same 1-based row order** so ``input_id`` lines up exactly:

    parquet row 0 -> safety_v0_unsafebench_000001.jpg
    parquet row 1 -> safety_v0_unsafebench_000002.jpg
    ...

The HF ``Image`` feature is stored in the parquet as a struct
``{"bytes": <png/jpeg bytes>, "path": <str|None>}``; we also accept a raw
``bytes`` cell (what the synthetic test parquet uses) and a path-only cell.
Everything is normalized to RGB and saved as JPEG so downstream OCR / redaction
stages get a consistent format.

Usage (requires the test parquet already downloaded; no HF token needed here):

    python scripts/safety_v0/download/extract_unsafebench_images.py
    python scripts/safety_v0/download/extract_unsafebench_images.py --limit 50
"""

import argparse
import io
import sys
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    format_input_id,
    source_dir,
)

SLUG = "unsafebench"

# Only the image column is needed; never materialize the label columns here.
IMAGE_COLUMN = "image"


def _decode_image_cell(cell: Any):
    """Return a PIL.Image for one parquet ``image`` cell, or None if undecodable.

    Handles the three shapes we can see:
    - HF ``Image`` feature: a dict ``{"bytes": ..., "path": ...}``
    - a raw ``bytes`` / ``bytearray`` blob (synthetic test parquet)
    - a filesystem path string (rare; HF can store path-only references)
    """
    from PIL import Image

    raw: Optional[bytes] = None
    path: Optional[str] = None

    if isinstance(cell, dict):
        raw = cell.get("bytes")
        path = cell.get("path")
    elif isinstance(cell, (bytes, bytearray)):
        raw = bytes(cell)
    elif isinstance(cell, str):
        path = cell

    if raw:
        return Image.open(io.BytesIO(raw))
    if path and Path(path).exists():
        return Image.open(path)
    return None


def extract_images(
    parquet_path: Path,
    images_root: Path,
    *,
    limit: Optional[int] = None,
    overwrite: bool = False,
    quality: int = 90,
) -> dict:
    """Decode the parquet ``image`` column into ``<images_root>/<input_id>.jpg``.

    Returns a small summary dict (written / skipped / failed counts).
    """
    import pandas as pd

    df = pd.read_parquet(parquet_path, columns=[IMAGE_COLUMN])
    if limit is not None:
        df = df.head(limit)

    images_root.mkdir(parents=True, exist_ok=True)

    written = skipped = failed = 0
    for row_idx, cell in enumerate(df[IMAGE_COLUMN].tolist()):
        input_id = format_input_id(SLUG, row_idx + 1)  # 1-based; matches converter
        out_path = images_root / f"{input_id}.jpg"

        if out_path.exists() and not overwrite:
            skipped += 1
            continue

        try:
            image = _decode_image_cell(cell)
            if image is None:
                raise ValueError("no decodable bytes/path in image cell")
            image.convert("RGB").save(out_path, format="JPEG", quality=quality)
            written += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  failed row {row_idx} ({input_id}): {exc}", file=sys.stderr)

    return {"written": written, "skipped": skipped, "failed": failed,
            "total": len(df)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parquet",
        type=Path,
        default=source_dir("raw", SLUG) / "data" / "test-00000-of-00001.parquet",
        help="Downloaded UnsafeBench parquet (test or train).",
    )
    parser.add_argument(
        "--images-root",
        type=Path,
        default=source_dir("raw", SLUG) / "images",
        help="Where to write <input_id>.jpg. Must match the converter's "
        "--images-root (default is the same).",
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Only extract the first N rows (matches converter --limit).")
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-decode images that already exist on disk.")
    parser.add_argument("--quality", type=int, default=90,
                        help="JPEG quality (default 90).")
    args = parser.parse_args()

    if not args.parquet.exists():
        raise FileNotFoundError(
            f"No parquet at {args.parquet}. Run download_unsafebench.py first."
        )

    print(f"Extracting UnsafeBench images from {args.parquet} -> {args.images_root} ...")
    summary = extract_images(
        args.parquet,
        args.images_root,
        limit=args.limit,
        overwrite=args.overwrite,
        quality=args.quality,
    )
    print(
        f"Extracted {summary['written']} images "
        f"({summary['skipped']} already present, {summary['failed']} failed) "
        f"out of {summary['total']} rows -> {args.images_root}"
    )
    if summary["failed"]:
        print(
            "Next: re-run with --overwrite after inspecting the failures above, "
            "then run the OCR -> PII -> prompt-injection stages.",
            file=sys.stderr,
        )
        return 1
    print(
        "Next: run the OCR -> PII -> prompt-injection weak-label stages over "
        "these images (English-only; PII redactions expected near zero)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
