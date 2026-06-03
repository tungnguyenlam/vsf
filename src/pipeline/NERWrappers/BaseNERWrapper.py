from abc import ABC, abstractmethod
from typing import List


class BaseNERWrapper(ABC):
    """Abstract base class for NER model wrappers.

    All NER backends (HuggingFace transformers, spaCy, ensembles, etc.)
    implement this interface so they can be plugged into a
    DeepLearningRecognizer without any code changes.

    The predict_entities() method must return a list of dicts, each with:
        - entity_type (str): Standardized entity type (e.g. "PERSON", "LOCATION")
        - start (int): Character start offset in the original text
        - end (int): Character end offset in the original text
        - score (float): Confidence score between 0.0 and 1.0
        - word (str): The matched text span
    """

    @abstractmethod
    def load(self):
        """Load the model into memory."""
        pass

    @abstractmethod
    def unload(self):
        """Unload the model and free resources."""
        pass

    @abstractmethod
    def predict_entities(self, text: str) -> List[dict]:
        """Run NER inference on a text string.

        Args:
            text: The input text to analyze.

        Returns:
            List of entity dicts with keys: entity_type, start, end, score, word.
        """
        pass

    @property
    def is_loaded(self) -> bool:
        """Whether the model is currently loaded in memory."""
        return False
