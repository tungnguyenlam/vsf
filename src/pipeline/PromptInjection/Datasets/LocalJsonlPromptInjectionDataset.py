import json
from pathlib import Path

from src.pipeline.PromptInjection.Datasets.PromptInjectionDataset import (
    PromptInjectionDataset,
)
from src.pipeline.PromptInjection.Datasets.PromptInjectionExample import (
    PromptInjectionExample,
)


class LocalJsonlPromptInjectionDataset(PromptInjectionDataset):
    path: Path

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(
        self,
        split: str = "test",
        limit: int | None = None,
        random_state: int = 42,
    ) -> list[PromptInjectionExample]:
        if split not in {"test", "all"}:
            raise ValueError(f"{self.name}: split {split!r} not available. Use test or all.")

        examples = []
        with self.path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                examples.append(self._example_from_record(record, line_number))
        return self._limit(examples, limit, random_state)

    def _example_from_record(
        self,
        record: dict,
        line_number: int,
    ) -> PromptInjectionExample:
        return PromptInjectionExample(
            input_id=record.get("input_id") or f"{self.name}:{line_number}",
            text=record["text"],
            label=int(record["label"]),
            source=record.get("source", self.name),
            language=record.get("language", "vi"),
            category=record.get("category"),
            expected_action=record.get("expected_action"),
        )
