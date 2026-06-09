import re
from typing import Iterable, Iterator, List, Tuple

from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerRegistry
from presidio_analyzer.context_aware_enhancers import ContextAwareEnhancer
from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngine


VIETNAMESE_LANGUAGE = "vi"


class SimpleToken:
    def __init__(self, text: str):
        self.text = text

    def __len__(self):
        return len(self.text)


class NoOpNlpEngine(NlpEngine):
    """Minimal NLP engine for regex-first Vietnamese Presidio analyzers."""

    def __init__(self, supported_languages=None):
        self.supported_languages = supported_languages or [VIETNAMESE_LANGUAGE]
        self._loaded = False

    def load(self) -> None:
        self._loaded = True

    def is_loaded(self) -> bool:
        return self._loaded

    def process_text(self, text: str, language: str) -> NlpArtifacts:
        matches = list(re.finditer(r"\S+", text))
        tokens = [SimpleToken(match.group(0)) for match in matches]
        token_indices = [match.start() for match in matches]
        lemmas = [token.text.lower() for token in tokens]
        return NlpArtifacts(
            entities=[],
            tokens=tokens,
            tokens_indices=token_indices,
            lemmas=lemmas,
            nlp_engine=self,
            language=language,
        )

    def process_batch(
        self,
        texts: Iterable[str],
        language: str,
        batch_size: int = 1,
        n_process: int = 1,
        **kwargs,
    ) -> Iterator[Tuple[str, NlpArtifacts]]:
        for text in texts:
            yield text, self.process_text(text, language)

    def is_stopword(self, word: str, language: str) -> bool:
        return False

    def is_punct(self, word: str, language: str) -> bool:
        return bool(re.fullmatch(r"\W+", word))

    def get_supported_entities(self) -> List[str]:
        return []

    def get_supported_languages(self) -> List[str]:
        return list(self.supported_languages)


class NoContextAwareEnhancer(ContextAwareEnhancer):
    """Disable analyzer-level context boosting for regex-only offline runs."""

    def __init__(self):
        super().__init__(
            context_similarity_factor=0.0,
            min_score_with_context_similarity=0.0,
            context_prefix_count=0,
            context_suffix_count=0,
        )

    def enhance_using_context(
        self,
        text,
        raw_results,
        nlp_artifacts,
        recognizers,
        context=None,
    ):
        return raw_results


class NoOpRecognizer(EntityRecognizer):
    def __init__(self, supported_language: str = VIETNAMESE_LANGUAGE):
        super().__init__(
            supported_entities=["NOOP"],
            supported_language=supported_language,
            name="NoOpRecognizer",
        )

    def load(self) -> None:
        return None

    def analyze(self, text, entities, nlp_artifacts):
        return []


def create_vietnamese_analyzer(
    presidio_recognizers=None,
    *,
    log_decision_process: bool = False,
    context_aware_enhancer=None,
) -> AnalyzerEngine:
    recognizers = list(presidio_recognizers or [])
    if not recognizers:
        recognizers = [NoOpRecognizer()]

    registry = RecognizerRegistry(
        recognizers=recognizers,
        supported_languages=[VIETNAMESE_LANGUAGE],
    )
    return AnalyzerEngine(
        registry=registry,
        nlp_engine=NoOpNlpEngine([VIETNAMESE_LANGUAGE]),
        supported_languages=[VIETNAMESE_LANGUAGE],
        log_decision_process=log_decision_process,
        context_aware_enhancer=context_aware_enhancer or NoContextAwareEnhancer(),
    )
