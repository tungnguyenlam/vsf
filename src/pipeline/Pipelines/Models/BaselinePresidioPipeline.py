from src.pipeline.Pipelines.base import VietnamesePipeline


class BaselinePresidioPipeline(VietnamesePipeline):
    """Vietnamese Presidio shell without experiment recognizers."""

    def __init__(self, **kwargs):
        super().__init__(
            recognizers=[],
            pipeline_name="baseline_presidio",
            **kwargs,
        )
