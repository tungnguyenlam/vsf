"""Build a balanced Vietnamese prompt-injection evaluation set.

The attack-only seeds could measure rule *precision* on attacks and recall, but
never precision/recall *together* on realistic Vietnamese text. This script
assembles one curated eval set so the rule detector (and any later learned
detector) can be scored on precision AND recall at once, and so the deferred
``secret_or_data_exfiltration`` refinement can be validated against real negatives
instead of guesswork.

Ground-truth source (all Vietnamese):

- Positives: the ``local_vi_prompt_injection`` gold attacks
  (``label_source.prompt_injection == "source_gold"`` and ``True``).
- Negatives: the ``local_vi_prompt_injection`` gold benigns (hard negatives that
  *discuss* security/jailbreaks without performing an attack) PLUS a bounded,
  deterministic sample of ``vihsd_topic_safety`` comments (real Vietnamese
  social-media text, none of them prompt injections).

Each emitted row is a valid canonical ``safety_v0`` row with an extra top-level
``eval`` block recording the ground truth and where it came from::

    "eval": {"label": bool, "bucket": "attack"|"benign_seed"|"benign_vihsd",
             "gold": bool}

``gold`` is true when the label has ``source_gold`` provenance (the local seeds)
and false for the vihsd negatives, which are ``source_assumption`` (not a PI
dataset, hence trustworthy negatives but not hand-verified per row).

By default the set is balanced: every local attack is kept, all local benigns are
kept, and just enough vihsd negatives are added to match the positive count.
Sampling is deterministic (``--seed``, default 42) for repeatability. Increase
``--vihsd-negatives`` for a more realistic (negative-heavy) false-positive
estimate; that is a single flag, not a code change.

Usage::

    python scripts/safety_v0/build_pi_vi_eval.py
    python scripts/safety_v0/build_pi_vi_eval.py --vihsd-negatives 500
"""

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import validate_row  # noqa: E402
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    pi_vi_eval_path,
    weak_path,
)

LOCAL_SLUG = "local_vi_prompt_injection"
VIHSD_SLUG = "vihsd_topic_safety"


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as src:
        for line in src:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _gold_pi(row: Dict[str, Any]) -> Optional[bool]:
    """The gold prompt_injection flag, or None when not source_gold."""
    if row.get("label_source", {}).get("prompt_injection") == "source_gold":
        value = row.get("labels", {}).get("prompt_injection")
        if isinstance(value, bool):
            return value
    return None


def _tag(row: Dict[str, Any], *, label: bool, bucket: str, gold: bool) -> Dict[str, Any]:
    """Return a copy of the row carrying the eval ground-truth block."""
    out = json.loads(json.dumps(row, ensure_ascii=False))
    out["eval"] = {"label": bool(label), "bucket": bucket, "gold": bool(gold)}
    return out


def select_rows(
    local_rows: List[Dict[str, Any]],
    vihsd_rows: List[Dict[str, Any]],
    *,
    vihsd_negatives: Optional[int],
    seed: int,
) -> List[Dict[str, Any]]:
    """Assemble the balanced eval rows from the two sources.

    ``vihsd_negatives=None`` means "balance": add just enough vihsd negatives so
    the negative count matches the positive count.
    """
    positives = [r for r in local_rows if _gold_pi(r) is True]
    benign_seed = [r for r in local_rows if _gold_pi(r) is False]

    if vihsd_negatives is None:
        needed = max(0, len(positives) - len(benign_seed))
    else:
        needed = vihsd_negatives

    # Only real negatives: vihsd rows whose weak prompt_injection label is False.
    vihsd_negs = [r for r in vihsd_rows if r.get("labels", {}).get("prompt_injection") is False]
    rng = random.Random(seed)
    rng.shuffle(vihsd_negs)
    vihsd_pick = vihsd_negs[:needed]

    rows: List[Dict[str, Any]] = []
    rows += [_tag(r, label=True, bucket="attack", gold=True) for r in positives]
    rows += [_tag(r, label=False, bucket="benign_seed", gold=True) for r in benign_seed]
    rows += [_tag(r, label=False, bucket="benign_vihsd", gold=False) for r in vihsd_pick]
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the balanced Vietnamese PI eval set.")
    parser.add_argument(
        "--local-input",
        help="local_vi converted JSONL (default: converted/local_vi_prompt_injection).",
    )
    parser.add_argument(
        "--vihsd-input",
        help="vihsd weak-labeled JSONL (default: weak/vihsd_topic_safety).",
    )
    parser.add_argument("--output", help="Output JSONL (default: eval/pi_vi/eval.jsonl).")
    parser.add_argument(
        "--vihsd-negatives",
        type=int,
        default=None,
        help="How many vihsd negatives to add. Default: balance against positives.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Deterministic sampling seed.")
    args = parser.parse_args()

    local_path = Path(args.local_input) if args.local_input else converted_path(LOCAL_SLUG)
    vihsd_path = Path(args.vihsd_input) if args.vihsd_input else weak_path(VIHSD_SLUG)
    out_path = Path(args.output) if args.output else pi_vi_eval_path(create=True)

    for path in (local_path, vihsd_path):
        if not path.exists():
            print(f"Input not found: {path}", file=sys.stderr)
            return 1

    local_rows = _read_jsonl(local_path)
    vihsd_rows = _read_jsonl(vihsd_path)
    rows = select_rows(
        local_rows,
        vihsd_rows,
        vihsd_negatives=args.vihsd_negatives,
        seed=args.seed,
    )

    invalid = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as dst:
        for row in rows:
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid {row.get('input_id')}: {errors[0]}", file=sys.stderr)
                continue
            dst.write(json.dumps(row, ensure_ascii=False) + "\n")

    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["eval"]["bucket"]] = counts.get(row["eval"]["bucket"], 0) + 1
    pos = sum(1 for r in rows if r["eval"]["label"])
    neg = len(rows) - pos
    print(
        f"PI VI eval set: {len(rows)} rows ({pos} positive / {neg} negative), "
        f"{invalid} invalid -> {out_path}"
    )
    print(f"  buckets: {counts}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
