"""Download a bounded slice of `yiting/UnsafeBench` into the safety_v0 raw tree.

`yiting/UnsafeBench` is a Hugging Face image-safety benchmark with 10,146 labeled
images across 11 unsafe categories (Hate, Harassment, Violence, Self-Harm, Sexual,
Shocking, Illegal Activity, Deception, Political, Public and Personal Health,
Spam -- the OpenAI DALL-E content-policy taxonomy, April 2022 version) and two
image sources (LAION-5B real-world, Lexica AI-generated). It is shipped as a
single train parquet (755 MB) and a single test parquet (184 MB) and is
**GATED** under a Data Use Agreement (DUA) that requires manual approval on the
HF dataset page before any user can read the files.

Per DATA_PLAN cost discipline this downloader:

- does NOT pull the multi-GB archives automatically. The full train parquet is
  not pulled by default; only the test parquet (184 MB) is fetched when a row
  limit is requested, and even then we stream only the first N rows of the
  split through PyArrow so we never have to materialize the whole image
  column to disk.
- fails LOUDLY with a clear "DUA access required" message when the user's HF
  token does not have the dataset approved. We do not silently retry or skip.
- never tries to enumerate the gated files via the datasets-server
  ``/rows`` API (the server returns 404 for gated repos regardless of token).

Usage (all require a HF token that has been granted access to
`yiting/UnsafeBench`):

    # 50 rows of the test split (default; small, ~tens of MB of image bytes)
    python scripts/safety_v0/download/download_unsafebench.py

    # Custom row limit
    python scripts/safety_v0/download/download_unsafebench.py --limit 200

    # Pull from the train split (much larger, ~755 MB raw)
    python scripts/safety_v0/download/download_unsafebench.py --split train --limit 500
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from huggingface_hub import hf_hub_download  # noqa: E402

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402
from src.pipeline.Utils import load_env, load_hf_token  # noqa: E402

REPO_ID = "yiting/UnsafeBench"
SLUG = "unsafebench"

# Parquet shards in the repo (only these two files exist; no separate meta/).
PARQUET_FILES = {
    "train": "data/train-00000-of-00001.parquet",
    "test": "data/test-00000-of-00001.parquet",
}

# 11 unsafe categories (paper Section 2.1, "Unsafe Image Taxonomy", citing
# OpenAI DALL-E content policy April 2022). The HF dataset uses the short
# labels below in its `category` column; "Health" is the paper's abbreviation
# for "Public and Personal Health". "Shocking" is in the paper but not always
# present in the released CSV -- listing it for completeness / future-proofing.
UNSAFE_CATEGORIES = (
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


def _require_hf_token() -> str:
    """Return the HF token or exit with a clear DUA-required error.

    The dataset is gated. Without a token that has been granted access the HF
    API will return 403 even for the README; we treat the missing-token case
    the same as the not-yet-approved case so the user knows exactly what to
    do next.
    """
    token = load_hf_token()
    if not token:
        sys.exit(
            "UnsafeBench is gated under a DUA. Set HF_TOKEN in .env (or "
            "`huggingface-cli login`) with an account that has been granted "
            "access at https://huggingface.co/datasets/yiting/UnsafeBench, "
            "then re-run."
        )
    return token


def download_split(
    split: str, out_dir: Path, token: str, *, force: bool = False
) -> Path:
    """Materialize the requested split's parquet into the raw tree.

    Downloads the whole parquet (no streaming at the HF layer -- gated repos
    do not support range reads). PyArrow can then stream the rows on demand
    in the inspector without unpacking the whole image column.
    """
    if split not in PARQUET_FILES:
        raise ValueError(f"Unknown split {split!r}; choose from {sorted(PARQUET_FILES)}.")
    src_name = PARQUET_FILES[split]
    cached = Path(hf_hub_download(REPO_ID, src_name, repo_type="dataset", token=token))
    out_path = out_dir / src_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not force:
        if out_path.resolve() == cached.resolve():
            return out_path
        # Don't blow away a user-edited copy; just point at the new cache file.
        out_path.unlink()
    shutil.copy2(cached, out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        choices=sorted(PARQUET_FILES),
        default="test",
        help="Which split to download. Default test (184 MB raw, smaller and "
        "labeled with the same schema as train).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Where to write the parquet. Defaults to "
        "data/safety_v0/raw/unsafebench/.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if the parquet is already present in the raw tree.",
    )
    args = parser.parse_args()

    token = _require_hf_token()
    out_dir = args.out_dir or source_dir("raw", SLUG, create=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {REPO_ID} split={args.split} -> {out_dir} ...")
    try:
        out_path = download_split(args.split, out_dir, token, force=args.force)
    except Exception as exc:  # noqa: BLE001
        # Surface the most actionable error: GatedRepoError means access not yet
        # granted. Anything else (network, 5xx) is a transient failure.
        name = type(exc).__name__
        if "GatedRepo" in name or "Forbidden" in name or "403" in str(exc):
            sys.exit(
                f"Hugging Face denied access to {REPO_ID}. Confirm the HF "
                f"token in .env belongs to an account that has been granted "
                f"access (DUA approval can take 1-2 days). Original error: {exc}"
            )
        raise

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"Wrote {out_path} ({size_mb:.1f} MB)")
    print(
        "Next: run the inspector to enumerate categories, source distribution, "
        "and sample rows before writing the converter.\n"
        f"  python scripts/safety_v0/inspect/inspect_unsafebench.py "
        f"--parquet {out_path} --limit 50"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
