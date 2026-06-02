import inspect
from src.pipeline.Recognizers.BaseRecognizer import BaseRecognizer

DEFAULT_TRANSFORMER_MODEL_ID = "NlpHUST/ner-vietnamese-electra-base"
DEFAULT_TRANSFORMER_LABEL_MAPPING = {
    "PER": "PERSON",
    "LOC": "LOCATION",
    "ORG": "ORGANIZATION",
    "MISC": "MISC",
}

class TransformersRecognizer(BaseRecognizer):
    """Modular wrapper for Hugging Face transformer-based entity recognizers in Presidio."""
    
    def __init__(
        self,
        model_id: str = DEFAULT_TRANSFORMER_MODEL_ID,
        label_mapping: dict = None,
        lang_code: str = "vi",
        device: str = "cpu",
        verbose: bool = False
    ):
        super().__init__(device=device, verbose=verbose)
        self.model_id = model_id
        self.label_mapping = label_mapping or DEFAULT_TRANSFORMER_LABEL_MAPPING
        self.lang_code = lang_code
        self.recognizer = None
        
    def load_model(self):
        if self.recognizer is not None:
            return
            
        transformers_cls = None
        try:
            from presidio_analyzer.predefined_recognizers import TransformersRecognizer as HFRec
            transformers_cls = HFRec
        except Exception:
            try:
                from presidio_analyzer import TransformersRecognizer as HFRec
                transformers_cls = HFRec
            except Exception:
                transformers_cls = None
                
        if transformers_cls is None:
            if self.verbose:
                print("TransformersRecognizer not available; skipping.")
            return
            
        try:
            sig = inspect.signature(transformers_cls.__init__)
            params = sig.parameters
            
            init_kwargs = {}
            
            # Model parameter setups
            if "model_name" in params:
                init_kwargs["model_name"] = self.model_id
            elif "model_id" in params:
                init_kwargs["model_id"] = self.model_id
            elif "model_path" in params:
                init_kwargs["model_path"] = self.model_id
                
            if "supported_entities" in params:
                init_kwargs["supported_entities"] = list(self.label_mapping.values())
                
            if "label_mapping" in params:
                init_kwargs["label_mapping"] = self.label_mapping
                
            if "supported_language" in params:
                init_kwargs["supported_language"] = self.lang_code
            elif "language" in params:
                init_kwargs["language"] = self.lang_code
                
            try:
                self.recognizer = transformers_cls(**init_kwargs)
            except TypeError as e:
                if self.verbose:
                    print(f"TransformersRecognizer init failed with model parameters: {e}. Retrying without model arguments...")
                filtered_kwargs = {k: v for k, v in init_kwargs.items() if k not in ["model_name", "model_id", "model_path"]}
                self.recognizer = transformers_cls(**filtered_kwargs)
                
            self.model = self.recognizer
        except Exception as exc:
            print(f"TransformersRecognizer init failed: {exc}")
            
    def unload_model(self):
        self.recognizer = None
        # Safely attempt torch empty cache to free GPU memory
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        super().unload_model()
        
    def register_to_analyzer(self, analyzer_engine):
        self.load_model()
        if self.recognizer is not None:
            analyzer_engine.registry.add_recognizer(self.recognizer)
            
    def predict(self, inputs, **kwargs):
        # Custom transformers detection runs inside the Presidio analysis step.
        pass
