"""Download a BOUNDED sample of UIT-ViHSD (Vietnamese Hate Speech Detection).

The canonical ``uitnlp/vihsd`` repo is a loading-script dataset and is not
parquet-indexed by the datasets-server, so we pull the data from the
``phucdev/ViHSD`` mirror, which preserves the original schema (``free_text`` +
``label_id``) and the train/validation/test splits. The dataset identity we
record on each row stays the canonical ``uitnlp/vihsd`` (see
``safety_v0_sources``); only the download location is the mirror.

Per DATA_PLAN we take a bounded sample (not all ~33k rows): this pages the
datasets-server ``/rows`` API (no full-file download) and persists per-split
JSONL under ``data/safety_v0/raw/vihsd_topic_safety/``. The sample follows the
source row order, so it keeps the source's class skew (mostly CLEAN);
class balancing happens later at review-queue / final-build selection.

Usage::

    python scripts/safety_v0/download/download_vihsd_topic_safety.py
    python scripts/safety_v0/download/download_vihsd_topic_safety.py --train-limit 3000
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402
from src.pipeline.Utils import load_env, load_hf_token  # noqa: E402

MIRROR_REPO = "phucdev/ViHSD"
SLUG = "vihsd_topic_safety"
# Source split -> our split name. ViHSD's validation becomes our dev split.
SPLIT_MAP = {"train": "train", "validation": "dev", "test": "test"}
_SERVER = "https://datasets-server.huggingface.co"
_PAGE = 100  # datasets-server max rows per /rows request


def _get(url: str, token: Optional[str]) -> Dict[str, Any]:
    headers = {"User-Agent": "vsf-download"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def fetch_rows(split: str, limit: int, token: Optional[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    ds = urllib.parse.quote(MIRROR_REPO)
    while len(rows) < limit:
        length = min(_PAGE, limit - len(rows))
        url = (
            f"{_SERVER}/rows?dataset={ds}&config=default&split={split}"
            f"&offset={offset}&length={length}"
        )
        page = _get(url, token)
        batch = [r["row"] for r in page.get("rows", [])]
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-limit", type=int, default=2000)
    parser.add_argument("--val-limit", type=int, default=500)
    parser.add_argument("--test-limit", type=int, default=1000)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    load_env()
    token = load_hf_token()
    out_dir = args.out_dir or source_dir("raw", SLUG, create=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    limits = {"train": args.train_limit, "validation": args.val_limit, "test": args.test_limit}
    for src_split, limit in limits.items():
        rows = fetch_rows(src_split, limit, token)
        # Persist under our split name so downstream stages read train/dev/test.
        path = out_dir / f"{SPLIT_MAP[src_split]}.jsonl"
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Wrote {len(rows)} rows ({src_split}) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
