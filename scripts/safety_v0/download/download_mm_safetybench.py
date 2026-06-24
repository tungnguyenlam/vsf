"""Download bounded MM-SafetyBench metadata into the safety_v0 raw tree.

MM-SafetyBench (``PKU-Alignment/MM-SafetyBench``) is a public (non-gated)
multimodal jailbreak benchmark. It ships one folder per harmful category, each
with four Parquet splits:

- ``Text_only.parquet``  -- ``id`` + the original harmful ``question`` (image is
  null). These files are tiny (~6-10 KB each).
- ``TYPO.parquet``       -- the harmful keyword rendered as typography in an
  image; the ``question`` is rewritten to point at the image (~0.6-3.8 MB).
- ``SD.parquet``         -- a Stable-Diffusion image for the keyword (~6-25 MB).
- ``SD_TYPO.parquet``    -- SD image with the keyword typed at the bottom
  (~7-25 MB).

The harmful instruction lives in the ``Text_only`` ``question`` and (for the
image splits) is smuggled into the image as text. This downloader fetches only
the lightweight ``Text_only`` parquets by default -- enough to inspect the label
taxonomy and questions without pulling the multi-hundred-MB image parquets.
Pull image parquets explicitly later with ``--include-images``.

Usage:

    python scripts/safety_v0/download/download_mm_safetybench.py
    python scripts/safety_v0/download/download_mm_safetybench.py --include-images
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

REPO_ID = "PKU-Alignment/MM-SafetyBench"
SLUG = "mm_safetybench"

# 13 harmful-scenario categories (one folder each upstream).
CATEGORIES = (
    "EconomicHarm",
    "Financial_Advice",
    "Fraud",
    "Gov_Decision",
    "HateSpeech",
    "Health_Consultation",
    "Illegal_Activitiy",  # upstream spelling kept verbatim
    "Legal_Opinion",
    "Malware_Generation",
    "Physical_Harm",
    "Political_Lobbying",
    "Privacy_Violence",
    "Sex",
)

METADATA_SPLIT = "Text_only"
IMAGE_SPLITS = ("TYPO", "SD", "SD_TYPO")


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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cached, out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--include-images",
        action="store_true",
        help="Also download the TYPO/SD/SD_TYPO image parquets (hundreds of MB). "
        "Text_only metadata only by default.",
    )
    args = parser.parse_args()

    load_env()
    token = load_hf_token()
    out_dir = args.out_dir or source_dir("raw", SLUG, create=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    splits = [METADATA_SPLIT]
    if args.include_images:
        splits.extend(IMAGE_SPLITS)

    total = 0
    for category in CATEGORIES:
        for split in splits:
            filename = f"data/{category}/{split}.parquet"
            out_path = download_file(filename, out_dir, token)
            size = out_path.stat().st_size
            total += size
            print(f"Wrote {filename} -> {out_path} ({size} bytes)")
    print(f"Downloaded {len(CATEGORIES)} categories x {len(splits)} split(s), {total} bytes total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
