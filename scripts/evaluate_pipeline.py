import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Evaluator import PIIEvaluator
from src.pipeline.BasePipeline import _DEFAULT_PREDICTION_LOG_PATH_SENTINEL
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
    parser.add_argument(
        "--log-path",
        default=None,
        help="JSONL log path. Defaults to output/predictions/<timestamp>/predictions.jsonl.",
    )
    parser.add_argument("--no-log", action="store_true", help="Disable JSONL prediction logging.")
    parser.add_argument("--include-source-text", action="store_true")
    parser.add_argument("--per-label", action="store_true", help="Include fine-grained label recall.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run an LLM adjudication pass over recognizer results (requires OPENROUTER_API_KEY).",
    )
    parser.add_argument(
        "--verify-model",
        default="deepseek/deepseek-v4-flash",
        help="OpenAI-compatible model id for the --verify adjudication pass (e.g. a DeepSeek or Qwen slug on OpenRouter).",
    )
    parser.add_argument(
        "--verify-effort",
        default=None,
        choices=["low", "medium", "high"],
        help="Optional reasoning effort for the --verify pass. Omit for non-reasoning flash models.",
    )
    parser.add_argument(
        "--verify-provider",
        default="require_parameters",
        help="OpenRouter provider routing for --verify. Default 'require_parameters' only routes "
        "to endpoints that support strict structured output. Use a provider slug such as "
        "'novita' to hard-pin for reproducible eval, or 'none' to let OpenRouter load-balance.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.no_log:
        log_path = None
    elif args.log_path is None:
        log_path = _DEFAULT_PREDICTION_LOG_PATH_SENTINEL
    else:
        log_path = Path(args.log_path)

    df_eval = load_evaluation_dataset(
        dataset_name=args.dataset,
        split=args.split,
        limit=args.limit,
    )
    verifier = None
    if args.verify:
        from src.pipeline.Verifiers import LLMVerifier

        provider_arg = args.verify_provider.lower()
        if provider_arg in ("none", "any", "off", ""):
            provider = None
        elif provider_arg in ("require_parameters", "required", "strict"):
            provider = {"require_parameters": True}
        else:
            provider = LLMVerifier.pin_provider(args.verify_provider)
        verifier = LLMVerifier(
            model=args.verify_model,
            effort=args.verify_effort,
            provider=provider,
            raise_on_error=True,
        )

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

    resolved_log_path = pipeline.prediction_log_path if pipeline.prediction_log_path is not None else None

    if args.per_label:
        overall, per_entity, per_label = evaluation
        output = {
            "pipeline": args.pipeline,
            "rows": len(df_eval),
            "split": args.split,
            "overall": overall,
            "per_entity": per_entity,
            "per_label": per_label,
            "log_path": str(resolved_log_path) if resolved_log_path else None,
        }
    else:
        overall, per_entity = evaluation
        output = {
            "pipeline": args.pipeline,
            "rows": len(df_eval),
            "split": args.split,
            "overall": overall,
            "per_entity": per_entity,
            "log_path": str(resolved_log_path) if resolved_log_path else None,
        }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
