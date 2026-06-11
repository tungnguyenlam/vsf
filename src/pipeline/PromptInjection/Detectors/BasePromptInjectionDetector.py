from src.pipeline.BaseModel import BaseModel


class BasePromptInjectionDetector(BaseModel):
    """Base interface for prompt-injection detectors."""

    def detect(self, text: str):
        raise NotImplementedError
