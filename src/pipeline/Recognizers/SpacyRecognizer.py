import spacy
from spacy import cli as spacy_cli
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from src.pipeline.Recognizers.BaseRecognizer import BaseRecognizer

class SpacyRecognizer(BaseRecognizer):
    """Modular wrapper for spaCy-based baseline NLP engine and predefined recognizers."""
    
    def __init__(self, model_name: str = "xx_ent_wiki_sm", lang_code: str = "xx", device: str = "cpu", verbose: bool = False):
        super().__init__(device=device, verbose=verbose)
        self.model_name = model_name
        self.lang_code = lang_code
        self.nlp_engine = None
        self.analyzer = None
        
    def ensure_spacy_model(self) -> bool:
        if self.model_name == "vi_core_news_sm":
            return False
        try:
            spacy.load(self.model_name)
            return True
        except OSError:
            try:
                if self.verbose:
                    print(f"Downloading spaCy model {self.model_name}...")
                spacy_cli.download(self.model_name)
                spacy.load(self.model_name)
                return True
            except SystemExit as exc:
                print(f"Skipping spaCy model {self.model_name!r}: download exited with code {exc.code}.")
                return False
            except Exception as exc:
                print(f"Skipping spaCy model {self.model_name!r}: {exc}")
                return False
                
    def load_model(self):
        if self.nlp_engine is not None:
            return
            
        model_to_use = self.model_name
        if not self.ensure_spacy_model():
            if self.lang_code == "vi" and self.model_name == "vi_core_news_sm":
                fallback_model = "xx_ent_wiki_sm"
                if self.verbose:
                    print(f"spaCy model {self.model_name!r} not available. Falling back to {fallback_model!r} for language 'vi'.")
                self.model_name = fallback_model
                self.ensure_spacy_model()
                model_to_use = fallback_model
                
        nlp_config = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": self.lang_code, "model_name": model_to_use}],
        }
        self.nlp_engine = NlpEngineProvider(nlp_configuration=nlp_config).create_engine()
        self.analyzer = AnalyzerEngine(nlp_engine=self.nlp_engine, supported_languages=[self.lang_code])
        self.model = self.analyzer
        
    def unload_model(self):
        self.nlp_engine = None
        self.analyzer = None
        super().unload_model()
        
    def register_to_analyzer(self, analyzer_engine):
        # SpacyRecognizer acts as the core NlpEngine itself.
        pass
        
    def predict(self, inputs, **kwargs):
        """Analyze text inputs. inputs can be a single string or a list of strings."""
        if self.analyzer is None:
            self.load_model()
        score_threshold = kwargs.get("score_threshold", 0.0)
        language = kwargs.get("language", self.lang_code)
        
        if isinstance(inputs, str):
            return self.analyzer.analyze(text=inputs, language=language, score_threshold=score_threshold)
        elif hasattr(inputs, "__iter__"):
            return [self.analyzer.analyze(text=text, language=language, score_threshold=score_threshold) for text in inputs]
        return []
