from pathlib import Path

from src.pipeline.PromptInjection.Datasets.LocalJsonlPromptInjectionDataset import (
    LocalJsonlPromptInjectionDataset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
LOCAL_APP_SEED_PATH = PROJECT_ROOT / "data" / "prompt_injection" / "vietnamese_app_seed.jsonl"


class LocalVietnamesePromptInjectionAppSeed(LocalJsonlPromptInjectionDataset):
    name = "local_vietnamese_app_seed"
    description = "Repo-owned Vietnamese application-shaped prompt-injection seed benchmark."

    def __init__(self, path: Path | str = LOCAL_APP_SEED_PATH):
        super().__init__(path)
