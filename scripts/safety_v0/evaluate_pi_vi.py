"""Evaluate a prompt-injection detector on the balanced Vietnamese eval set.

Reads the curated eval JSONL (``build_pi_vi_eval.py``), runs a registry detector
over each row's ``input_text`` (these rows are text-only), and reports accuracy,
precision, recall, F1 and the confusion matrix against the per-row ``eval.label``
ground truth. Unlike the weak-label stage's gold-only metric, this scores the
vihsd negatives too, so precision is measured against realistic Vietnamese text.

The detector (``--detector``) and thresholds are config flips, matching the
weak-label stage. Misclassified rows (false positives / false negatives) are
printed and can be saved with ``--errors`` for rule iteration.

Usage::

    python scripts/safety_v0/evaluate_pi_vi.py
    python scripts/safety_v0/evaluate_pi_vi.py --errors output/pi_vi_errors.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_sources import pi_vi_eval_path  # noqa: E402
from src.pipeline.PromptInjection import get_prompt_injection_detector  # noqa: E402

_TEXT_FIELDS = ("input_text", "ocr_text")


def predict(detector, row: Dict[str, Any]) -> bool:
    """True if the detector fires on any scanned text of the row."""
    content = row.get("content", {})
    for field in _TEXT_FIELDS:
        text = content.get(field) or ""
        if text.strip() and detector.detect(text).is_injection:
            return True
    return False


def evaluate(detector, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Confusion + P/R/F1 overall and per bucket against ``eval.label``."""
    tp = fp = fn = tn = 0
    per_bucket: Dict[str, Dict[str, int]] = {}
    errors: List[Dict[str, Any]] = []
    for row in rows:
        gold = bool(row["eval"]["label"])
        bucket = row["eval"]["bucket"]
        pred = predict(detector, row)
        b = per_bucket.setdefault(bucket, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        if gold and pred:
            tp += 1
            b["tp"] += 1
        elif gold and not pred:
            fn += 1
            b["fn"] += 1
            errors.append(_error_record(row, "false_negative", detector))
        elif not gold and pred:
            fp += 1
            b["fp"] += 1
            errors.append(_error_record(row, "false_positive", detector))
        else:
            tn += 1
            b["tn"] += 1

    return {
        "n": len(rows),
        **_scores(tp, fp, fn, tn),
        "per_bucket": {k: _scores(**v) for k, v in sorted(per_bucket.items())},
        "errors": errors,
    }


def _scores(tp: int, fp: int, fn: int, tn: int) -> Dict[str, Any]:
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision and recall
        else None
    )
    accuracy = (tp + tn) / total if total else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
    }


def _error_record(row: Dict[str, Any], kind: str, detector) -> Dict[str, Any]:
    text = row.get("content", {}).get("input_text") or ""
    result = detector.detect(text) if text.strip() else None
    return {
        "input_id": row.get("input_id"),
        "kind": kind,
        "bucket": row["eval"]["bucket"],
        "text": text,
        "score": round(float(result.score), 4) if result else None,
        "matched_rules": list(result.matched_rules) if result else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a detector on the Vietnamese PI eval set.")
    parser.add_argument("--input", help="Eval JSONL (default: eval/pi_vi/eval.jsonl).")
    parser.add_argument(
        "--detector",
        default="rule_based_prompt_injection",
        help="Prompt-injection detector name from the registry.",
    )
    parser.add_argument("--warn-threshold", type=float, default=0.45)
    parser.add_argument("--block-threshold", type=float, default=0.75)
    parser.add_argument("--errors", help="Optional path to write misclassified rows as JSON.")
    parser.add_argument("--metrics", help="Optional path to write the metrics JSON.")
    args = parser.parse_args()

    in_path = Path(args.input) if args.input else pi_vi_eval_path()
    if not in_path.exists():
        print(f"Input not found: {in_path} (run build_pi_vi_eval.py first)", file=sys.stderr)
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
            if line:
                rows.append(json.loads(line))

    metrics = evaluate(detector, rows)
    print(
        f"PI VI eval ({args.detector}): n={metrics['n']} "
        f"acc={metrics['accuracy']} P={metrics['precision']} "
        f"R={metrics['recall']} F1={metrics['f1']} "
        f"(tp={metrics['tp']} fp={metrics['fp']} fn={metrics['fn']} tn={metrics['tn']})"
    )
    for bucket, s in metrics["per_bucket"].items():
        print(
            f"  {bucket}: n={s['tp'] + s['fp'] + s['fn'] + s['tn']} "
            f"tp={s['tp']} fp={s['fp']} fn={s['fn']} tn={s['tn']}"
        )

    fps = [e for e in metrics["errors"] if e["kind"] == "false_positive"]
    fns = [e for e in metrics["errors"] if e["kind"] == "false_negative"]
    if fps:
        print(f"\n  false positives ({len(fps)}):")
        for e in fps[:20]:
            print(f"    [{e['bucket']}] {e['input_id']} score={e['score']} "
                  f"rules={e['matched_rules']} :: {e['text'][:90]}")
    if fns:
        print(f"\n  false negatives ({len(fns)}):")
        for e in fns[:20]:
            print(f"    [{e['bucket']}] {e['input_id']} score={e['score']} :: {e['text'][:90]}")

    if args.errors:
        Path(args.errors).parent.mkdir(parents=True, exist_ok=True)
        Path(args.errors).write_text(
            json.dumps(metrics["errors"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.metrics:
        payload = {k: v for k, v in metrics.items() if k != "errors"}
        Path(args.metrics).parent.mkdir(parents=True, exist_ok=True)
        Path(args.metrics).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
