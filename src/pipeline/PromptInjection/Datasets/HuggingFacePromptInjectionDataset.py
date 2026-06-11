from typing import Iterable

from src.pipeline.PromptInjection.Datasets.PromptInjectionDataset import (
    PromptInjectionDataset,
)
from src.pipeline.PromptInjection.Datasets.PromptInjectionExample import (
    PromptInjectionExample,
)


class HuggingFacePromptInjectionDataset(PromptInjectionDataset):
    hf_name: str = ""
    text_column: str = "text"
    label_column: str = "label"
    language: str = "multilingual"

    def load(
        self,
        split: str = "test",
        limit: int | None = None,
        random_state: int = 42,
    ) -> list[PromptInjectionExample]:
        from datasets import load_dataset

        mapped_split = "test" if split in {"validation", "val"} else split
        dataset = load_dataset(self.hf_name)
        if mapped_split == "all":
            splits: Iterable[str] = dataset.keys()
        elif mapped_split in dataset:
            splits = [mapped_split]
        else:
            available = ", ".join(dataset.keys())
            raise ValueError(
                f"{self.name}: split {split!r} not available. Available: {available}"
            )

        examples = []
        for split_name in splits:
            frame = dataset[split_name].to_pandas()
            for row_index, row in frame.iterrows():
                examples.append(
                    PromptInjectionExample(
                        input_id=f"{self.name}:{split_name}:{row_index}",
                        text=str(row[self.text_column]),
                        label=int(row[self.label_column]),
                        source=self.hf_name,
                        language=self.language,
                    )
                )
        return self._limit(examples, limit, random_state)
