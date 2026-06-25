"""Bulk-clear the P1 "pii_spans detected but pii_visible not flipped" review gap.

These rows surface at the top of a review queue with priority P1 and the reason
``pii_spans detected but pii_visible is not true`` (see
``scripts/safety_v0/build_review_queue.py``). The detector already found image
PII text, so the only review action is to confirm ``pii_visible = true``. This
is the same edit a reviewer would make in the webdemo Annotate tab (toggle
``pii_visible`` and save); doing it here writes the identical human-override
records via ``webdemo.safety_v0_review.save_override`` rather than by hand.

Only ``pii_visible`` is set (the other labels keep their existing weak/router
provenance — saving does not silently re-stamp them as human). Each cleared row
is marked ``review.status = human_reviewed`` so it drops out of the queue count.

The pass is idempotent: a row already ``human_reviewed`` in the override file is
skipped, so re-running writes nothing new.

Usage::

    python scripts/safety_v0/clear_pii_gap_p1.py --slug unsafebench
    python scripts/safety_v0/clear_pii_gap_p1.py --slug unsafebench --dry-run
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import review_queue_path  # noqa: E402
from webdemo import safety_v0_review as review  # noqa: E402

PII_GAP_REASON = "pii_spans detected but pii_visible is not true"
DEFAULT_REVIEWER = "bulk-p1-pii-gap"


def is_pii_gap_row(row: dict) -> bool:
    """True if the row is the known P1 gap: PII spans found, pii_visible not yet true."""
    has_spans = bool((row.get("detections") or {}).get("pii_spans"))
    pii_visible = (row.get("labels") or {}).get("pii_visible")
    return has_spans and pii_visible is not True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", default="unsafebench", help="Source slug (default: unsafebench).")
    parser.add_argument("--input", help="Override queue JSONL (default: review/queue/<slug>.jsonl).")
    parser.add_argument("--reviewer", default=DEFAULT_REVIEWER, help="Reviewer id stamped on overrides.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing.")
    args = parser.parse_args(argv)

    queue_path = Path(args.input) if args.input else review_queue_path(args.slug)
    if not queue_path.exists():
        parser.error(f"queue not found: {queue_path}")

    # load_rows applies any existing overrides, so already-reviewed rows show
    # status human_reviewed and we skip them (idempotency).
    rows, _ = review.load_rows(queue_path)

    targets = []
    skipped_reviewed = 0
    for row in rows:
        if not is_pii_gap_row(row):
            continue
        if (row.get("review") or {}).get("status") == "human_reviewed":
            skipped_reviewed += 1
            continue
        targets.append(row["input_id"])

    print(f"Queue: {queue_path}")
    print(f"PII-gap rows still needing review: {len(targets)} (already reviewed: {skipped_reviewed})")

    if args.dry_run:
        for iid in targets:
            print(f"  would clear {iid} -> pii_visible=true, human_reviewed")
        return 0

    for iid in targets:
        review.save_override(
            queue_path,
            iid,
            {"pii_visible": True},
            {
                "status": "human_reviewed",
                "notes": "bulk-confirmed pii_visible from detected pii_spans (P1 gap)",
            },
            reviewer=args.reviewer,
        )
        print(f"  cleared {iid}")

    out_path = review.override_path_for(queue_path)
    try:
        out_path = out_path.relative_to(PROJECT_ROOT)
    except ValueError:
        pass
    print(f"Wrote {len(targets)} overrides to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
