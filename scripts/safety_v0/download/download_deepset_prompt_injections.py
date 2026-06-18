"""Download the `deepset/prompt-injections` dataset into the safety_v0 raw tree.

The dataset is tiny (train 546 / test 116, two columns: ``text`` + ``label``),
so we download it whole and persist each split as JSONL under
``data/safety_v0/raw/deepset_prompt_injections/`` to decouple conversion from
the network (the converter reads the raw JSONL, never HF).

``label`` is the gold prompt-injection flag (1 = attack, 0 = benign). Content is
English + German (see ``docs/datasets/deepset_prompt_injections.md``).

Usage::

    python scripts/safety_v0/download/download_deepset_prompt_injections.py
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402
from src.pipeline.Utils import load_env  # noqa: E402

REPO_ID = "deepset/prompt-injections"
SLUG = "deepset_prompt_injections"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Raw output directory. Defaults to data/safety_v0/raw/<slug>/.",
    )
    args = parser.parse_args()

    load_env()  # HF_TOKEN if the dataset ever needs auth (public today)
    from datasets import load_dataset

    out_dir = args.out_dir or source_dir("raw", SLUG, create=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    ds = load_dataset(REPO_ID)
    for split, dset in ds.items():
        path = out_dir / f"{split}.jsonl"
        with open(path, "w", encoding="utf-8") as handle:
            for record in dset:
                handle.write(json.dumps(dict(record), ensure_ascii=False) + "\n")
        print(f"Wrote {len(dset)} rows -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
