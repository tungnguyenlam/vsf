from src.pipeline.Pipelines.base import VietnamesePipeline
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer


class RegexOnlyPipeline(VietnamesePipeline):
    """Vietnamese regex-only pipeline using repository pattern recognizers."""

    def __init__(self, **kwargs):
        super().__init__(
            recognizers=[CustomPatternRecognizer()],
            pipeline_name="regex_only",
            **kwargs,
        )
