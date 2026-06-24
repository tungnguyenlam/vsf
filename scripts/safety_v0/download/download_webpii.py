"""Download the WebPII sample snapshot and link it into the safety_v0 raw tree.

Default behavior follows DATA_PLAN.md for WebPII: download the bounded upstream
sample first, not the full multi-GB parquet snapshot.

Usage:

    python scripts/safety_v0/download/download_webpii.py
    python scripts/safety_v0/download/download_webpii.py --full
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets import safety_v0_sources as sv  # noqa: E402


REPO_ID = "WebPII/webpii"
SAMPLE_PATTERNS = [
    "README.md",
    "sample/README.md",
    "sample/sample_manifest.json",
    "sample/schema_sample_100.parquet",
    "sample/webpii_visual_samples.zip",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Download all WebPII files, including the multi-GB train/test parquet shards.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Optional Hugging Face cache root. Defaults to the standard HF cache.",
    )
    parser.add_argument(
        "--raw-link",
        type=Path,
        default=sv.DEFAULT_DATA_ROOT / "raw" / "webpii",
        help="Repo path to symlink to the cached HF snapshot.",
    )
    parser.add_argument(
        "--force-link",
        action="store_true",
        help="Replace an existing symlink at --raw-link if it points elsewhere.",
    )
    return parser.parse_args()


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
    args = parse_args()

    from huggingface_hub import snapshot_download

    allow_patterns = None if args.full else SAMPLE_PATTERNS
    snapshot = Path(
        snapshot_download(
            repo_id=REPO_ID,
            repo_type="dataset",
            allow_patterns=allow_patterns,
            cache_dir=args.cache_dir,
        )
    )
    link_snapshot(snapshot, args.raw_link, force=args.force_link)

    mode = "full" if args.full else "sample"
    print(f"Downloaded WebPII {mode} snapshot: {snapshot}")
    print(f"Linked raw source: {args.raw_link} -> {snapshot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
