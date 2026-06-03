import copy
import gc
import logging
from typing import List, Optional

from src.pipeline.NERWrappers.BaseNERWrapper import BaseNERWrapper

logger = logging.getLogger(__name__)

DEFAULT_LABEL_MAPPING = {
    "PER": "PERSON",
    "LOC": "LOCATION",
    "ORG": "ORGANIZATION",
    "MISC": "MISC",
}


class HFTransformersNER(BaseNERWrapper):
    """Wraps a HuggingFace token-classification pipeline for NER.

    Loads a model directly using transformers.pipeline("ner", ...) and runs
    inference independently of Presidio's NLP engine. This means it works
    correctly alongside a spaCy-backed AnalyzerEngine.

    Args:
        model_id: HuggingFace model identifier (e.g. "NlpHUST/ner-vietnamese-electra-base").
        label_mapping: Dict mapping model labels to standardized Presidio entity types.
        aggregation_strategy: HuggingFace aggregation strategy for sub-word tokens.
        chunk_size: Maximum character length per inference chunk.
        chunk_overlap: Number of overlapping characters between chunks.
        device: Device index for inference (0 for GPU, -1 for CPU, None for auto-detect).
    """

    def __init__(
        self,
        model_id: str = "NlpHUST/ner-vietnamese-electra-base",
        label_mapping: dict = None,
        aggregation_strategy: str = "simple",
        chunk_size: int = 512,
        chunk_overlap: int = 40,
        device=None,
    ):
        self.model_id = model_id
        self.label_mapping = label_mapping or DEFAULT_LABEL_MAPPING
        self.aggregation_strategy = aggregation_strategy
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.device = device
        self._pipeline = None

    @property
    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def load(self):
        """Load the HuggingFace model and tokenizer into a token-classification pipeline."""
        if self._pipeline is not None:
            return

        from transformers import (
            AutoTokenizer,
            AutoModelForTokenClassification,
            pipeline,
        )

        # Auto-detect device if not specified
        device_val = self.device
        if device_val is None:
            try:
                import torch
                device_val = 0 if torch.cuda.is_available() else -1
            except ImportError:
                device_val = -1

        logger.info(f"Loading HuggingFace NER model: {self.model_id} (device={device_val})")

        tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        model = AutoModelForTokenClassification.from_pretrained(self.model_id)

        self._pipeline = pipeline(
            "ner",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy=self.aggregation_strategy,
            device=device_val,
        )

    def unload(self):
        """Unload the model and free GPU/CPU memory."""
        self._pipeline = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()

    def _map_label(self, label: str) -> Optional[str]:
        """Map a model-output label to a standardized Presidio entity type.

        Handles B-/I- prefixed labels (e.g. "B-PER" -> "PERSON") and
        passes through labels that are already in the target vocabulary.
        """
        clean_label = label
        if label.startswith(("B-", "I-")):
            clean_label = label[2:]

        # Check explicit mapping
        mapped = self.label_mapping.get(clean_label)
        if mapped:
            return mapped

        # Already a valid target label?
        if clean_label in self.label_mapping.values():
            return clean_label

        # Return as-is (caller can filter if needed)
        return clean_label

    def predict_entities(self, text: str) -> List[dict]:
        """Run NER inference on text, returning standardized entity dicts."""
        if self._pipeline is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        if not text or not text.strip():
            return []

        # Run inference (with chunking for long texts)
        if len(text) <= self.chunk_size:
            raw_predictions = self._pipeline(text)
        else:
            raw_predictions = self._chunked_predict(text)

        # Convert to standardized format
        results = []
        for pred in raw_predictions:
            entity_group = pred.get("entity_group", pred.get("entity", ""))
            mapped_type = self._map_label(entity_group)

            if mapped_type is None or mapped_type == "O":
                continue

            results.append({
                "entity_type": mapped_type,
                "start": pred["start"],
                "end": pred["end"],
                "score": float(pred["score"]),
                "word": pred.get("word", text[pred["start"]:pred["end"]]),
            })

        return results

    def _chunked_predict(self, text: str) -> List[dict]:
        """Split text into overlapping chunks, run inference, and merge predictions."""
        predictions = []
        text_length = len(text)
        step = max(1, self.chunk_size - self.chunk_overlap)

        for chunk_start in range(0, text_length, step):
            chunk_end = min(chunk_start + self.chunk_size, text_length)
            chunk_text = text[chunk_start:chunk_end]

            chunk_preds = self._pipeline(chunk_text)

            # Align offsets to the original text
            for pred in chunk_preds:
                aligned = copy.deepcopy(pred)
                aligned["start"] += chunk_start
                aligned["end"] += chunk_start
                predictions.append(aligned)

            if chunk_end >= text_length:
                break

        # Remove duplicates from overlapping regions
        predictions = self._deduplicate(predictions)
        return predictions

    def _deduplicate(self, predictions: List[dict]) -> List[dict]:
        """Remove duplicate predictions from overlapping chunks.

        Keeps the highest-scoring prediction when two spans overlap.
        """
        if not predictions:
            return predictions

        # Sort by start position, then by score descending
        predictions.sort(key=lambda x: (x["start"], -x["score"]))

        deduplicated = [predictions[0]]
        for pred in predictions[1:]:
            last = deduplicated[-1]
            # Check overlap
            overlap_start = max(pred["start"], last["start"])
            overlap_end = min(pred["end"], last["end"])
            if overlap_start < overlap_end:
                # Overlapping — keep the one with higher score
                if pred["score"] > last["score"]:
                    deduplicated[-1] = pred
            else:
                deduplicated.append(pred)

        return deduplicated
