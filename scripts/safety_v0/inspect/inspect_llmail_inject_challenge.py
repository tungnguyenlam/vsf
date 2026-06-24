"""Inspect the bounded `microsoft/llmail-inject-challenge` raw sample.

Reads the per-phase JSONL written by
``scripts/safety_v0/download/download_llmail_inject_challenge.py`` and writes
inspection artifacts under
``data/safety_v0/inspection/llmail_inject_challenge/``:

- ``schema.json`` — columns + phase sample sizes
- ``stats.json``  — scenario distribution, objective success counts, body
  length, and the script-filter drop count
- ``sample_rows.jsonl`` — a few compact example rows

Usage::

    python scripts/safety_v0/inspect/inspect_llmail_inject_challenge.py
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

from src.pipeline.Datasets.language import is_mostly_latin  # noqa: E402
from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402

SLUG = "llmail_inject_challenge"


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
    scenarios = Counter(r.get("scenario") for r in rows)
    objective_true = Counter()
    for r in rows:
        raw = r.get("objectives")
        obj = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
        for key, value in obj.items():
            if value is True:
                objective_true[key] += 1
    body_lengths = [len((r.get("body") or "")) for r in rows]
    text = [(r.get("subject") or "") + "\n" + (r.get("body") or "") for r in rows]
    non_latin = sum(1 for t in text if not is_mostly_latin(t))
    return {
        "rows": len(rows),
        "top_scenarios": scenarios.most_common(10),
        "objective_true_counts": dict(objective_true),
        "body_length": length_buckets(body_lengths),
        "non_latin_rows_would_drop": non_latin,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def compact(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "scenario": record.get("scenario"),
        "subject": record.get("subject"),
        "body": (record.get("body") or "")[:300],
        "objectives": record.get("objectives"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--out-dir", type=Path, default=source_dir("inspection", SLUG, create=True))
    parser.add_argument("--sample-rows", type=int, default=6)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    split_files = sorted(p for p in args.raw_dir.glob("*.jsonl"))
    if not split_files:
        raise FileNotFoundError(
            f"No raw JSONL under {args.raw_dir}. Run download_llmail_inject_challenge.py first."
        )

    splits = {p.stem: load_split(p) for p in split_files}
    schema = {
        "repo_id": "microsoft/llmail-inject-challenge",
        "columns": ["subject", "body", "objectives", "scenario", "output", "team_id", "job_id", "RowKey"],
        "phase_sample_sizes": {name: len(rows) for name, rows in splits.items()},
        "note": "All rows are prompt-injection attempts (positives only).",
    }
    stats = {name: summarize(rows) for name, rows in splits.items()}

    write_json(args.out_dir / "schema.json", schema)
    write_json(args.out_dir / "stats.json", stats)
    first = next(iter(splits.values()))
    write_jsonl(args.out_dir / "sample_rows.jsonl", (compact(r) for r in first[: args.sample_rows]))

    print(f"Wrote inspection artifacts to {args.out_dir}")
    print(json.dumps(stats, ensure_ascii=False, indent=2)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
