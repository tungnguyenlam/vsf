"""Inspect the bounded UIT-ViHSD raw sample.

Reads the per-split JSONL written by
``scripts/safety_v0/download/download_vihsd_topic_safety.py`` and writes
inspection artifacts under ``data/safety_v0/inspection/vihsd_topic_safety/``:

- ``schema.json`` — columns + per-split sample sizes
- ``stats.json``  — label distribution, empty-text count, comment length buckets
- ``sample_rows.jsonl`` — a few compact example rows per label

Usage::

    python scripts/safety_v0/inspect/inspect_vihsd_topic_safety.py
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402

SLUG = "vihsd_topic_safety"
LABEL_NAMES = {0: "CLEAN", 1: "OFFENSIVE", 2: "HATE"}


def load_split(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


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
    labels = Counter(r.get("label_id") for r in rows)
    named = {LABEL_NAMES.get(k, str(k)): v for k, v in labels.items()}
    texts = [(r.get("free_text") or "") for r in rows]
    empty = sum(1 for t in texts if not t.strip())
    return {
        "rows": len(rows),
        "label_id_dist": dict(labels),
        "label_name_dist": named,
        "empty_text": empty,
        "text_length": length_buckets([len(t) for t in texts]),
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
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    split_files = sorted(p for p in args.raw_dir.glob("*.jsonl"))
    if not split_files:
        raise FileNotFoundError(
            f"No raw JSONL under {args.raw_dir}. Run download_vihsd_topic_safety.py first."
        )

    splits = {p.stem: load_split(p) for p in split_files}
    schema = {
        "mirror_repo": "phucdev/ViHSD",
        "canonical_repo": "uitnlp/vihsd",
        "columns": ["free_text", "label_id"],
        "label_names": LABEL_NAMES,
        "split_sample_sizes": {name: len(rows) for name, rows in splits.items()},
    }
    stats = {name: summarize(rows) for name, rows in splits.items()}

    write_json(args.out_dir / "schema.json", schema)
    write_json(args.out_dir / "stats.json", stats)

    # A couple of examples per label from the train split.
    train = splits.get("train", next(iter(splits.values())))
    examples: List[Dict[str, Any]] = []
    for label in (0, 1, 2):
        picks = [r for r in train if r.get("label_id") == label][:2]
        examples.extend(
            {"label_id": r["label_id"], "label_name": LABEL_NAMES.get(r["label_id"]),
             "free_text": (r.get("free_text") or "")[:200]}
            for r in picks
        )
    write_jsonl(args.out_dir / "sample_rows.jsonl", examples)

    print(f"Wrote inspection artifacts to {args.out_dir}")
    print(json.dumps(stats, ensure_ascii=False, indent=2)[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
