from src.pipeline.BasePipeline import PIIPipeline
from src.pipeline.Pipelines.analyzer_utils import (
    VIETNAMESE_LANGUAGE,
    create_vietnamese_analyzer,
)


class VietnamesePipeline(PIIPipeline):
    """Base class for Vietnamese experiment pipelines."""

    def __init__(
        self,
        *,
        recognizers=None,
        pipeline_name: str,
        default_score_threshold: float = 0.0,
        **kwargs,
    ):
        super().__init__(
            recognizers=recognizers or [],
            pipeline_name=pipeline_name,
            default_language=VIETNAMESE_LANGUAGE,
            default_score_threshold=default_score_threshold,
            **kwargs,
        )

    def load_model(self):
        if self.analyzer is not None:
            self.model = self.analyzer
            return

        self.analyzer = create_vietnamese_analyzer()
        for recognizer in self.recognizers:
            recognizer.load_model()
            recognizer.register_to_analyzer(self.analyzer)
        self.model = self.analyzer
