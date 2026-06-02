from presidio_analyzer import PatternRecognizer, Pattern
from src.pipeline.Recognizers.BaseRecognizer import BaseRecognizer

class CustomPatternRecognizer(BaseRecognizer):
    """Modular wrapper for custom regex pattern-based recognizers."""
    
    def __init__(self, device: str = "cpu", verbose: bool = False):
        super().__init__(device=device, verbose=verbose)
        self.recognizers = []
        
    def build_patterns(self) -> list:
        phone_patterns = [
            Pattern(name="vn_phone", regex=r"\b(?:\+?84|0)(?:[ .-]?\d){8,11}\b", score=0.65),
        ]
        id_patterns = [
            Pattern(name="vn_id_9", regex=r"\b\d{9}\b", score=0.5),
            Pattern(name="vn_id_12", regex=r"\b\d{12}\b", score=0.5),
            Pattern(name="vn_tax_id", regex=r"\b\d{10}(?:-\d{3})?\b", score=0.4),
        ]
        address_patterns = [
            Pattern(
                name="vn_address_keyword",
                regex=r"(?i)\b(?:so|so nha|duong|pho|phuong|xa|quan|huyen|thanh pho|tp|tinh)\b[^,\n]{0,40}",
                score=0.35,
            ),
        ]
        return [
            PatternRecognizer(supported_entity="PHONE_NUMBER", patterns=phone_patterns),
            PatternRecognizer(supported_entity="ID", patterns=id_patterns),
            PatternRecognizer(supported_entity="LOCATION", patterns=address_patterns),
        ]
        
    def load_model(self):
        if not self.recognizers:
            self.recognizers = self.build_patterns()
            self.model = self.recognizers
            
    def unload_model(self):
        self.recognizers = []
        super().unload_model()
        
    def register_to_analyzer(self, analyzer_engine):
        self.load_model()
        for recognizer in self.recognizers:
            analyzer_engine.registry.add_recognizer(recognizer)
            
    def predict(self, inputs, **kwargs):
        # CustomPatternRecognizer is designed to plug directly into a Presidio analyzer.
        pass
