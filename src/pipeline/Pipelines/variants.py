from src.pipeline.Pipelines.base import VietnamesePipeline
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer


class BaselinePresidioPipeline(VietnamesePipeline):
    """Vietnamese Presidio shell without experiment recognizers."""

    def __init__(self, **kwargs):
        super().__init__(
            recognizers=[],
            pipeline_name="baseline_presidio",
            **kwargs,
        )


class RegexOnlyPipeline(VietnamesePipeline):
    """Vietnamese regex-only pipeline using repository pattern recognizers."""

    def __init__(self, **kwargs):
        super().__init__(
            recognizers=[CustomPatternRecognizer()],
            pipeline_name="regex_only",
            **kwargs,
        )


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
