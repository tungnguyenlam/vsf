import uuid
from pathlib import Path

from src.pipeline.PromptInjection.Datasets import get_prompt_injection_dataset
from src.pipeline.PromptInjection.Detectors import get_prompt_injection_detector
from src.pipeline.PromptInjection.Evaluation.PromptInjectionEvaluationConfig import (
    PromptInjectionEvaluationConfig,
)
from src.pipeline.PromptInjection.Logging import PromptInjectionDecisionJsonlLogger


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DECISION_LOG_DIR = PROJECT_ROOT / "output" / "prompt_injection"


class PromptInjectionEvaluationRunner:
    def __init__(self, config: PromptInjectionEvaluationConfig):
        self.config = config

    def run(self) -> dict:
        dataset = get_prompt_injection_dataset(self.config.dataset)
        examples = dataset.load(
            split=self.config.split,
            limit=self.config.limit,
            random_state=self.config.random_state,
        )
        run_id = self.config.run_id or f"prompt-injection-{uuid.uuid4().hex[:8]}"
        logger = self._build_logger(run_id)

        # For external training the detector is fit once on a separate dataset
        # and reused for every eval row (a true held-out test).
        shared_detector = (
            self._build_external_detector() if self.config.train_strategy == "external" else None
        )

        decisions = []
        counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
        action_counts = {"correct": 0, "total": 0}
        for index, example in enumerate(examples):
            detector = shared_detector or self._build_detector(examples, holdout_index=index)
            result = detector.predict(example.text)
            self._update_counts(counts, predicted=result.is_injection, actual=example.is_injection)
            self._update_action_counts(action_counts, example=example, result=result)
            decisions.append(self._decision(example, result))
            if logger is not None:
                logger.log_decision(
                    run_id=run_id,
                    detector_name=self.config.detector,
                    example=example,
                    result=result,
                    include_source_text=self.config.include_source_text,
                )

        return {
            "detector": self.config.detector,
            "dataset": self.config.dataset,
            "split": self.config.split,
            "rows": len(examples),
            "run_id": run_id,
            "log_path": str(logger.path) if logger is not None else None,
            "metrics": self._metrics(counts),
            "action_metrics": self._action_metrics(action_counts),
            "counts": counts,
            "action_counts": action_counts,
            "decisions": decisions,
        }

    def _build_detector(self, examples, *, holdout_index: int):
        detector = get_prompt_injection_detector(self.config.detector)
        if self.config.train_strategy == "none":
            return detector
        if self.config.train_strategy not in {"leave_one_out", "external"}:
            raise ValueError(
                f"Unsupported train strategy {self.config.train_strategy!r}. "
                "Use 'none', 'leave_one_out', or 'external'."
            )
        if not hasattr(detector, "fit"):
            raise ValueError(
                f"Detector {self.config.detector!r} does not support training."
            )
        train_examples = [
            example for index, example in enumerate(examples) if index != holdout_index
        ]
        detector.fit(train_examples)
        return detector

    def _build_external_detector(self):
        if not self.config.train_dataset:
            raise ValueError(
                "train_strategy='external' requires train_dataset to be set."
            )
        detector = get_prompt_injection_detector(self.config.detector)
        if not hasattr(detector, "fit"):
            raise ValueError(
                f"Detector {self.config.detector!r} does not support training."
            )
        # train_dataset may name a pool of sources, comma-separated; their
        # examples are concatenated so a detector can learn from several
        # Vietnamese sources at once and be scored on a held-out one.
        names = [name.strip() for name in self.config.train_dataset.split(",") if name.strip()]
        train_examples = []
        for name in names:
            train_examples.extend(
                get_prompt_injection_dataset(name).load(
                    split="all", random_state=self.config.random_state
                )
            )
        detector.fit(train_examples)
        return detector

    def _build_logger(self, run_id: str):
        if self.config.no_log:
            return None
        if self.config.log_path is not None:
            return PromptInjectionDecisionJsonlLogger(self.config.log_path)
        run_dir = DEFAULT_DECISION_LOG_DIR / run_id
        return PromptInjectionDecisionJsonlLogger(run_dir / "decisions.jsonl")

    def _update_counts(self, counts: dict[str, int], *, predicted: bool, actual: bool):
        if predicted and actual:
            counts["tp"] += 1
        elif predicted and not actual:
            counts["fp"] += 1
        elif not predicted and not actual:
            counts["tn"] += 1
        else:
            counts["fn"] += 1

    def _update_action_counts(self, counts: dict[str, int], *, example, result):
        if example.expected_action is None:
            return
        counts["total"] += 1
        if result.action == example.expected_action:
            counts["correct"] += 1

    def _decision(self, example, result) -> dict:
        return {
            "input_id": example.input_id,
            "label": example.label,
            "expected_action": example.expected_action,
            "predicted_label": int(result.is_injection),
            "score": result.score,
            "action": result.action,
            "matched_rules": result.matched_rules,
        }

    def _metrics(self, counts: dict[str, int]) -> dict[str, float]:
        tp = counts["tp"]
        fp = counts["fp"]
        tn = counts["tn"]
        fn = counts["fn"]
        total = tp + fp + tn + fn
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        accuracy = (tp + tn) / total if total else 0.0
        return {
            "accuracy": round(accuracy, 6),
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
        }

    def _action_metrics(self, counts: dict[str, int]) -> dict[str, float | None]:
        if counts["total"] == 0:
            return {"accuracy": None}
        return {"accuracy": round(counts["correct"] / counts["total"], 6)}
