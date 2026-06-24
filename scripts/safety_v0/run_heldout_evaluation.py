"""Reproduce the held-out generalization numbers cited in the writeup.

Runs the rule-based detector and the char-ngram Naive Bayes detector on
`deepset_vi` and `llmail_vi` from the on-disk translation cache (no LLM
spend) and writes the two JSON files under
`output/safety_v0/{deepset_vi,llmail_vi}/`. The numbers should match the
held-out table in `writeup/report.typ` and `writeup/report-vi.typ`.

Usage:
    PYTHONPATH=. python scripts/safety_v0/run_heldout_evaluation.py
"""

from __future__ import annotations

import json
from pathlib import Path

from src.pipeline.PromptInjection.Evaluation.PromptInjectionEvaluationConfig import (
    PromptInjectionEvaluationConfig,
)
from src.pipeline.PromptInjection.Evaluation.PromptInjectionEvaluationRunner import (
    PromptInjectionEvaluationRunner,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output" / "safety_v0"


def _run(config: PromptInjectionEvaluationConfig) -> dict:
    output = PromptInjectionEvaluationRunner(config).run()
    metrics = output["metrics"]
    counts = output["counts"]
    return {
        "detector": config.detector,
        "train": _train_label(config),
        "rows": output["rows"],
        "tp": counts["tp"],
        "fn": counts["fn"],
        "fp": counts["fp"],
        "tn": counts["tn"],
        "precision": metrics["precision"],
        "recall": metrics["recall"],
        "f1": metrics["f1"],
    }


def _train_label(config: PromptInjectionEvaluationConfig) -> str:
    if config.train_strategy == "external":
        return f"external:{config.train_dataset}"
    if config.train_strategy == "leave_one_out":
        return "leave-one-out (in-domain)"
    return "authored (none)"


def evaluate_deepset_vi() -> dict:
    eval_dir = OUTPUT_DIR / "deepset_vi"
    eval_dir.mkdir(parents=True, exist_ok=True)

    runs = [
        _run(
            PromptInjectionEvaluationConfig(
                dataset="deepset_vi",
                split="all",
                detector="rule_based_prompt_injection",
                train_strategy="none",
                no_log=True,
            )
        ),
        _run(
            PromptInjectionEvaluationConfig(
                dataset="deepset_vi",
                split="all",
                detector="char_ngram_prompt_injection",
                train_strategy="external",
                train_dataset="pi_vi_eval",
                no_log=True,
            )
        ),
        _run(
            PromptInjectionEvaluationConfig(
                dataset="deepset_vi",
                split="all",
                detector="char_ngram_prompt_injection",
                train_strategy="external",
                train_dataset="local_vietnamese_seed",
                no_log=True,
            )
        ),
        _run(
            PromptInjectionEvaluationConfig(
                dataset="deepset_vi",
                split="all",
                detector="char_ngram_prompt_injection",
                train_strategy="leave_one_out",
                no_log=True,
            )
        ),
    ]

    summary = {
        "dataset": "deepset_vi",
        "rows": 351,
        "attacks": 154,
        "benign": 197,
        "note": (
            "Held-out Vietnamese prompt-injection set: deepset/prompt-injections "
            "translated EN->VI via openrouter/openai/gpt-4o-mini. No LLM spend at "
            "reproduce time: translations are read from "
            "data/safety_v0/augmented/deepset_prompt_injections/augmented.jsonl."
        ),
        "runs": runs,
        "finding": (
            "Rules catch 10/154 unseen attacks (recall 0.065) at perfect precision; "
            "NB cross-source transfer is weak (F1 0.31-0.38); in-domain NB leave-one-out "
            "reaches F1 0.791. The data is learnable, so the production gap is a data "
            "problem, not a model ceiling."
        ),
    }
    output_path = eval_dir / "heldout_results.json"
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def evaluate_llmail_vi() -> dict:
    eval_dir = OUTPUT_DIR / "llmail_vi"
    eval_dir.mkdir(parents=True, exist_ok=True)

    runs = [
        _run(
            PromptInjectionEvaluationConfig(
                dataset="llmail_vi",
                split="all",
                detector="rule_based_prompt_injection",
                train_strategy="none",
                no_log=True,
            )
        ),
        _run(
            PromptInjectionEvaluationConfig(
                dataset="llmail_vi",
                split="all",
                detector="char_ngram_prompt_injection",
                train_strategy="external",
                train_dataset="pi_vi_eval",
                no_log=True,
            )
        ),
        _run(
            PromptInjectionEvaluationConfig(
                dataset="llmail_vi",
                split="all",
                detector="char_ngram_prompt_injection",
                train_strategy="external",
                train_dataset="deepset_vi",
                no_log=True,
            )
        ),
        _run(
            PromptInjectionEvaluationConfig(
                dataset="llmail_vi",
                split="all",
                detector="char_ngram_prompt_injection",
                train_strategy="external",
                train_dataset=(
                    "pi_vi_eval,local_vietnamese_seed,local_vietnamese_app_seed,"
                    "local_vietnamese_mentor_seed,deepset_vi"
                ),
                no_log=True,
            )
        ),
    ]
    # llmail is attack-only; reduce to recall rows to match the report table.
    transfer_runs = [
        {
            "detector": run["detector"],
            "train": run["train"],
            "recall": run["recall"],
            "tp": run["tp"],
            "fn": run["fn"],
        }
        for run in runs
    ]

    summary = {
        "dataset": "llmail_vi",
        "rows": 500,
        "attacks": 500,
        "benign": 0,
        "note": (
            "Second independent held-out Vietnamese attack source (translated "
            "llmail-inject, attack-only -> recall-only). Translation: "
            "openrouter/openai/gpt-4o-mini. No LLM spend at reproduce time: "
            "translations are read from "
            "data/safety_v0/augmented/llmail_inject_challenge/augmented.jsonl."
        ),
        "runs": transfer_runs,
        "finding": (
            "Recall climbs monotonically as the Vietnamese training pool grows "
            "(0.262 -> 0.364 -> 0.386); rules collapse to 0.026 on this novel "
            "source. Translation augmentation is the confirmed lever."
        ),
    }
    output_path = eval_dir / "transfer_results.json"
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def _print_table(label: str, runs: list[dict]) -> None:
    print(f"\n{label}")
    for run in runs:
        if "f1" in run:
            print(
                f"  {run['detector']:<32s} train={run['train']:<70s} "
                f"P={run['precision']:.3f} R={run['recall']:.3f} F1={run['f1']:.3f}"
            )
        else:
            print(
                f"  {run['detector']:<32s} train={run['train']:<70s} "
                f"R={run['recall']:.3f} (tp={run['tp']})"
            )


def main() -> None:
    deepset_summary = evaluate_deepset_vi()
    llmail_summary = evaluate_llmail_vi()

    _print_table("deepset_vi (351 rows: 154 attacks + 197 benigns)", deepset_summary["runs"])
    _print_table("llmail_vi (500 attacks, recall-only)", llmail_summary["runs"])
    print(f"\nWrote {OUTPUT_DIR / 'deepset_vi' / 'heldout_results.json'}")
    print(f"Wrote {OUTPUT_DIR / 'llmail_vi' / 'transfer_results.json'}")


if __name__ == "__main__":
    main()
