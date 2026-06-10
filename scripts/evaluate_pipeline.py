import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Evaluator import PIIEvaluator
from src.pipeline.Pipelines import get_pipeline, list_pipeline_names
from src.pipeline.Utils import DEFAULT_DATASET_NAME, load_evaluation_dataset


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate a Vietnamese PII pipeline.")
    parser.add_argument(
        "--pipeline",
        default="regex_only",
        choices=list_pipeline_names(),
        help="Pipeline variant to evaluate.",
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET_NAME)
    parser.add_argument("--split", default="train", help="Dataset split: train, val, test, or all.")
    parser.add_argument("--limit", type=int, default=None, help="Rows to sample per selected split.")
    parser.add_argument("--score-threshold", type=float, default=0.0)
    parser.add_argument("--log-path", default=str(PROJECT_ROOT / "output" / "predictions.jsonl"))
    parser.add_argument("--no-log", action="store_true", help="Disable JSONL prediction logging.")
    parser.add_argument("--include-source-text", action="store_true")
    parser.add_argument("--per-label", action="store_true", help="Include fine-grained label recall.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run an LLM adjudication pass over recognizer results (requires ANTHROPIC_API_KEY).",
    )
    parser.add_argument(
        "--verify-model",
        default="claude-opus-4-8",
        help="Claude model id for the --verify adjudication pass.",
    )
    parser.add_argument(
        "--verify-effort",
        default="low",
        choices=["low", "medium", "high", "max"],
        help="Effort level for the --verify adjudication pass.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    log_path = None if args.no_log else Path(args.log_path)

    df_eval = load_evaluation_dataset(
        dataset_name=args.dataset,
        split=args.split,
        limit=args.limit,
    )
    verifier = None
    if args.verify:
        from src.pipeline.Verifiers import LLMVerifier

        verifier = LLMVerifier(model=args.verify_model, effort=args.verify_effort)

    pipeline = get_pipeline(
        args.pipeline,
        prediction_log_path=log_path,
        include_source_text=args.include_source_text,
        default_score_threshold=args.score_threshold,
        verifier=verifier,
    )

    evaluator = PIIEvaluator()
    evaluation = evaluator.evaluate_presidio(
        df_eval,
        pipeline,
        language="vi",
        score_threshold=args.score_threshold,
        use_type_mapping=True,
        return_per_entity=True,
        return_per_label=args.per_label,
    )

    if args.per_label:
        overall, per_entity, per_label = evaluation
        output = {
            "pipeline": args.pipeline,
            "rows": len(df_eval),
            "split": args.split,
            "overall": overall,
            "per_entity": per_entity,
            "per_label": per_label,
            "log_path": str(log_path) if log_path else None,
        }
    else:
        overall, per_entity = evaluation
        output = {
            "pipeline": args.pipeline,
            "rows": len(df_eval),
            "split": args.split,
            "overall": overall,
            "per_entity": per_entity,
            "log_path": str(log_path) if log_path else None,
        }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
