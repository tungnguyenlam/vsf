from src.pipeline.Pipelines.base import VietnamesePipeline
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer


class RegexRecallViePiiPipeline(VietnamesePipeline):
    """Recall regex plus broad patterns tuned for the HoangHa/vie-pii corpus."""

    def __init__(self, **kwargs):
        super().__init__(
            recognizers=[CustomPatternRecognizer(recall_mode=True, vie_pii_mode=True)],
            pipeline_name="regex_recall_vie_pii",
            **kwargs,
        )

