from abc import ABC, abstractmethod
import gc

class BaseModel(ABC):
    """Abstract base class enforcing load/unload lifecycles for pipeline models."""
    
    def __init__(self, device: str = "cpu", verbose: bool = False):
        self.device = device
        self.verbose = verbose
        self.model = None
        
    @abstractmethod
    def load_model(self):
        """Load weights, patterns, or setups into RAM/VRAM."""
        pass
        
    @abstractmethod
    def unload_model(self):
        """Unload models and release RAM/VRAM resource pools."""
        if self.model is not None:
            self.model = None
        gc.collect()
        
    @abstractmethod
    def predict(self, inputs, **kwargs):
        """Evaluate inputs and return predictions."""
        pass
        
    def __enter__(self):
        self.load_model()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.unload_model()
