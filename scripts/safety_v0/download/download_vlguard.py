"""Download bounded VLGuard metadata into the safety_v0 raw tree.

VLGuard is gated on Hugging Face and stores large images in ``train.zip`` and
``test.zip``. This downloader intentionally fetches only lightweight metadata by
default: ``README.md``, ``train.json``, and ``test.json``. Download image zips
explicitly later with ``--include-zips`` once the source mapping is accepted.

Usage:

    python scripts/safety_v0/download/download_vlguard.py
    python scripts/safety_v0/download/download_vlguard.py --include-zips
"""

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from huggingface_hub import hf_hub_download  # noqa: E402

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402
from src.pipeline.Utils import load_env, load_hf_token  # noqa: E402

REPO_ID = "ys-zong/VLGuard"
SLUG = "vlguard"
METADATA_FILES = ("README.md", "train.json", "test.json")
ZIP_FILES = ("train.zip", "test.zip")


def download_file(filename: str, out_dir: Path, token: str | None) -> Path:
    cached = Path(
        hf_hub_download(
            REPO_ID,
            filename=filename,
            repo_type="dataset",
            token=token,
        )
    )
    out_path = out_dir / filename
    shutil.copy2(cached, out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--include-zips",
        action="store_true",
        help="Also download train.zip/test.zip (multi-GB). Metadata only by default.",
    )
    args = parser.parse_args()

    load_env()
    token = load_hf_token()
    out_dir = args.out_dir or source_dir("raw", SLUG, create=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = list(METADATA_FILES)
    if args.include_zips:
        files.extend(ZIP_FILES)

    for filename in files:
        out_path = download_file(filename, out_dir, token)
        print(f"Wrote {filename} -> {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
