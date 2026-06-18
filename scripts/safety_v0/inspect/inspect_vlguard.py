"""Inspect VLGuard metadata for safety_v0 conversion planning.

Reads ``train.json`` and ``test.json`` from ``data/safety_v0/raw/vlguard`` and
writes:

- ``schema.json``: raw columns and split sizes
- ``stats.json``: safe/unsafe and harmful category counts
- ``sample_rows.jsonl``: a small mixed sample for manual inspection
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402

SLUG = "vlguard"
SPLITS = ("train", "test")


def load_split(raw_dir: Path, split: str) -> List[Dict[str, Any]]:
    path = raw_dir / f"{split}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    safe_counts = Counter(bool(r.get("safe")) for r in rows)
    categories = Counter(r.get("harmful_category") for r in rows if not r.get("safe"))
    subcategories: Dict[str, Counter] = defaultdict(Counter)
    instruction_lengths = Counter()
    for row in rows:
        instruction_lengths[len(row.get("instr-resp") or [])] += 1
        if not row.get("safe"):
            subcategories[str(row.get("harmful_category"))][row.get("harmful_subcategory")] += 1
    return {
        "rows": len(rows),
        "safe_counts": {"safe": safe_counts[True], "unsafe": safe_counts[False]},
        "harmful_category_counts": dict(categories),
        "harmful_subcategory_counts": {
            key: dict(value) for key, value in sorted(subcategories.items())
        },
        "instruction_response_lengths": dict(instruction_lengths),
    }


def sample_rows(splits: Dict[str, List[Dict[str, Any]]], per_split: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for split, rows in splits.items():
        safe = [r for r in rows if r.get("safe")][:per_split]
        unsafe = [r for r in rows if not r.get("safe")][:per_split]
        for row in safe + unsafe:
            copied = dict(row)
            copied["split"] = split
            out.append(copied)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--out-dir", type=Path, default=source_dir("inspection", SLUG, create=True))
    parser.add_argument("--sample-per-split", type=int, default=4)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    splits = {split: load_split(args.raw_dir, split) for split in SPLITS}
    if not any(splits.values()):
        raise FileNotFoundError(f"No VLGuard metadata JSON found under {args.raw_dir}")

    schema = {
        "repo_id": "ys-zong/VLGuard",
        "columns": {
            "id": "string",
            "image": "relative image path inside train.zip/test.zip",
            "safe": "bool image safety flag",
            "harmful_category": "string, unsafe rows only",
            "harmful_subcategory": "string, unsafe rows only",
            "instr-resp": "list of instruction/response objects",
        },
        "split_sizes": {split: len(rows) for split, rows in splits.items()},
        "license": "mit",
        "access": "gated",
    }
    stats = {split: summarize(rows) for split, rows in splits.items()}

    write_json(args.out_dir / "schema.json", schema)
    write_json(args.out_dir / "stats.json", stats)
    write_jsonl(args.out_dir / "sample_rows.jsonl", sample_rows(splits, args.sample_per_split))

    print(f"Wrote VLGuard inspection artifacts to {args.out_dir}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
