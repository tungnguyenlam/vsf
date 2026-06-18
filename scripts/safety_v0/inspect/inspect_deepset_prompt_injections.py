"""Inspect the cached `deepset/prompt-injections` raw JSONL for conversion planning.

Reads the raw splits written by
``scripts/safety_v0/download/download_deepset_prompt_injections.py`` and writes
lightweight inspection artifacts under
``data/safety_v0/inspection/deepset_prompt_injections/``:

- ``schema.json``  — columns, dtypes, split sizes
- ``stats.json``   — label balance, text-length distribution, rough language mix
- ``sample_rows.jsonl`` — a few attack and benign examples

Usage::

    python scripts/safety_v0/inspect/inspect_deepset_prompt_injections.py
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402

SLUG = "deepset_prompt_injections"
# Rough German detector for the language-mix estimate (deepset mixes EN + DE).
_DE_STOPWORDS = re.compile(r"\b(und|der|die|das|ich|nicht|Sie|für|mit|auf|ist|ein|eine)\b")


def load_split(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def length_buckets(lengths: List[int]) -> Dict[str, int]:
    if not lengths:
        return {}
    ordered = sorted(lengths)
    return {
        "min": ordered[0],
        "p50": ordered[len(ordered) // 2],
        "p90": ordered[int(len(ordered) * 0.9)],
        "max": ordered[-1],
    }


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    labels = Counter(int(r.get("label", 0)) for r in rows)
    lengths = [len(r.get("text", "") or "") for r in rows]
    de = sum(1 for r in rows if _DE_STOPWORDS.search(r.get("text", "") or ""))
    return {
        "rows": len(rows),
        "label_counts": {"benign(0)": labels.get(0, 0), "attack(1)": labels.get(1, 0)},
        "text_length": length_buckets(lengths),
        "rows_with_german_stopwords": de,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--out-dir", type=Path, default=source_dir("inspection", SLUG, create=True))
    parser.add_argument("--sample-rows", type=int, default=6)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    split_files = sorted(args.raw_dir.glob("*.jsonl"))
    if not split_files:
        raise FileNotFoundError(
            f"No raw JSONL under {args.raw_dir}. Run download_deepset_prompt_injections.py first."
        )

    splits = {p.stem: load_split(p) for p in split_files}
    schema = {
        "repo_id": "deepset/prompt-injections",
        "columns": {"text": "string", "label": "int (1=attack, 0=benign)"},
        "split_sizes": {name: len(rows) for name, rows in splits.items()},
        "language": "English + German (mixed)",
    }
    stats = {name: summarize(rows) for name, rows in splits.items()}

    write_json(args.out_dir / "schema.json", schema)
    write_json(args.out_dir / "stats.json", stats)

    # A few attack + benign samples from the train split for eyeballing.
    train = splits.get("train", next(iter(splits.values())))
    half = max(1, args.sample_rows // 2)
    attacks = [r for r in train if int(r.get("label", 0)) == 1][:half]
    benigns = [r for r in train if int(r.get("label", 0)) == 0][:half]
    write_jsonl(args.out_dir / "sample_rows.jsonl", attacks + benigns)

    print(f"Wrote inspection artifacts to {args.out_dir}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
