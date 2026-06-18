"""Inspect the cached cyberseceval3-visual-prompt-injection raw JSONL.

Reads the raw split written by
``scripts/safety_v0/download/download_cyberseceval3_visual_prompt_injection.py``
and writes lightweight inspection artifacts under
``data/safety_v0/inspection/cyberseceval3_visual_prompt_injection/``:

- ``schema.json`` — columns, split sizes, a note that no image binaries ship
- ``stats.json``  — injection_type / risk_category / technique distribution,
  empty-image_text count, text-length buckets, non-ASCII (non-English) count
- ``sample_rows.jsonl`` — a few representative rows

Usage::

    python scripts/safety_v0/inspect/inspect_cyberseceval3_visual_prompt_injection.py
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

SLUG = "cyberseceval3_visual_prompt_injection"
_NON_ASCII = re.compile(r"[^\x00-\x7f]")


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
    techniques = Counter()
    for r in rows:
        for t in r.get("injection_technique", []) or []:
            techniques[t] += 1
    combined = [((r.get("user_input_text") or "") + (r.get("image_text") or "")) for r in rows]
    return {
        "rows": len(rows),
        "injection_type": dict(Counter(r.get("injection_type") for r in rows)),
        "risk_category": dict(Counter(r.get("risk_category") for r in rows)),
        "injection_technique": dict(techniques),
        "empty_image_text": sum(1 for r in rows if not (r.get("image_text") or "").strip()),
        "empty_user_input_text": sum(1 for r in rows if not (r.get("user_input_text") or "").strip()),
        "image_text_length": length_buckets([len(r.get("image_text") or "") for r in rows]),
        "user_input_length": length_buckets([len(r.get("user_input_text") or "") for r in rows]),
        "rows_with_non_ascii_text": sum(1 for t in combined if _NON_ASCII.search(t)),
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
            f"No raw JSONL under {args.raw_dir}. "
            "Run download_cyberseceval3_visual_prompt_injection.py first."
        )

    splits = {p.stem: load_split(p) for p in split_files}
    schema = {
        "repo_id": "facebook/cyberseceval3-visual-prompt-injection",
        "config": "visual_prompt_injection",
        "columns": {
            "id": "int64",
            "system_prompt": "string (app system prompt; may carry a secret)",
            "user_input_text": "string (benign-looking user question)",
            "image_description": "string (scene of the image)",
            "image_text": "string (text embedded in the image = the injection; may be empty)",
            "judge_question": "string (eval rubric)",
            "injection_technique": "list[string]",
            "injection_type": "string (direct|indirect)",
            "risk_category": "string (logic-violating|security-violating)",
        },
        "split_sizes": {name: len(rows) for name, rows in splits.items()},
        "note": "No image binaries ship; only the image's text + description.",
        "language": "English",
    }
    stats = {name: summarize(rows) for name, rows in splits.items()}

    write_json(args.out_dir / "schema.json", schema)
    write_json(args.out_dir / "stats.json", stats)

    first = next(iter(splits.values()))
    write_jsonl(args.out_dir / "sample_rows.jsonl", first[: args.sample_rows])

    print(f"Wrote inspection artifacts to {args.out_dir}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
