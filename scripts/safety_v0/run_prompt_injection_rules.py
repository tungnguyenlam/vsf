"""Prompt-injection rule stage for canonical safety_v0 rows.

Runs the deterministic rule-based prompt-injection detector
(``src/pipeline/PromptInjection``) over each row's ``input_text`` and
``ocr_text``, records the matched evidence as ``detections.prompt_injection_spans``
(``detector="rule"``), and fills the ``prompt_injection`` weak label ONLY where it
is currently unknown.

Provenance rule (matches DATA_PLAN label layering source -> api -> human):

    The rule detector is the weakest signal. It NEVER overrides a label that
    already carries a stronger provenance (e.g. ``source_gold``); it only writes
    ``prompt_injection`` (``label_source="rule"``) where the label is ``None``
    ("null means unknown"). It never touches ``action`` or the topic axes.

Existing prompt-injection spans (e.g. the whole-text ``source_gold`` span on
attack rows) are preserved; rule spans are appended with their own ``pi_rule_*``
ids so the two never collide.

When gold flags are present (``label_source.prompt_injection == "source_gold"``)
the script also prints precision/recall/F1 of the rule detector against them and
can persist the metrics with ``--metrics``. This is free (no LLM calls).

Default paths from the source registry::

    python scripts/safety_v0/run_prompt_injection_rules.py --slug deepset_prompt_injections
    # data/safety_v0/converted/<slug>/source_canonical.jsonl
    #   -> data/safety_v0/weak/<slug>/weak_labeled.jsonl

The detector (``--detector``) and thresholds (``--warn-threshold`` /
``--block-threshold``) are config flips. Override paths with ``--input`` /
``--output``. For image sources, pass the redacted-stage JSONL via ``--input``
so OCR text is already present.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import (  # noqa: E402
    new_prompt_injection_span,
    validate_row,
)
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    weak_path,
)
from src.pipeline.PromptInjection import get_prompt_injection_detector  # noqa: E402

# Texts we scan, in priority order. Each contributes spans with offsets into
# that text; we tag the span with the field so downstream consumers know the
# reference. Both are scanned because DATA_PLAN runs the detector "on input text
# and OCR text".
_TEXT_FIELDS = ("input_text", "ocr_text")


def detect_spans(detector, text: str, *, field: str, start_index: int) -> List[Dict[str, Any]]:
    """Build prompt_injection_spans from one text's rule matches.

    ``field`` records which content field the char offsets index into;
    ``start_index`` keeps span ids unique across the texts scanned for a row.
    """
    if not text or not text.strip():
        return []
    result = detector.detect(text)
    spans: List[Dict[str, Any]] = []
    for i, ev in enumerate(result.evidence, start=start_index):
        span = new_prompt_injection_span(
            f"pi_rule_{i:04d}",
            ev["category"],
            ev["start"],
            ev["end"],
            ev["text"],
            score=round(float(ev["weight"]), 4),
            box_ids=[],
            detector="rule",
        )
        span["field"] = field
        span["rule"] = ev["rule"]
        spans.append(span)
    return spans


def rule_flag(detector, row: Dict[str, Any]) -> bool:
    """True if the rule detector fires on any scanned text of the row."""
    content = row.get("content", {})
    for field in _TEXT_FIELDS:
        text = content.get(field) or ""
        if text.strip() and detector.detect(text).is_injection:
            return True
    return False


def label_prompt_injection_rules(detector, row: Dict[str, Any]) -> Dict[str, Any]:
    """Add rule spans + fill the weak ``prompt_injection`` label in place."""
    content = row.get("content", {})
    existing = list(row.get("detections", {}).get("prompt_injection_spans") or [])
    new_spans: List[Dict[str, Any]] = []
    cursor = 1
    fired = False
    for field in _TEXT_FIELDS:
        text = content.get(field) or ""
        spans = detect_spans(detector, text, field=field, start_index=cursor)
        if text.strip() and detector.detect(text).is_injection:
            fired = True
        cursor += len(spans)
        new_spans.extend(spans)

    row.setdefault("detections", {})["prompt_injection_spans"] = existing + new_spans

    # Weak label: only where currently unknown. Never override stronger
    # provenance (source_gold / api / human).
    labels = row.setdefault("labels", {})
    label_source = row.setdefault("label_source", {})
    if labels.get("prompt_injection") is None:
        labels["prompt_injection"] = bool(fired)
        label_source["prompt_injection"] = "rule"
    return row


def _gold_flag(row: Dict[str, Any]) -> Optional[bool]:
    """The source gold prompt_injection flag, or None when not gold-labelled."""
    if row.get("label_source", {}).get("prompt_injection") == "source_gold":
        value = row.get("labels", {}).get("prompt_injection")
        if isinstance(value, bool):
            return value
    return None


def evaluate(detector, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Precision/recall/F1 of the rule detector vs available gold flags."""
    tp = fp = fn = tn = 0
    scored = 0
    for row in rows:
        gold = _gold_flag(row)
        if gold is None:
            continue
        scored += 1
        pred = rule_flag(detector, row)
        if gold and pred:
            tp += 1
        elif gold and not pred:
            fn += 1
        elif not gold and pred:
            fp += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall
        else None
    )
    return {
        "rows_with_gold": scored,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rule-based prompt-injection stage over canonical rows.")
    parser.add_argument("--slug", help="Source slug for default input/output paths.")
    parser.add_argument("--input", help="Input JSONL (overrides --slug default).")
    parser.add_argument("--output", help="Output JSONL (overrides --slug default).")
    parser.add_argument(
        "--detector",
        default="rule_based_prompt_injection",
        help="Prompt-injection detector name from the registry.",
    )
    parser.add_argument("--warn-threshold", type=float, default=0.45)
    parser.add_argument("--block-threshold", type=float, default=0.75)
    parser.add_argument("--metrics", help="Optional path to write the gold evaluation JSON.")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.input:
        in_path = Path(args.input)
    elif args.slug:
        in_path = converted_path(args.slug)
    else:
        parser.error("provide --input or --slug")
    if args.output:
        out_path = Path(args.output)
    elif args.slug:
        out_path = weak_path(args.slug, create=True)
    else:
        parser.error("provide --output or --slug")

    if not in_path.exists():
        print(f"Input not found: {in_path}", file=sys.stderr)
        return 1

    detector = get_prompt_injection_detector(
        args.detector,
        warn_threshold=args.warn_threshold,
        block_threshold=args.block_threshold,
    )

    rows: List[Dict[str, Any]] = []
    with open(in_path, encoding="utf-8") as src:
        for line in src:
            line = line.strip()
            if not line:
                continue
            if args.limit is not None and len(rows) >= args.limit:
                break
            rows.append(json.loads(line))

    total = flagged = filled = invalid = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as dst:
        for row in rows:
            total += 1
            before = row.get("labels", {}).get("prompt_injection")
            row = label_prompt_injection_rules(detector, row)
            if rule_flag(detector, row):
                flagged += 1
            if before is None and row["labels"].get("prompt_injection") is not None:
                filled += 1
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid {row.get('input_id')}: {errors[0]}", file=sys.stderr)
                continue
            dst.write(json.dumps(row, ensure_ascii=False) + "\n")

    metrics = evaluate(detector, rows)
    print(
        f"Prompt-injection rules: {total} rows, {flagged} rule-flagged, "
        f"{filled} weak labels filled, {invalid} invalid -> {out_path}"
    )
    if metrics["rows_with_gold"]:
        print(
            "  vs gold: "
            f"n={metrics['rows_with_gold']} "
            f"P={metrics['precision']} R={metrics['recall']} F1={metrics['f1']} "
            f"(tp={metrics['tp']} fp={metrics['fp']} fn={metrics['fn']} tn={metrics['tn']})"
        )
    else:
        print("  vs gold: no source_gold prompt_injection flags in this file")

    if args.metrics:
        Path(args.metrics).parent.mkdir(parents=True, exist_ok=True)
        Path(args.metrics).write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
