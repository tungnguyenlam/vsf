import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.pipeline.Datasets import get_dataset, list_dataset_names, resolve_dataset_key
from src.pipeline.Evaluator import PIIEvaluator
from src.pipeline.Pipelines.registry import get_pipeline, list_pipeline_names
from src.pipeline.Utils import DEFAULT_DATASET_NAME, load_evaluation_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EVALUATION_OUTPUT_DIR = PROJECT_ROOT / "output" / "evaluations"


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
    input_ids: Optional[tuple[str, ...]] = None

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
            env_path=Path(args.env_path) if getattr(args, "env_path", None) is not None else None,
            input_ids=_resolve_input_ids(args),
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


def _read_input_ids_file(path: str) -> list[str]:
    """Read an input_ids list from a manifest JSON file.

    Accepts either a top-level ``input_ids`` list or a manifest dict with the
    shape produced by :mod:`src.pipeline.Datasets.sampling`. Empty / missing
    values fall back to an empty list so callers can treat the result uniformly.
    """
    import json
    from pathlib import Path

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [str(value) for value in payload]
    ids = payload.get("input_ids", []) if isinstance(payload, dict) else []
    return [str(value) for value in ids]


def _resolve_input_ids(args) -> Optional[tuple[str, ...]]:
    """Merge ``--input-ids`` and ``--input-ids-file`` into a deterministic tuple."""
    raw = list(args.input_ids or [])
    manifest_path = getattr(args, "input_ids_file", None)
    if manifest_path:
        raw.extend(_read_input_ids_file(manifest_path))
    if not raw:
        return None
    seen: dict[str, None] = {}
    for value in raw:
        if value not in seen:
            seen[value] = None
    return tuple(seen)


def _filter_by_input_ids(df, input_ids):
    """Restrict ``df`` to the requested ``input_ids`` in the manifest order.

    Drops the input_ids not present in the frame with a warning-equivalent
    comment in the caller's metrics (handled at the runner level by reading
    the post-filter length). Returns the original frame untouched when
    ``input_ids`` is None.
    """
    if not input_ids:
        return df
    allowed = set(input_ids)
    filtered = df[df["input_id"].astype(str).isin(allowed)].copy()
    id_to_pos = {value: index for index, value in enumerate(input_ids)}
    filtered["__input_id_pos"] = filtered["input_id"].astype(str).map(id_to_pos)
    filtered = filtered.sort_values("__input_id_pos").drop(columns="__input_id_pos")
    return filtered.reset_index(drop=True)


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
    parser.add_argument(
        "--input-ids",
        action="append",
        default=None,
        metavar="ID",
        help="Restrict evaluation to a specific input_id. Repeatable.",
    )
    parser.add_argument(
        "--input-ids-file",
        default=None,
        metavar="PATH",
        help="Path to a JSON manifest with an 'input_ids' list (e.g. data/sample_ids/*.json). "
             "When set, only those rows are evaluated, independent of --limit or HF row order.",
    )
    parser.add_argument("--score-threshold", type=float, default=0.0)
    parser.add_argument(
        "--log-path",
        default=None,
        help="JSONL log path. Defaults to output/evaluations/<pipeline>/<run_id>/predictions.jsonl.",
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
        self.run_id = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y%m%dT%H%M%SZ")

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
        output = self._format_output(evaluation, rows=len(df_eval), pipeline=pipeline)
        self._write_metrics(output)
        return output

    def _load_dataset(self):
        registry_key = resolve_dataset_key(self.config.dataset)
        if registry_key in list_dataset_names():
            self.dataset = get_dataset(registry_key)
            df = self.dataset.load(
                split=self.config.split,
                limit=self.config.limit,
            )
            return _filter_by_input_ids(df, self.config.input_ids)
        self.dataset = None
        df = load_evaluation_dataset(
            dataset_name=self.config.dataset,
            split=self.config.split,
            limit=self.config.limit,
        )
        return _filter_by_input_ids(df, self.config.input_ids)

    def _build_pipeline(self):
        return get_pipeline(
            self.config.pipeline,
            run_id=self.run_id,
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
            return self._run_dir() / "predictions.jsonl"
        return self.config.log_path

    def _run_dir(self):
        return DEFAULT_EVALUATION_OUTPUT_DIR / self.config.pipeline / self.run_id

    def _metrics_path(self):
        return self._run_dir() / "metrics.json"

    def _write_metrics(self, output: dict):
        metrics_path = self._metrics_path()
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with metrics_path.open("w", encoding="utf-8") as handle:
            json.dump(output, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def _format_output(self, evaluation, *, rows: int, pipeline) -> dict:
        resolved_log_path = (
            pipeline.prediction_log_path
            if pipeline.prediction_log_path is not None
            else None
        )
        output = {
            "run_id": self.run_id,
            "pipeline": self.config.pipeline,
            "dataset": self.config.dataset,
            "rows": rows,
            "split": self.config.split,
            "output_dir": str(self._run_dir()),
            "metrics_path": str(self._metrics_path()),
            "log_path": str(resolved_log_path) if resolved_log_path else None,
        }
        if self.config.input_ids:
            output["input_ids_requested"] = len(self.config.input_ids)
            output["input_ids_matched"] = rows
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
