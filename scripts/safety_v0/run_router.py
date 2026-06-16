"""Batch safety-router stage (PAID) + fallback queue.

Routes canonical rows through the shared VLM safety router and writes the
decisions as an API-label layer, plus a fallback queue of rows that need human
review. It does NOT mutate the source rows or write final labels — the router
output is a provenance layer (``label_source="api"``) that the Annotate tab
shows beneath any human override.

Default paths from the source registry::

    python scripts/safety_v0/run_router.py --slug webpii --limit 50
    # in:    data/safety_v0/redacted/webpii/redacted.jsonl
    # out:   data/safety_v0/review/api_labels/webpii.jsonl   (one record/row)
    # queue: data/safety_v0/review/queue/webpii.jsonl        (unsure/invalid rows)

COST DISCIPLINE (see CLAUDE.md): this spends paid budget — one model call per
row. ``--limit`` is REQUIRED unless ``--all`` is passed, so a full run is never
accidental. Start with 50 for a smoke check.

Fallback policy: rows whose action is ``unsure`` OR whose output failed
validation are appended to the queue with a reason, so they surface for human
annotation. ``safe``/``reject`` rows are recorded but not queued.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import LABEL_FIELDS  # noqa: E402
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    api_labels_dir,
    get_source,
    redacted_path,
    review_queue_dir,
)
from src.pipeline.Router import build_router_input, get_router  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def api_label_record(input_id: str, result, router_name: str) -> Dict[str, Any]:
    """Build the API-label layer record for one routed row.

    Mirrors the human-override record shape so the review tool can apply it the
    same way: known labels get ``label_source="api"``, unknowns stay ``None``.
    Unsure/invalid results are marked ``needs_review`` so they surface in the UI.
    """
    labels = result.to_labels()
    label_source = {f: ("api" if labels.get(f) is not None else None) for f in LABEL_FIELDS}
    status = "needs_review" if (result.action == "unsure" or not result.valid) else "unreviewed"
    return {
        "input_id": input_id,
        "labels": labels,
        "label_source": label_source,
        "review": {"status": status, "reviewer": f"router:{router_name}", "notes": result.error or ""},
        "router": {"name": router_name, "valid": result.valid, "action": result.action,
                   "error": result.error},
        "timestamp": _now(),
    }


def queue_record(input_id: str, source_file: str, result) -> Dict[str, Any]:
    reason = "router_unsure" if result.action == "unsure" else "router_invalid_output"
    return {
        "input_id": input_id,
        "source_file": source_file,
        "reason": reason,
        "router_action": result.action,
        "router_error": result.error,
        "timestamp": _now(),
    }


def route_rows(
    rows: List[Dict[str, Any]],
    router,
    router_name: str,
    source_file: str,
    *,
    limit: Optional[int] = None,
):
    """Yield ``(api_record, queue_record_or_None, result)`` per routed row."""
    count = 0
    for row in rows:
        if limit is not None and count >= limit:
            break
        count += 1
        iid = row.get("input_id")
        result = router.route(build_router_input(row))
        api_rec = api_label_record(iid, result, router_name)
        q_rec = None
        if result.action == "unsure" or not result.valid:
            q_rec = queue_record(iid, source_file, result)
        yield api_rec, q_rec, result


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch VLM safety router (paid) + fallback queue.")
    parser.add_argument("--slug", help="Source slug for default input/output paths.")
    parser.add_argument("--input", help="Input JSONL of canonical rows (overrides --slug).")
    parser.add_argument("--api-labels-out", help="API-label JSONL output (overrides --slug).")
    parser.add_argument("--queue-out", help="Fallback queue JSONL output (overrides --slug).")
    parser.add_argument("--router", default="gemini_flash", help="Router name.")
    parser.add_argument("--limit", type=int, default=None, help="Route at most N rows (paid).")
    parser.add_argument("--all", action="store_true", help="Route every row (paid; explicit).")
    args = parser.parse_args()

    if args.limit is None and not args.all:
        parser.error("refusing to run unbounded paid routing: pass --limit N (or --all).")

    if args.input:
        in_path = Path(args.input)
        source_file = args.input
    elif args.slug:
        in_path = redacted_path(args.slug)
        source_file = str(in_path)
    else:
        parser.error("provide --input or --slug")

    if args.api_labels_out:
        api_out = Path(args.api_labels_out)
    elif args.slug:
        get_source(args.slug)
        api_out = api_labels_dir(create=True) / f"{args.slug}.jsonl"
    else:
        parser.error("provide --api-labels-out or --slug")

    if args.queue_out:
        queue_out = Path(args.queue_out)
    elif args.slug:
        queue_out = review_queue_dir(create=True) / f"{args.slug}.jsonl"
    else:
        parser.error("provide --queue-out or --slug")

    if not in_path.exists():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1

    rows = [json.loads(line) for line in in_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    router = get_router(args.router)
    api_out.parent.mkdir(parents=True, exist_ok=True)
    queue_out.parent.mkdir(parents=True, exist_ok=True)

    counts = {"routed": 0, "safe": 0, "reject": 0, "unsure": 0, "invalid": 0, "queued": 0}
    with open(api_out, "w", encoding="utf-8") as api_f, open(queue_out, "w", encoding="utf-8") as q_f:
        for api_rec, q_rec, result in route_rows(
            rows, router, args.router, source_file, limit=args.limit
        ):
            api_f.write(json.dumps(api_rec, ensure_ascii=False) + "\n")
            counts["routed"] += 1
            counts[result.action] = counts.get(result.action, 0) + 1
            if not result.valid:
                counts["invalid"] += 1
            if q_rec is not None:
                q_f.write(json.dumps(q_rec, ensure_ascii=False) + "\n")
                counts["queued"] += 1

    print(
        f"Routed {counts['routed']} rows -> {api_out}\n"
        f"  safe={counts['safe']} reject={counts['reject']} unsure={counts['unsure']} "
        f"invalid={counts['invalid']}\n"
        f"  queued {counts['queued']} for review -> {queue_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
