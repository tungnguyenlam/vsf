"""Validate `safety_v0` JSONL files against the canonical schema.

Runs ``validate_row`` over every line of one or more JSONL files (converted,
weak-labeled, verified, or final). Prints per-file pass/fail counts and the
first few errors, and exits non-zero if any row is invalid — suitable for use
after every converter or build stage.

Usage::

    python scripts/safety_v0/validate_safety_v0.py data/safety_v0/converted/existing_repo_pii/source_canonical.jsonl
    python scripts/safety_v0/validate_safety_v0.py data/safety_v0/converted/*/source_canonical.jsonl
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import validate_row  # noqa: E402


def validate_file(path: Path, max_errors: int = 10) -> tuple:
    """Return (total, valid, invalid) and print the first ``max_errors`` problems."""
    total = valid = invalid = 0
    shown = 0
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                invalid += 1
                if shown < max_errors:
                    print(f"  {path}:{line_no} JSON error: {exc}", file=sys.stderr)
                    shown += 1
                continue
            errors = validate_row(row)
            if errors:
                invalid += 1
                if shown < max_errors:
                    rid = row.get("input_id", "?")
                    print(f"  {path}:{line_no} [{rid}] {errors[0]}", file=sys.stderr)
                    shown += 1
            else:
                valid += 1
    return total, valid, invalid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--max-errors", type=int, default=10)
    args = parser.parse_args()

    any_invalid = False
    for path in args.paths:
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            any_invalid = True
            continue
        total, valid, invalid = validate_file(path, max_errors=args.max_errors)
        status = "OK" if invalid == 0 else "FAIL"
        print(f"[{status}] {path}: {valid}/{total} valid, {invalid} invalid")
        any_invalid = any_invalid or invalid > 0

    return 1 if any_invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
