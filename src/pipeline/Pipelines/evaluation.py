import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.pipeline.BasePipeline import _DEFAULT_PREDICTION_LOG_PATH_SENTINEL
from src.pipeline.Datasets import get_dataset, list_dataset_names
from src.pipeline.Evaluator import PIIEvaluator
from src.pipeline.Pipelines.registry import get_pipeline, list_pipeline_names
from src.pipeline.Utils import DEFAULT_DATASET_NAME, load_evaluation_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class PipelineEvaluationConfig:
    pipeline: str = "regex_only"
    dataset: str = DEFAULT_DATASET_NAME
    split: str = "train"
    limit: Optional[int] = None
    score_threshold: float = 0.0
    log_path: Optional[Path] = None
    no_log: bool = False
    include_source_text: bool = False
    per_label: bool = False
    verify: bool = False
    verify_model: str = "deepseek/deepseek-v4-flash"
    verify_effort: Optional[str] = None
    verify_provider: str = "require_parameters"
    env_path: Optional[Path] = None

    @classmethod
    def from_args(cls, args):
        return cls(
            pipeline=args.pipeline,
            dataset=args.dataset,
            split=args.split,
            limit=args.limit,
            score_threshold=args.score_threshold,
            log_path=Path(args.log_path) if args.log_path is not None else None,
            no_log=args.no_log,
            include_source_text=args.include_source_text,
            per_label=args.per_label,
            verify=args.verify,
            verify_model=args.verify_model,
            verify_effort=args.verify_effort,
            verify_provider=args.verify_provider,
        )


def load_local_env(env_path: Path = None):
    """Load local .env values without requiring the caller to source the shell."""
    env_path = env_path or PROJECT_ROOT / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
        return
    except ImportError:
        pass

    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def create_arg_parser():
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
        help="OpenAI-compatible model id for the --verify adjudication pass.",
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
    return parser


def parse_verify_provider(provider_arg: str):
    from src.pipeline.Verifiers import LLMVerifier

    normalized = provider_arg.lower()
    if normalized in ("none", "any", "off", ""):
        return None
    if normalized in ("require_parameters", "required", "strict"):
        return {"require_parameters": True}
    return LLMVerifier.pin_provider(provider_arg)


class PipelineEvaluationRunner:
    def __init__(self, config: PipelineEvaluationConfig):
        self.config = config
        self.dataset = None

    def run(self) -> dict:
        load_local_env(self.config.env_path)
        df_eval = self._load_dataset()
        pipeline = self._build_pipeline()
        label_to_presidio = (
            self.dataset.label_to_presidio if self.dataset is not None else None
        )
        evaluation = PIIEvaluator(label_to_presidio).evaluate_presidio(
            df_eval,
            pipeline,
            language="vi",
            score_threshold=self.config.score_threshold,
            use_type_mapping=True,
            return_per_entity=True,
            return_per_label=self.config.per_label,
        )
        return self._format_output(evaluation, rows=len(df_eval), pipeline=pipeline)

    def _load_dataset(self):
        if self.config.dataset in list_dataset_names():
            self.dataset = get_dataset(self.config.dataset)
            return self.dataset.load(
                split=self.config.split,
                limit=self.config.limit,
            )
        self.dataset = None
        return load_evaluation_dataset(
            dataset_name=self.config.dataset,
            split=self.config.split,
            limit=self.config.limit,
        )

    def _build_pipeline(self):
        return get_pipeline(
            self.config.pipeline,
            prediction_log_path=self._resolve_log_path(),
            include_source_text=self.config.include_source_text,
            default_score_threshold=self.config.score_threshold,
            verifier=self._build_verifier(),
        )

    def _build_verifier(self):
        if not self.config.verify:
            return None

        from src.pipeline.Verifiers import LLMVerifier

        return LLMVerifier(
            model=self.config.verify_model,
            effort=self.config.verify_effort,
            provider=parse_verify_provider(self.config.verify_provider),
            raise_on_error=True,
        )

    def _resolve_log_path(self):
        if self.config.no_log:
            return None
        if self.config.log_path is None:
            return _DEFAULT_PREDICTION_LOG_PATH_SENTINEL
        return self.config.log_path

    def _format_output(self, evaluation, *, rows: int, pipeline) -> dict:
        resolved_log_path = (
            pipeline.prediction_log_path
            if pipeline.prediction_log_path is not None
            else None
        )
        output = {
            "pipeline": self.config.pipeline,
            "rows": rows,
            "split": self.config.split,
            "log_path": str(resolved_log_path) if resolved_log_path else None,
        }
        if self.config.per_label:
            overall, per_entity, per_label = evaluation
            output.update(
                {
                    "overall": overall,
                    "per_entity": per_entity,
                    "per_label": per_label,
                }
            )
        else:
            overall, per_entity = evaluation
            output.update(
                {
                    "overall": overall,
                    "per_entity": per_entity,
                }
            )
        return output


def evaluate_from_args(args):
    return PipelineEvaluationRunner(PipelineEvaluationConfig.from_args(args)).run()


def main(argv=None):
    args = create_arg_parser().parse_args(argv)
    output = evaluate_from_args(args)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return output
