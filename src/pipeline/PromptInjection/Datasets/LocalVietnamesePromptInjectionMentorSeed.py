from pathlib import Path

from src.pipeline.PromptInjection.Datasets.LocalJsonlPromptInjectionDataset import (
    LocalJsonlPromptInjectionDataset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]
LOCAL_MENTOR_SEED_PATH = (
    PROJECT_ROOT / "data" / "prompt_injection" / "vietnamese_mentor_seed.jsonl"
)


class LocalVietnamesePromptInjectionMentorSeed(LocalJsonlPromptInjectionDataset):
    name = "local_vietnamese_mentor_seed"
    description = "Repo-owned Vietnamese mentor/application-style prompt-injection seed benchmark."

    def __init__(self, path: Path | str = LOCAL_MENTOR_SEED_PATH):
        super().__init__(path)
