from src.pipeline.BaseModel import BaseModel
from src.pipeline.PredictionJsonlLogger import PredictionJsonlLogger
from src.pipeline.Recognizers.SpacyRecognizer import SpacyRecognizer
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PREDICTION_LOG_PATH = Path(__file__).resolve().parents[2] / "output" / "predictions.jsonl"
_DEFAULT_PREDICTION_LOG_PATH_SENTINEL = object()

class PIIPipeline(BaseModel):
    """Modular orchestration pipeline designed to swap recognizers in and out."""
    
    def __init__(
        self,
        spacy_recognizer=None,
        recognizers=None,
        analyzer=None,
        verifier=None,
        device: str = "cpu",
        verbose: bool = False,
        pipeline_name: str = "pii_pipeline",
        default_language: str = "vi",
        default_score_threshold: float = 0.0,
        run_id: str = None,
        prediction_log_path=_DEFAULT_PREDICTION_LOG_PATH_SENTINEL,
        include_source_text: bool = False,
        include_detected_text: bool = True,
        include_anonymized_text: bool = True,
    ):
        super().__init__(device=device, verbose=verbose)
        prediction_log_path_omitted = prediction_log_path is _DEFAULT_PREDICTION_LOG_PATH_SENTINEL
        self.spacy_recognizer = spacy_recognizer
        self.recognizers = recognizers or []
        self.analyzer = analyzer
        self.verifier = verifier
        self.pipeline_name = pipeline_name
        self.default_language = default_language
        self.default_score_threshold = default_score_threshold
        self.run_id = run_id or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.prediction_log_path = (
            DEFAULT_PREDICTION_LOG_PATH
            if prediction_log_path_omitted
            else prediction_log_path
        )
        self.include_source_text = include_source_text
        self.include_detected_text = include_detected_text
        self.include_anonymized_text = include_anonymized_text
        
    def add_recognizer(self, recognizer):
        """Add a custom recognizer (e.g. regex patterns or Hugging Face transformers) to the pipeline."""
        self.recognizers.append(recognizer)
        if self.analyzer is not None:
            # Register it dynamically if pipeline is already loaded
            recognizer.register_to_analyzer(self.analyzer)
            
    def load_model(self):
        if self.analyzer is not None:
            # If analyzer is already provided, load and register additional modules
            for recognizer in self.recognizers:
                recognizer.load_model()
                recognizer.register_to_analyzer(self.analyzer)
            self.model = self.analyzer
            return
            
        if self.spacy_recognizer is not None:
            # 1. Load spaCy baseline which initializes the base Presidio AnalyzerEngine
            self.spacy_recognizer.load_model()
            self.analyzer = self.spacy_recognizer.analyzer
        else:
            if self.default_language == "vi":
                from src.pipeline.Pipelines.analyzer_utils import create_vietnamese_analyzer

                self.analyzer = create_vietnamese_analyzer()
            else:
                self.analyzer = AnalyzerEngine(supported_languages=[self.default_language])
        
        # 2. Load and register additional modules
        for recognizer in self.recognizers:
            recognizer.load_model()
            recognizer.register_to_analyzer(self.analyzer)
            
        self.model = self.analyzer
        
    def unload_model(self):
        if self.spacy_recognizer is not None:
            self.spacy_recognizer.unload_model()
        for recognizer in self.recognizers:
            recognizer.unload_model()
        self.analyzer = None
        super().unload_model()
        
    def predict(self, inputs, **kwargs):
        """Analyze input text using the fully assembled pipeline."""
        if self.analyzer is None:
            self.load_model()
        score_threshold = kwargs.get("score_threshold", self.default_score_threshold)
        logging_enabled = self.prediction_log_path is not None
        
        # Determine language code (use spaCy recognizer code if available, else pipeline default).
        default_lang = self.spacy_recognizer.lang_code if self.spacy_recognizer is not None else self.default_language
        language = kwargs.get("language", default_lang)
        input_ids = kwargs.get("input_ids")
        ground_truth = kwargs.get("ground_truth")
        
        if isinstance(inputs, str):
            results = self._analyze_text(
                inputs,
                language=language,
                score_threshold=score_threshold,
                logging_enabled=logging_enabled,
            )
            if logging_enabled:
                self._log_prediction(
                    text=inputs,
                    results=results,
                    input_id=self._value_for_index(input_ids, 0),
                    ground_truth=ground_truth,
                    language=language,
                    score_threshold=score_threshold,
                )
            return results
        elif hasattr(inputs, "__iter__"):
            input_texts = list(inputs)
            results_by_input = [
                self._analyze_text(
                    text,
                    language=language,
                    score_threshold=score_threshold,
                    logging_enabled=logging_enabled,
                )
                for text in input_texts
            ]
            if logging_enabled:
                for index, (text, results) in enumerate(zip(input_texts, results_by_input)):
                    self._log_prediction(
                        text=text,
                        results=results,
                        input_id=self._value_for_index(input_ids, index),
                        ground_truth=self._value_for_index(ground_truth, index),
                        language=language,
                        score_threshold=score_threshold,
                    )
            return results_by_input
        return []

    def _analyze_text(self, text, *, language, score_threshold, logging_enabled):
        analyze_kwargs = {
            "text": text,
            "language": language,
            "score_threshold": score_threshold,
        }
        # Decision process carries recognizer provenance the verifier needs.
        if logging_enabled or self.verifier is not None:
            analyze_kwargs["return_decision_process"] = True
        results = self.analyzer.analyze(**analyze_kwargs)
        if self.verifier is not None:
            results = self.verifier.verify(text, results, language=language)
        return results

    def _log_prediction(self, *, text, results, input_id, ground_truth, language, score_threshold):
        anonymized_text = None
        if self.include_anonymized_text:
            anonymized_text = AnonymizerEngine().anonymize(text=text, analyzer_results=results).text

        PredictionJsonlLogger(self.prediction_log_path).log_prediction(
            run_id=self.run_id,
            pipeline_name=self.pipeline_name,
            input_id=input_id,
            language=language,
            score_threshold=score_threshold,
            source_text=text,
            results=results,
            anonymized_text=anonymized_text,
            ground_truth=ground_truth,
            include_source_text=self.include_source_text,
            include_detected_text=self.include_detected_text,
        )

    def _value_for_index(self, value, index):
        if value is None:
            return None
        if isinstance(value, (str, bytes, dict, int, float)):
            return value
        try:
            return value[index]
        except (IndexError, TypeError, KeyError):
            return None
