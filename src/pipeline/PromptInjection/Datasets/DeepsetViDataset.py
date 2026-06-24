import json
from pathlib import Path

from src.pipeline.PromptInjection.Datasets.PromptInjectionDataset import (
    PromptInjectionDataset,
)
from src.pipeline.PromptInjection.Datasets.PromptInjectionExample import (
    PromptInjectionExample,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEEPSET_VI_PATH = (
    PROJECT_ROOT
    / "data"
    / "safety_v0"
    / "augmented"
    / "deepset_prompt_injections"
    / "augmented.jsonl"
)


class DeepsetViDataset(PromptInjectionDataset):
    """Vietnamese deepset prompt-injection set (translated twins only).

    Reads the EN->VI twins produced by
    ``scripts/safety_v0/run_translation_augmentation.py --slug
    deepset_prompt_injections`` and keeps only the translated rows (those with an
    ``augmentation`` block), so every example is Vietnamese. The label comes from
    ``labels.prompt_injection``.

    This is the first Vietnamese attack data the hand-written rules were *not*
    authored against, so it gives a genuine held-out generalization estimate
    (recall on real attacks, false-positive rate on real benigns) rather than the
    coverage-by-construction score on the local seeds.
    """

    name = "deepset_vi"
    description = "Vietnamese (translated) deepset prompt-injection attacks and benigns."

    def __init__(self, path: Path | str = DEEPSET_VI_PATH):
        self.path = Path(path)

    def load(
        self,
        split: str = "test",
        limit: int | None = None,
        random_state: int = 42,
    ) -> list[PromptInjectionExample]:
        if split not in {"test", "all"}:
            raise ValueError(
                f"{self.name}: split {split!r} not available. Use test or all."
            )

        examples: list[PromptInjectionExample] = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                # Keep only translated twins (Vietnamese); skip the English originals.
                if not record.get("augmentation"):
                    continue
                text = (record.get("content", {}).get("input_text") or "").strip()
                if not text:
                    continue
                label_value = record.get("labels", {}).get("prompt_injection")
                if label_value is None:
                    continue
                examples.append(
                    PromptInjectionExample(
                        input_id=record.get("input_id") or f"{self.name}:{line_number}",
                        text=text,
                        label=int(bool(label_value)),
                        source=self.name,
                        language="vi",
                        category="attack" if label_value else "benign",
                    )
                )
        return self._limit(examples, limit, random_state)
