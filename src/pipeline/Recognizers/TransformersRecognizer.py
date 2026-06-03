"""Backward-compatible shim.

TransformersRecognizer is now implemented as DeepLearningRecognizer + HFTransformersNER.
This file preserves the original constructor signature so existing notebook code
continues to work without modifications.

For new code, prefer:
    from src.pipeline.NERWrappers.HFTransformersNER import HFTransformersNER
    from src.pipeline.Recognizers.DeepLearningRecognizer import DeepLearningRecognizer
"""

from src.pipeline.NERWrappers.HFTransformersNER import HFTransformersNER
from src.pipeline.Recognizers.DeepLearningRecognizer import DeepLearningRecognizer

DEFAULT_TRANSFORMER_MODEL_ID = "NlpHUST/ner-vietnamese-electra-base"
DEFAULT_TRANSFORMER_LABEL_MAPPING = {
    "PER": "PERSON",
    "LOC": "LOCATION",
    "ORG": "ORGANIZATION",
    "MISC": "MISC",
}


class TransformersRecognizer(DeepLearningRecognizer):
    """Backward-compatible wrapper around DeepLearningRecognizer + HFTransformersNER.

    Preserves the original constructor interface:
        TransformersRecognizer(model_id=..., label_mapping=..., lang_code=...)

    Internally creates an HFTransformersNER wrapper and passes it to
    DeepLearningRecognizer.
    """

    def __init__(
        self,
        model_id: str = DEFAULT_TRANSFORMER_MODEL_ID,
        label_mapping: dict = None,
        lang_code: str = "vi",
        device: str = "cpu",
        verbose: bool = False,
    ):
        label_mapping = label_mapping or DEFAULT_TRANSFORMER_LABEL_MAPPING

        # Translate device string to HF pipeline device index
        hf_device = None
        if device == "cuda":
            hf_device = 0
        elif device == "cpu":
            hf_device = -1

        ner_wrapper = HFTransformersNER(
            model_id=model_id,
            label_mapping=label_mapping,
            device=hf_device,
        )

        super().__init__(
            ner_wrapper=ner_wrapper,
            lang_code=lang_code,
            device=device,
            verbose=verbose,
        )
