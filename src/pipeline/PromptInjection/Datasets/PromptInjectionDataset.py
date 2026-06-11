from src.pipeline.PromptInjection.Datasets.PromptInjectionExample import (
    PromptInjectionExample,
)


class PromptInjectionDataset:
    name: str = ""
    description: str = ""

    def load(
        self,
        split: str = "test",
        limit: int | None = None,
        random_state: int = 42,
    ) -> list[PromptInjectionExample]:
        raise NotImplementedError

    def _limit(
        self,
        examples: list[PromptInjectionExample],
        limit: int | None,
        random_state: int,
    ) -> list[PromptInjectionExample]:
        if limit is None or len(examples) <= limit:
            return examples

        import random

        rng = random.Random(random_state)
        selected = rng.sample(range(len(examples)), limit)
        return [examples[index] for index in sorted(selected)]
