from abc import ABC, abstractmethod
from typing import List

from presidio_analyzer import RecognizerResult


class BaseVerifier(ABC):
    """Abstract second-pass adjudicator over Presidio recognizer results.

    A verifier runs *after* the AnalyzerEngine has already resolved overlaps by
    score. It receives the surviving spans — each carrying provenance (which
    recognizer produced it and at what confidence) — and returns an adjudicated
    list: false positives dropped, mislabeled entity types corrected.

    Implementations should default to returning ``results`` unchanged on failure
    for interactive use, but may expose a strict mode for evaluation where
    configuration/routing errors should stop the run.
    """

    @abstractmethod
    def verify(
        self,
        text: str,
        results: List[RecognizerResult],
        *,
        language: str = "vi",
    ) -> List[RecognizerResult]:
        """Adjudicate ``results`` for ``text`` and return the kept/corrected spans."""
        raise NotImplementedError

    @staticmethod
    def source_of(result: RecognizerResult) -> str:
        """Best-effort recognizer name for a result (provenance)."""
        metadata = getattr(result, "recognition_metadata", None) or {}
        name = metadata.get(RecognizerResult.RECOGNIZER_NAME_KEY)
        if name:
            return name
        explanation = getattr(result, "analysis_explanation", None)
        if explanation is not None and getattr(explanation, "recognizer", None):
            return explanation.recognizer
        return "unknown"
