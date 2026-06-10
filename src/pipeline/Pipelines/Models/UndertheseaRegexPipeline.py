from src.pipeline.NERWrappers.UndertheseaNER import UndertheseaNER
from src.pipeline.Pipelines.base import VietnamesePipeline
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer
from src.pipeline.Recognizers.DeepLearningRecognizer import DeepLearningRecognizer


class UndertheseaRegexPipeline(VietnamesePipeline):
    """Vietnamese regex pipeline augmented with Underthesea NER."""

    def __init__(self, recall_regex: bool = False, **kwargs):
        super().__init__(
            recognizers=[
                CustomPatternRecognizer(recall_mode=recall_regex),
                DeepLearningRecognizer(
                    ner_wrapper=UndertheseaNER(
                        label_mapping={"PER": "PERSON"},
                        person_context_required=True,
                        min_score=0.7,
                    ),
                    supported_entities=["PERSON"],
                ),
            ],
            pipeline_name="underthesea_regex_recall" if recall_regex else "underthesea_regex",
            **kwargs,
        )


class UndertheseaRegexRecallPipeline(UndertheseaRegexPipeline):
    """Recall-regex pipeline augmented with filtered Underthesea PERSON spans."""

    def __init__(self, **kwargs):
        super().__init__(recall_regex=True, **kwargs)
