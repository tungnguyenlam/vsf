from src.pipeline.BaseModel import BaseModel
from src.pipeline.Recognizers.SpacyRecognizer import SpacyRecognizer
from presidio_analyzer import AnalyzerEngine

class PIIPipeline(BaseModel):
    """Modular orchestration pipeline designed to swap recognizers in and out."""
    
    def __init__(self, spacy_recognizer=None, recognizers=None, analyzer=None, device: str = "cpu", verbose: bool = False):
        super().__init__(device=device, verbose=verbose)
        self.spacy_recognizer = spacy_recognizer
        self.recognizers = recognizers or []
        self.analyzer = analyzer
        
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
            # Fallback to default Presidio AnalyzerEngine
            self.analyzer = AnalyzerEngine()
        
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
        score_threshold = kwargs.get("score_threshold", 0.0)
        
        # Determine language code (use spaCy recognizer code if available, else default to "en")
        default_lang = self.spacy_recognizer.lang_code if self.spacy_recognizer is not None else "en"
        language = kwargs.get("language", default_lang)
        
        if isinstance(inputs, str):
            return self.analyzer.analyze(text=inputs, language=language, score_threshold=score_threshold)
        elif hasattr(inputs, "__iter__"):
            return [self.analyzer.analyze(text=text, language=language, score_threshold=score_threshold) for text in inputs]
        return []
