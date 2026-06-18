"""Download a BOUNDED sample of `microsoft/llmail-inject-challenge` into raw.

The full dataset is huge (Phase1 ~370k rows / 448 MB, Phase2 ~91k rows; raw
shards are multi-GB), and every row is a prompt-injection *attempt* against an
email assistant, so they are highly repetitive. Per DATA_PLAN we take a bounded
sample, not the whole thing: this pages the Hugging Face datasets-server
``/rows`` API (no full-file download) and persists ``--limit`` rows per phase as
JSONL under ``data/safety_v0/raw/llmail_inject_challenge/``. The tiny
description files (scenarios / objectives / levels / system prompt) are fetched
whole for documentation.

Usage::

    python scripts/safety_v0/download/download_llmail_inject_challenge.py
    python scripts/safety_v0/download/download_llmail_inject_challenge.py --limit 2000
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402
from src.pipeline.Utils import load_env  # noqa: E402

REPO_ID = "microsoft/llmail-inject-challenge"
SLUG = "llmail_inject_challenge"
PHASES = ["Phase1", "Phase2"]
META_FILES = [
    "data/scenarios.json",
    "data/objectives_descriptions.json",
    "data/levels_descriptions.json",
    "data/system_prompt.json",
]
_SERVER = "https://datasets-server.huggingface.co"
_PAGE = 100  # datasets-server max rows per /rows request


def _get(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "vsf-download"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def fetch_rows(split: str, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    ds = urllib.parse.quote(REPO_ID)
    while len(rows) < limit:
        length = min(_PAGE, limit - len(rows))
        url = f"{_SERVER}/rows?dataset={ds}&config=default&split={split}&offset={offset}&length={length}"
        page = _get(url)
        batch = [r["row"] for r in page.get("rows", [])]
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1000, help="Rows per phase.")
    parser.add_argument("--phases", nargs="*", default=PHASES)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    load_env()
    out_dir = args.out_dir or source_dir("raw", SLUG, create=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    for phase in args.phases:
        rows = fetch_rows(phase, args.limit)
        path = out_dir / f"{phase}.jsonl"
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Wrote {len(rows)} rows -> {path}")

    # Tiny description files for documentation/taxonomy.
    from huggingface_hub import hf_hub_download

    meta_dir = out_dir / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    for rel in META_FILES:
        local = hf_hub_download(repo_id=REPO_ID, repo_type="dataset", filename=rel)
        dst = meta_dir / Path(rel).name
        dst.write_bytes(Path(local).read_bytes())
        print(f"Fetched meta -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
