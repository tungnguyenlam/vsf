"""Extract a bounded, diverse slice of VLGuard images without downloading the zips.

VLGuard ships images inside ``train.zip`` (~315 MB) and ``test.zip`` (~125 MB).
Downloading them whole is wasteful when we only need a small review/OCR slice.
This script opens the remote zips through ``HfFileSystem`` (HTTP range requests),
reads only the central directory plus the selected members, and writes the
chosen images under ``data/safety_v0/raw/vlguard/images/<image-field>`` so they
line up with ``content.original_image_path`` produced by the converter.

Selection is deterministic and diverse: it round-robins across splits and across
``harmful_subcategory`` (plus a ``safe`` bucket) so the slice covers sexual,
violence, political, personal-data, and benign images rather than one category.

Usage:

    python scripts/safety_v0/download/extract_vlguard_images.py            # 100 images
    python scripts/safety_v0/download/extract_vlguard_images.py --limit 50
    python scripts/safety_v0/download/extract_vlguard_images.py --splits test
"""

import argparse
import json
import sys
import zipfile
from collections import OrderedDict, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from huggingface_hub import HfFileSystem  # noqa: E402

from src.pipeline.Datasets.safety_v0_sources import converted_path, source_dir  # noqa: E402
from src.pipeline.Utils import load_env, load_hf_token  # noqa: E402

REPO_ID = "ys-zong/VLGuard"
SLUG = "vlguard"
SPLITS = ("train", "test")


def _bucket(record: Dict) -> str:
    """Coarse diversity bucket: safe images, or their harmful subcategory."""
    if record.get("safe"):
        return "safe"
    return (record.get("harmful_subcategory") or "unknown").strip().lower()


def select_images(
    raw_dir: Path, splits: Tuple[str, ...], limit: int
) -> "OrderedDict[str, List[str]]":
    """Pick a diverse slice. Returns {split: [image-field, ...]} preserving order.

    Round-robins across (split, bucket) groups so no single category dominates.
    Deterministic: groups and members keep source-file order; no randomness.
    """
    groups: "OrderedDict[Tuple[str, str], List[str]]" = OrderedDict()
    for split in splits:
        path = raw_dir / f"{split}.json"
        if not path.exists():
            print(f"  skip {split}: {path} missing", file=sys.stderr)
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        for record in records:
            image = record.get("image")
            if not image:
                continue
            key = (split, _bucket(record))
            groups.setdefault(key, [])
            # one row per image; ignore duplicate image references
            if image not in groups[key]:
                groups[key].append(image)

    selected: "OrderedDict[str, List[str]]" = OrderedDict((s, []) for s in splits)
    seen = 0
    cursors = defaultdict(int)
    keys = list(groups.keys())
    while seen < limit and keys:
        progressed = False
        for key in keys:
            if seen >= limit:
                break
            members = groups[key]
            idx = cursors[key]
            if idx >= len(members):
                continue
            cursors[key] = idx + 1
            split, _ = key
            selected[split].append(members[idx])
            seen += 1
            progressed = True
        if not progressed:
            break
    return selected


def extract_from_zip(
    fs: HfFileSystem,
    split: str,
    images: List[str],
    images_root: Path,
) -> Tuple[int, int]:
    """Extract the given image fields from datasets/<repo>/<split>.zip."""
    if not images:
        return 0, 0
    zip_path = f"datasets/{REPO_ID}/{split}.zip"
    written = missing = 0
    with fs.open(zip_path, "rb") as handle:
        with zipfile.ZipFile(handle) as zf:
            names = set(zf.namelist())
            for image in images:
                member = f"{split}/{image}"
                if member not in names:
                    print(f"  missing member: {member}", file=sys.stderr)
                    missing += 1
                    continue
                out_path = images_root / image
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src:
                    out_path.write_bytes(src.read())
                written += 1
    return written, missing


def write_review_slice(images_root: Path, slice_out: Path) -> int:
    """Filter the converted canonical rows down to those whose image is on disk.

    The OCR/PII/redaction stages skip rows whose ``original_image_path`` is
    missing, so this bounds those stages to the extracted slice rather than the
    full converted set. Returns the number of rows written.
    """
    conv = converted_path(SLUG)
    if not conv.exists():
        print(f"  skip review slice: {conv} missing (run the converter first)", file=sys.stderr)
        return 0
    kept = 0
    slice_out.parent.mkdir(parents=True, exist_ok=True)
    with open(conv, encoding="utf-8") as src, open(slice_out, "w", encoding="utf-8") as dst:
        for line in src:
            if not line.strip():
                continue
            row = json.loads(line)
            rel = row.get("content", {}).get("original_image_path")
            if rel and (PROJECT_ROOT / rel).exists():
                dst.write(line if line.endswith("\n") else line + "\n")
                kept += 1
    print(f"Review slice: {kept} rows (image on disk) -> {slice_out}")
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument(
        "--images-root",
        type=Path,
        default=source_dir("raw", SLUG) / "images",
        help="Where to write extracted images (matches the converter default).",
    )
    parser.add_argument("--limit", type=int, default=100, help="Total images across splits.")
    parser.add_argument(
        "--splits",
        nargs="+",
        default=list(SPLITS),
        choices=list(SPLITS),
        help="Which splits to draw from.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional JSON manifest of selected images (default under images-root).",
    )
    parser.add_argument(
        "--review-slice",
        type=Path,
        default=converted_path(SLUG).parent / "review_slice.jsonl",
        help="Where to write converted rows whose image is now on disk. "
             "Set to '' / 'none' to skip.",
    )
    args = parser.parse_args()

    load_env()
    fs = HfFileSystem(token=load_hf_token())

    images_root: Path = args.images_root
    images_root.mkdir(parents=True, exist_ok=True)

    selected = select_images(args.raw_dir, tuple(args.splits), args.limit)
    total = sum(len(v) for v in selected.values())
    print(f"Selected {total} images across {len([s for s in selected if selected[s]])} split(s).")

    written_all = missing_all = 0
    for split, images in selected.items():
        w, m = extract_from_zip(fs, split, images, images_root)
        written_all += w
        missing_all += m
        if images:
            print(f"  {split}: extracted {w}/{len(images)} ({m} missing)")

    manifest_path = args.manifest or (images_root / "extracted_manifest.json")
    manifest_path.write_text(
        json.dumps(
            {"limit": args.limit, "selected": selected, "written": written_all},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Extracted {written_all} images ({missing_all} missing) -> {images_root}")
    print(f"Manifest -> {manifest_path}")

    if args.review_slice and str(args.review_slice).lower() not in ("", "none"):
        write_review_slice(images_root, Path(args.review_slice))
    return 1 if missing_all else 0


if __name__ == "__main__":
    raise SystemExit(main())
