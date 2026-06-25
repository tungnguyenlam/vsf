"""Select uncertain / conflicting / incomplete rows for human review.

Reads a source's weak-labeled rows (the output of the OCR -> PII -> prompt-
injection -> visual/topic weak-label chain) and writes the subset that a human
should look at to ``data/safety_v0/review/queue/<slug>.jsonl``.

The selection criteria are the DATA_PLAN "Priority for review" list, in order:

1. rows with conflicting source/pipeline labels
2. rows with ``action`` == null
3. rows where visual datasets have unclear label mapping
4. rows with detected PII boxes after redaction
5. prompt-injection hard negatives

A row is queued if ANY selector fires; its queue ``priority`` is the rank of the
highest-priority (lowest-number) selector that matched, and every matched reason
is recorded in ``review.notes`` so the reviewer knows why it surfaced. Queued
rows stay schema-valid: only ``review.status`` (-> ``needs_review``) and
``review.notes`` change, so the webdemo and the final build can read them as-is.

The selectors are source-agnostic (they read only the canonical row), so the
same script serves every source. Pass ``--slug`` to resolve standard paths, or
``--input``/``--output`` to point at arbitrary files (used by the tests).

Usage::

    python scripts/safety_v0/build_review_queue.py --slug unsafebench
    python scripts/safety_v0/build_review_queue.py --slug unsafebench --limit 200
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import RISK_FIELDS, validate_row  # noqa: E402
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    get_source,
    review_queue_path,
    weak_path,
)

# Visual axes whose meaning a human can confirm from the image alone.
_VISUAL_FIELDS = ("sexual", "violence", "blood_gore")


def _spans(row: Dict[str, Any], key: str) -> List[Any]:
    return row.get("detections", {}).get(key) or []


def selection_reasons(row: Dict[str, Any], *, has_images: bool) -> List[Tuple[int, str]]:
    """Return ``(priority_rank, reason)`` pairs for every selector that fired.

    Rank follows the DATA_PLAN "Priority for review" order (1 = highest). A row
    with no pairs is not queued.
    """
    labels = row.get("labels", {})
    action = labels.get("action")
    reasons: List[Tuple[int, str]] = []

    # 1. Conflicting source/pipeline labels: a detector fired but the matching
    #    label does not reflect it, or a "safe" action coexists with a risk.
    if _spans(row, "pii_spans") and labels.get("pii_visible") is not True:
        reasons.append((1, "pii_spans detected but pii_visible is not true"))
    if _spans(row, "prompt_injection_spans") and labels.get("prompt_injection") is not True:
        reasons.append((1, "prompt_injection_spans detected but prompt_injection is not true"))
    if action == "safe":
        risky = [f for f in RISK_FIELDS if labels.get(f) is True]
        if risky:
            reasons.append((1, f"action=safe but risk labels true: {', '.join(risky)}"))

    # 2. action is unknown -> a human must decide accept/reject.
    if action is None:
        reasons.append((2, "action is null"))

    # 3. Unclear visual mapping: an image row we reject without knowing which
    #    visual axis fired (all visual axes still null).
    if has_images and action == "reject" and all(
        labels.get(f) is None for f in _VISUAL_FIELDS
    ):
        reasons.append((3, "image rejected but all visual axes are null"))

    # 4. PII still detected after the redaction stage ran.
    if row.get("detections", {}).get("redaction_metadata"):
        reasons.append((4, "redaction_metadata present (PII detected in image text)"))

    # 5. Prompt-injection hard negatives: OCR text is present and a PI span was
    #    detected, yet the row is labeled not-injection (a candidate the rules
    #    flagged but we kept negative).
    if (
        labels.get("prompt_injection") is False
        and _spans(row, "prompt_injection_spans")
    ):
        reasons.append((5, "prompt-injection hard negative (span detected, label false)"))

    return reasons


def build_queue(
    rows: List[Dict[str, Any]],
    *,
    has_images: bool,
    limit: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Select review rows, sorted by priority then input_id, capped at ``limit``.

    Returns the queued rows (schema-shaped, ``review`` updated) and a stats dict
    with per-reason counts plus ``selected``/``total``/``dropped_by_limit``.
    """
    selected: List[Tuple[int, str, Dict[str, Any], List[str]]] = []
    reason_counts: Dict[str, int] = {}
    for row in rows:
        pairs = selection_reasons(row, has_images=has_images)
        if not pairs:
            continue
        pairs.sort(key=lambda p: p[0])
        top_rank = pairs[0][0]
        notes = [r for _, r in pairs]
        for note in notes:
            reason_counts[note] = reason_counts.get(note, 0) + 1
        selected.append((top_rank, row.get("input_id", ""), row, notes))

    selected.sort(key=lambda s: (s[0], s[1]))
    capped = selected if limit is None else selected[:limit]

    queued: List[Dict[str, Any]] = []
    for rank, _id, row, notes in capped:
        review = dict(row.get("review") or {})
        review["status"] = "needs_review"
        review["notes"] = f"auto-queued P{rank}: " + "; ".join(notes)
        out = dict(row)
        out["review"] = review
        queued.append(out)

    stats = {
        "total": len(rows),
        "selected": len(selected),
        "queued": len(queued),
        "dropped_by_limit": len(selected) - len(queued),
    }
    stats.update({f"reason::{k}": v for k, v in sorted(reason_counts.items())})
    return queued, stats


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", help="Source slug (resolves standard in/out paths).")
    parser.add_argument("--input", help="Override input JSONL (default: weak_labeled.jsonl).")
    parser.add_argument("--output", help="Override output JSONL (default: review/queue/<slug>.jsonl).")
    parser.add_argument("--limit", type=int, default=None, help="Cap the queue size (default: no cap).")
    parser.add_argument(
        "--has-images",
        choices=("auto", "true", "false"),
        default="auto",
        help="Whether rows carry images (default: from the source registry).",
    )
    args = parser.parse_args(argv)

    if not args.slug and not (args.input and args.output):
        parser.error("provide --slug, or both --input and --output")

    in_path = Path(args.input) if args.input else weak_path(args.slug)
    out_path = Path(args.output) if args.output else review_queue_path(args.slug, create=True)

    if args.has_images == "auto":
        has_images = get_source(args.slug).has_images if args.slug else True
    else:
        has_images = args.has_images == "true"

    if not in_path.exists():
        parser.error(f"input not found: {in_path}")

    rows = _read_jsonl(in_path)
    queued, stats = build_queue(rows, has_images=has_images, limit=args.limit)

    invalid = sum(1 for r in queued if validate_row(r))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for row in queued:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Read {stats['total']} rows from {in_path}")
    print(f"Selected {stats['selected']} for review; wrote {stats['queued']} to {out_path}")
    if stats["dropped_by_limit"]:
        print(f"Dropped {stats['dropped_by_limit']} over --limit {args.limit}")
    for key, val in stats.items():
        if key.startswith("reason::"):
            print(f"  {key[len('reason::'):]}: {val}")
    if invalid:
        print(f"WARNING: {invalid} queued rows failed schema validation")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
