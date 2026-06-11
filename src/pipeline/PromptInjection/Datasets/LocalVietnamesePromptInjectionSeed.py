from pathlib import Path

from src.pipeline.PromptInjection.Datasets.LocalJsonlPromptInjectionDataset import (
    LocalJsonlPromptInjectionDataset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
LOCAL_SEED_PATH = PROJECT_ROOT / "data" / "prompt_injection" / "vietnamese_seed.jsonl"


class LocalVietnamesePromptInjectionSeed(LocalJsonlPromptInjectionDataset):
    name = "local_vietnamese_seed"
    description = "Repo-owned Vietnamese prompt-injection seed benchmark."

    def __init__(self, path: Path | str = LOCAL_SEED_PATH):
        super().__init__(path)
