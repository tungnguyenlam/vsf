import gc
from typing import List

from src.pipeline.NERWrappers.BaseNERWrapper import BaseNERWrapper

DEFAULT_SPACY_LABEL_MAPPING = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
    "ORG": "ORGANIZATION",
    "NORP": "ORGANIZATION",
    "MISC": "MISC",
}


class SpacyNER(BaseNERWrapper):
    """Wraps a standalone spaCy model for NER entity extraction.

    This runs spaCy's NER independently from Presidio's NLP engine,
    so it can be used as a NER wrapper inside DeepLearningRecognizer
    alongside (or instead of) a HuggingFace model.

    Args:
        model_name: spaCy model identifier (e.g. "xx_ent_wiki_sm", "en_core_web_sm").
        label_mapping: Dict mapping spaCy entity labels to Presidio entity types.
    """

    def __init__(self, model_name: str = "xx_ent_wiki_sm", label_mapping: dict = None):
        self.model_name = model_name
        self.label_mapping = label_mapping or DEFAULT_SPACY_LABEL_MAPPING
        self._nlp = None

    @property
    def is_loaded(self) -> bool:
        return self._nlp is not None

    def load(self):
        """Load the spaCy model into memory."""
        if self._nlp is not None:
            return
        import spacy
        self._nlp = spacy.load(self.model_name)

    def unload(self):
        """Unload the spaCy model and free memory."""
        self._nlp = None
        gc.collect()

    def predict_entities(self, text: str) -> List[dict]:
        """Run spaCy NER on text and return standardized entity dicts.

        Note: spaCy does not provide per-entity confidence scores,
        so all scores are set to 0.85 as a reasonable default.
        """
        if self._nlp is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        if not text or not text.strip():
            return []

        doc = self._nlp(text)
        results = []
        for ent in doc.ents:
            mapped = self.label_mapping.get(ent.label_, ent.label_)
            results.append({
                "entity_type": mapped,
                "start": ent.start_char,
                "end": ent.end_char,
                "score": 0.85,
                "word": ent.text,
            })
        return results
