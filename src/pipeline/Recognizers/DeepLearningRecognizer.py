from typing import List

from presidio_analyzer import EntityRecognizer, RecognizerResult, AnalysisExplanation
from presidio_analyzer.nlp_engine import NlpArtifacts

from src.pipeline.Recognizers.BaseRecognizer import BaseRecognizer
from src.pipeline.NERWrappers.BaseNERWrapper import BaseNERWrapper


class _WrapperEntityRecognizer(EntityRecognizer):
    """Internal Presidio EntityRecognizer that delegates NER to a BaseNERWrapper.

    This is registered into the Presidio AnalyzerEngine's registry so the
    wrapper's predictions are included in the standard Presidio analysis flow
    alongside spaCy and regex recognizers.
    """

    def __init__(
        self,
        ner_wrapper: BaseNERWrapper,
        supported_entities: List[str],
        supported_language: str = "vi",
        name: str = None,
    ):
        self.ner_wrapper = ner_wrapper
        super().__init__(
            supported_entities=supported_entities,
            supported_language=supported_language,
            name=name or f"DeepLearning_{ner_wrapper.__class__.__name__}",
        )

    def load(self) -> None:
        """No-op: loading is handled by the outer DeepLearningRecognizer."""
        pass

    def analyze(
        self, text: str, entities: List[str], nlp_artifacts: NlpArtifacts = None
    ) -> List[RecognizerResult]:
        """Run the NER wrapper and convert predictions to RecognizerResult objects."""
        predictions = self.ner_wrapper.predict_entities(text)

        results = []
        for pred in predictions:
            entity_type = pred["entity_type"]
            if entity_type not in entities:
                continue

            explanation = AnalysisExplanation(
                recognizer=self.name,
                original_score=pred["score"],
                textual_explanation=f"Detected by {self.ner_wrapper.__class__.__name__}",
            )

            result = RecognizerResult(
                entity_type=entity_type,
                start=pred["start"],
                end=pred["end"],
                score=round(pred["score"], 2),
                analysis_explanation=explanation,
            )
            # Carry provenance so a downstream verifier knows this came from the
            # deep-learning recognizer (regex/spaCy recognizers set this already).
            result.recognition_metadata = {
                RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
            }
            results.append(result)

        return results


class DeepLearningRecognizer(BaseRecognizer):
    """Modular recognizer that wraps any BaseNERWrapper and registers it
    as a custom Presidio EntityRecognizer.

    This is the integration layer between the NER wrapper abstraction and
    the Presidio pipeline. It:
    1. Loads the NER wrapper model
    2. Creates a _WrapperEntityRecognizer (Presidio EntityRecognizer subclass)
    3. Registers it to the AnalyzerEngine's registry

    Args:
        ner_wrapper: Any BaseNERWrapper implementation (HFTransformersNER, SpacyNER, EnsembleNER, etc.)
        supported_entities: List of Presidio entity types to detect. If None, inferred from wrapper's label_mapping.
        lang_code: Language code for Presidio registration.
        device: Device string (for BaseRecognizer compatibility).
        verbose: Enable verbose logging.
    """

    def __init__(
        self,
        ner_wrapper: BaseNERWrapper,
        supported_entities: List[str] = None,
        lang_code: str = "vi",
        device: str = "cpu",
        verbose: bool = False,
    ):
        super().__init__(device=device, verbose=verbose)
        self.ner_wrapper = ner_wrapper
        self.lang_code = lang_code
        self.supported_entities = supported_entities
        self._presidio_recognizer = None

    def load_model(self):
        """Load the NER wrapper and create the Presidio EntityRecognizer bridge."""
        if self._presidio_recognizer is not None:
            return

        self.ner_wrapper.load()

        # Infer supported entities from the wrapper's label mapping if not provided
        entities = self.supported_entities
        if entities is None:
            if hasattr(self.ner_wrapper, "label_mapping"):
                entities = list(set(self.ner_wrapper.label_mapping.values()))
            else:
                entities = ["PERSON", "LOCATION", "ORGANIZATION", "MISC"]

        self._presidio_recognizer = _WrapperEntityRecognizer(
            ner_wrapper=self.ner_wrapper,
            supported_entities=entities,
            supported_language=self.lang_code,
        )
        self.model = self._presidio_recognizer

    def unload_model(self):
        """Unload the NER wrapper and free resources."""
        self.ner_wrapper.unload()
        self._presidio_recognizer = None
        super().unload_model()

    def register_to_analyzer(self, analyzer_engine):
        """Register the wrapper-backed EntityRecognizer to the Presidio AnalyzerEngine."""
        self.load_model()
        if self._presidio_recognizer is not None:
            analyzer_engine.registry.add_recognizer(self._presidio_recognizer)

    def predict(self, inputs, **kwargs):
        """Direct prediction bypasses Presidio — returns raw wrapper output.

        In normal pipeline usage, prediction happens through the registered
        Presidio EntityRecognizer. This method is provided for standalone testing.
        """
        if not self.ner_wrapper.is_loaded:
            self.ner_wrapper.load()
        if isinstance(inputs, str):
            return self.ner_wrapper.predict_entities(inputs)
        elif hasattr(inputs, "__iter__"):
            return [self.ner_wrapper.predict_entities(text) for text in inputs]
        return []
