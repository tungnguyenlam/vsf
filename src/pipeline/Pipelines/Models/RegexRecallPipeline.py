from src.pipeline.Pipelines.base import VietnamesePipeline
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer


class RegexRecallPipeline(VietnamesePipeline):
    """Vietnamese regex pipeline with broader recall-oriented patterns."""

    def __init__(self, **kwargs):
        super().__init__(
            recognizers=[CustomPatternRecognizer(recall_mode=True)],
            pipeline_name="regex_recall",
            **kwargs,
        )
