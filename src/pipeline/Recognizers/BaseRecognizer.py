from src.pipeline.BaseModel import BaseModel
from abc import abstractmethod

class BaseRecognizer(BaseModel):
    """Abstract base class specifically for swappable PII recognizers."""
    
    def __init__(self, device: str = "cpu", verbose: bool = False):
        super().__init__(device=device, verbose=verbose)
        
    @abstractmethod
    def register_to_analyzer(self, analyzer_engine):
        """Register the underlying Presidio EntityRecognizer(s) to the AnalyzerEngine."""
        pass
        
    def predict(self, inputs, **kwargs):
        """Base predict standardizes input analysis for a single text input.
        
        Usage:
            recognizer.predict("some text", language="vi")
        """
        pass
