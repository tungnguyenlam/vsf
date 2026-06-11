from src.pipeline.PromptInjection.Datasets.HuggingFacePromptInjectionDataset import (
    HuggingFacePromptInjectionDataset,
)


class HfPromptInjectionMultilingualDataset(HuggingFacePromptInjectionDataset):
    name = "hf_prompt_injection_multilingual"
    hf_name = "rikka-snow/prompt-injection-multilingual"
    description = "Public HuggingFace multilingual binary prompt-injection dataset."
