from src.pipeline.NERWrappers.UndertheseaNER import UndertheseaNER
from src.pipeline.Pipelines.base import VietnamesePipeline
from src.pipeline.Recognizers.DeepLearningRecognizer import DeepLearningRecognizer


class UndertheseaNerPipeline(VietnamesePipeline):
    """Vietnamese NER-only pipeline backed by Underthesea."""

    def __init__(self, **kwargs):
        super().__init__(
            recognizers=[
                DeepLearningRecognizer(
                    ner_wrapper=UndertheseaNER(),
                    supported_entities=["PERSON", "LOCATION", "ORGANIZATION"],
                )
            ],
            pipeline_name="underthesea_ner",
            **kwargs,
        )
