from src.pipeline.PromptInjection.Datasets.HfPromptInjectionMultilingualDataset import (
    HfPromptInjectionMultilingualDataset,
)
from src.pipeline.PromptInjection.Datasets.LocalVietnamesePromptInjectionSeed import (
    LocalVietnamesePromptInjectionSeed,
)
from src.pipeline.PromptInjection.Datasets.PromptInjectionDataset import (
    PromptInjectionDataset,
)


PROMPT_INJECTION_DATASETS = {
    LocalVietnamesePromptInjectionSeed.name: LocalVietnamesePromptInjectionSeed,
    HfPromptInjectionMultilingualDataset.name: HfPromptInjectionMultilingualDataset,
}


def list_prompt_injection_dataset_names() -> list[str]:
    return sorted(PROMPT_INJECTION_DATASETS)


def get_prompt_injection_dataset(name: str, **kwargs) -> PromptInjectionDataset:
    try:
        dataset_class = PROMPT_INJECTION_DATASETS[name]
    except KeyError as exc:
        available = ", ".join(list_prompt_injection_dataset_names())
        raise ValueError(
            f"Unknown prompt-injection dataset {name!r}. Available datasets: {available}"
        ) from exc
    return dataset_class(**kwargs)
