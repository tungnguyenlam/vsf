from src.pipeline.Pipelines.base import VietnamesePipeline
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer


class HybridRegexPipeline(VietnamesePipeline):
    """Vietnamese hybrid scaffold with regex recognizers plus optional extras."""

    def __init__(self, extra_recognizers=None, **kwargs):
        recognizers = [CustomPatternRecognizer()]
        recognizers.extend(extra_recognizers or [])
        super().__init__(
            recognizers=recognizers,
            pipeline_name="hybrid_regex",
            **kwargs,
        )
