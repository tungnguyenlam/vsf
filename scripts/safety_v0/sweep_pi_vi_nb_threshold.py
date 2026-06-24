"""Sweep the char-ngram NB decision threshold on the pi_vi_eval set.

The leave-one-out scores are computed once; thresholds are swept offline. This
answers whether NB's leave-one-out F1 (0.875 at the default 0.5 cut-off) can be
improved by trading off its false positives, without spending any LLM budget.

Usage:
    PYTHONPATH=. python scripts/safety_v0/sweep_pi_vi_nb_threshold.py
    PYTHONPATH=. python scripts/safety_v0/sweep_pi_vi_nb_threshold.py \
        --metrics output/safety_v0/pi_vi_eval/nb_threshold_sweep.json
"""

import argparse
import json
from pathlib import Path

from src.pipeline.PromptInjection import (
    PromptInjectionEvaluationConfig,
    PromptInjectionEvaluationRunner,
)


def _confusion(scores_labels, threshold):
    tp = fp = tn = fn = 0
    for score, label in scores_labels:
        predicted = score >= threshold
        if predicted and label:
            tp += 1
        elif predicted and not label:
            fp += 1
        elif not predicted and not label:
            tn += 1
        else:
            fn += 1
    return tp, fp, tn, fn


def _metrics(tp, fp, tn, fn):
    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / total if total else 0.0
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "accuracy": round(accuracy, 6),
    }


def sweep_thresholds(scores_labels, step: float = 0.05) -> list[dict]:
    """Return a list of {threshold, tp, fp, tn, fn, metrics} rows.

    Candidate thresholds are a regular grid (``step``) unioned with every observed
    score boundary, so the F1-optimal cut-off is not missed between grid points.
    """
    grid = [round(i * step, 4) for i in range(int(1 / step) + 1)]
    boundaries = sorted({round(s, 6) for s, _ in scores_labels})
    thresholds = sorted(set(grid) | set(boundaries))

    rows = []
    for threshold in thresholds:
        tp, fp, tn, fn = _confusion(scores_labels, threshold)
        rows.append(
            {
                "threshold": threshold,
                "tp": tp,
                "fp": fp,
                "tn": tn,
                "fn": fn,
                **_metrics(tp, fp, tn, fn),
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="pi_vi_eval")
    parser.add_argument("--detector", default="char_ngram_prompt_injection")
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--metrics", type=Path, default=None)
    args = parser.parse_args()

    runner = PromptInjectionEvaluationRunner(
        PromptInjectionEvaluationConfig(
            dataset=args.dataset,
            detector=args.detector,
            train_strategy="leave_one_out",
            no_log=True,
        )
    )
    output = runner.run()
    scores_labels = [(d["score"], int(d["label"])) for d in output["decisions"]]

    rows = sweep_thresholds(scores_labels, step=args.step)
    best = max(rows, key=lambda r: (r["f1"], r["precision"]))
    default = next((r for r in rows if abs(r["threshold"] - 0.5) < 1e-9), None)

    print(f"dataset={args.dataset} detector={args.detector} rows={output['rows']}")
    print(f"{'thresh':>7} {'P':>7} {'R':>7} {'F1':>7} {'tp':>4} {'fp':>4} {'fn':>4} {'tn':>4}")
    for r in rows:
        mark = ""
        if r is best:
            mark += " <-best F1"
        if r is default:
            mark += " <-default(0.5)"
        print(
            f"{r['threshold']:>7.3f} {r['precision']:>7.3f} {r['recall']:>7.3f} "
            f"{r['f1']:>7.3f} {r['tp']:>4} {r['fp']:>4} {r['fn']:>4} {r['tn']:>4}{mark}"
        )

    print("\nBest F1:", json.dumps(best))
    if default is not None:
        print("Default (0.5):", json.dumps(default))

    if args.metrics is not None:
        args.metrics.parent.mkdir(parents=True, exist_ok=True)
        args.metrics.write_text(
            json.dumps(
                {
                    "dataset": args.dataset,
                    "detector": args.detector,
                    "rows": output["rows"],
                    "default_threshold": default,
                    "best_f1_threshold": best,
                    "sweep": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nWrote {args.metrics}")


if __name__ == "__main__":
    main()
