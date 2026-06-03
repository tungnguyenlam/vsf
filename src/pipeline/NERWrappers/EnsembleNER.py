from typing import List

from src.pipeline.NERWrappers.BaseNERWrapper import BaseNERWrapper


class EnsembleNER(BaseNERWrapper):
    """Combines multiple NER wrappers and merges their predictions.

    Supports two strategies:
        - "union": Combine all predictions; for overlapping spans, keep the
          one with the highest confidence score.
        - "intersection": Only keep entities that are detected by at least
          two of the wrapped models (overlapping span + same entity type).

    Args:
        wrappers: List of BaseNERWrapper instances to ensemble.
        strategy: Merge strategy — "union" or "intersection".
    """

    def __init__(self, wrappers: List[BaseNERWrapper], strategy: str = "union"):
        if not wrappers:
            raise ValueError("EnsembleNER requires at least one wrapper.")
        self.wrappers = wrappers
        self.strategy = strategy

    @property
    def is_loaded(self) -> bool:
        return all(w.is_loaded for w in self.wrappers)

    def load(self):
        """Load all wrapped models."""
        for wrapper in self.wrappers:
            wrapper.load()

    def unload(self):
        """Unload all wrapped models."""
        for wrapper in self.wrappers:
            wrapper.unload()

    def predict_entities(self, text: str) -> List[dict]:
        """Run all wrappers and merge predictions according to the strategy."""
        all_predictions = []
        for wrapper in self.wrappers:
            preds = wrapper.predict_entities(text)
            all_predictions.append(preds)

        if self.strategy == "union":
            return self._merge_union(all_predictions)
        elif self.strategy == "intersection":
            return self._merge_intersection(all_predictions)
        else:
            raise ValueError(f"Unknown ensemble strategy: {self.strategy!r}")

    def _merge_union(self, all_predictions: List[List[dict]]) -> List[dict]:
        """Combine all predictions; keep highest-scoring for overlapping spans."""
        combined = []
        for preds in all_predictions:
            combined.extend(preds)

        if not combined:
            return combined

        # Sort by start position, then by score descending
        combined.sort(key=lambda x: (x["start"], -x["score"]))

        merged = [combined[0]]
        for pred in combined[1:]:
            last = merged[-1]
            # Overlap check: does this prediction start before the last one ends?
            if pred["start"] < last["end"]:
                # Keep the one with higher score
                if pred["score"] > last["score"]:
                    merged[-1] = pred
            else:
                merged.append(pred)

        return merged

    def _merge_intersection(self, all_predictions: List[List[dict]]) -> List[dict]:
        """Only keep entities confirmed by at least two wrappers.

        A prediction is confirmed if another wrapper produced an overlapping
        span with the same entity type.
        """
        if len(all_predictions) < 2:
            return all_predictions[0] if all_predictions else []

        # Check each prediction from the first wrapper against all others
        result = []
        for candidate in all_predictions[0]:
            confirmed = False
            for other_preds in all_predictions[1:]:
                for other in other_preds:
                    same_type = candidate["entity_type"] == other["entity_type"]
                    overlaps = (max(candidate["start"], other["start"])
                                < min(candidate["end"], other["end"]))
                    if same_type and overlaps:
                        confirmed = True
                        break
                if confirmed:
                    break
            if confirmed:
                result.append(candidate)

        # Also check predictions from other wrappers that the first missed
        first_set_spans = [(p["start"], p["end"]) for p in all_predictions[0]]
        for i in range(1, len(all_predictions)):
            for candidate in all_predictions[i]:
                # Skip if already covered by first wrapper's candidates
                already_found = any(
                    max(candidate["start"], s) < min(candidate["end"], e)
                    for s, e in first_set_spans
                )
                if already_found:
                    continue

                # Check against other wrappers (excluding current)
                confirmed = False
                for j in range(len(all_predictions)):
                    if j == i:
                        continue
                    for other in all_predictions[j]:
                        same_type = candidate["entity_type"] == other["entity_type"]
                        overlaps = (max(candidate["start"], other["start"])
                                    < min(candidate["end"], other["end"]))
                        if same_type and overlaps:
                            confirmed = True
                            break
                    if confirmed:
                        break
                if confirmed:
                    result.append(candidate)

        return result
