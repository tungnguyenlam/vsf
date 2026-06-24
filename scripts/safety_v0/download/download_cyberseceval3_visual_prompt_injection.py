"""Download `facebook/cyberseceval3-visual-prompt-injection` (metadata + images).

The dataset is a real **visual** prompt-injection benchmark: `test_cases.json`
holds the 1,000 text records and `images/<id>.png` holds the rendered image for
each record (the injection is drawn into the image). Each image is ~1.3 MB, so
the full set is ~1.3 GB.

Per DATA_PLAN cost discipline this downloads a BOUNDED sample by default
(`--limit 100`, ~135 MB) and links it into the raw tree; pass `--full` for all
1,000 images. The snapshot is linked at `data/safety_v0/raw/cyberseceval3_visual_prompt_injection`.

Usage::

    python scripts/safety_v0/download/download_cyberseceval3_visual_prompt_injection.py
    python scripts/safety_v0/download/download_cyberseceval3_visual_prompt_injection.py --full
    python scripts/safety_v0/download/download_cyberseceval3_visual_prompt_injection.py --limit 300
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets import safety_v0_sources as sv  # noqa: E402
from src.pipeline.Utils import load_env, load_hf_token  # noqa: E402

REPO_ID = "facebook/cyberseceval3-visual-prompt-injection"
SLUG = "cyberseceval3_visual_prompt_injection"
# Image ids are 0-based and contiguous (0..999), so a bounded sample is the
# first N images plus the metadata file.
BASE_PATTERNS = ["README.md", "test_cases.json"]


def link_snapshot(snapshot_path: Path, raw_link: Path, *, force: bool = False) -> None:
    raw_link.parent.mkdir(parents=True, exist_ok=True)
    if raw_link.is_symlink():
        current = raw_link.resolve()
        if current == snapshot_path.resolve():
            return
        if not force:
            raise FileExistsError(
                f"{raw_link} already points to {current}; pass --force-link to replace it"
            )
        raw_link.unlink()
    elif raw_link.exists():
        raise FileExistsError(f"{raw_link} exists and is not a symlink")
    raw_link.symlink_to(snapshot_path, target_is_directory=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Number of images to download (first N ids). Default 100; ignored with --full.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Download all 1,000 images (~1.3 GB).",
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument(
        "--raw-link",
        type=Path,
        default=sv.DEFAULT_DATA_ROOT / "raw" / SLUG,
    )
    parser.add_argument("--force-link", action="store_true")
    args = parser.parse_args()

    load_env()
    load_hf_token()  # ensures HF_TOKEN is in env for snapshot_download if gated

    from huggingface_hub import snapshot_download

    if args.full:
        allow_patterns = BASE_PATTERNS + ["images/*.png"]
    else:
        allow_patterns = BASE_PATTERNS + [f"images/{i}.png" for i in range(args.limit)]

    snapshot = Path(
        snapshot_download(
            repo_id=REPO_ID,
            repo_type="dataset",
            allow_patterns=allow_patterns,
            cache_dir=args.cache_dir,
        )
    )
    link_snapshot(snapshot, args.raw_link, force=args.force_link)

    n_images = len(list((snapshot / "images").glob("*.png"))) if (snapshot / "images").exists() else 0
    mode = "full" if args.full else f"sample(limit={args.limit})"
    print(f"Downloaded cyberseceval3 {mode} snapshot: {snapshot}")
    print(f"Images present: {n_images}")
    print(f"Linked raw source: {args.raw_link} -> {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
