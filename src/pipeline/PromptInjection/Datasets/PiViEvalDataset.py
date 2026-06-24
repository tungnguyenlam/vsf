from pathlib import Path

from src.pipeline.PromptInjection.Datasets.PromptInjectionDataset import (
    PromptInjectionDataset,
)
from src.pipeline.PromptInjection.Datasets.PromptInjectionExample import (
    PromptInjectionExample,
)

import json


PROJECT_ROOT = Path(__file__).resolve().parents[4]
PI_VI_EVAL_PATH = (
    PROJECT_ROOT / "data" / "safety_v0" / "eval" / "pi_vi" / "eval.jsonl"
)


class PiViEvalDataset(PromptInjectionDataset):
    """The balanced Vietnamese PI eval set as labelled training/eval examples.

    Reads the canonical ``safety_v0`` rows emitted by
    ``scripts/safety_v0/build_pi_vi_eval.py``. The ground truth lives in the
    top-level ``eval.label`` block (74 gold attacks, 46 gold benign seeds, 28
    real ViHSD negatives), so this is the same 148-row set the rule-based
    detector is scored on. Exposing it as ``PromptInjectionExample`` rows lets a
    trainable detector (the char-ngram Naive Bayes baseline) be evaluated
    leave-one-out on the identical rows, making the two detectors directly
    comparable.
    """

    name = "pi_vi_eval"
    description = "Balanced Vietnamese PI eval set (gold attacks + benign seeds + ViHSD negatives)."

    def __init__(self, path: Path | str = PI_VI_EVAL_PATH):
        self.path = Path(path)

    def load(
        self,
        split: str = "test",
        limit: int | None = None,
        random_state: int = 42,
    ) -> list[PromptInjectionExample]:
        if split not in {"test", "all"}:
            raise ValueError(f"{self.name}: split {split!r} not available. Use test or all.")

        examples: list[PromptInjectionExample] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                text = (record.get("content", {}).get("input_text") or "").strip()
                if not text:
                    continue
                eval_block = record.get("eval", {})
                examples.append(
                    PromptInjectionExample(
                        input_id=record.get("input_id") or f"{self.name}:{line_number}",
                        text=text,
                        label=int(bool(eval_block.get("label"))),
                        source=self.name,
                        language="vi",
                        category=eval_block.get("bucket"),
                    )
                )
        return self._limit(examples, limit, random_state)
