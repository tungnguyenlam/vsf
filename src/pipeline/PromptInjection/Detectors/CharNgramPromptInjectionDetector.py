import math
import re
from collections import Counter

from src.pipeline.PromptInjection.Detectors.BasePromptInjectionDetector import (
    BasePromptInjectionDetector,
)
from src.pipeline.PromptInjection.Models import PromptInjectionResult


class CharNgramPromptInjectionDetector(BasePromptInjectionDetector):
    """Trainable character-ngram Naive Bayes baseline for prompt injection."""

    def __init__(
        self,
        min_n: int = 3,
        max_n: int = 5,
        warn_threshold: float = 0.5,
        block_threshold: float = 0.85,
        smoothing: float = 1.0,
        device: str = "cpu",
        verbose: bool = False,
    ):
        super().__init__(device=device, verbose=verbose)
        self.min_n = min_n
        self.max_n = max_n
        self.warn_threshold = warn_threshold
        self.block_threshold = block_threshold
        self.smoothing = smoothing
        self.class_doc_counts = Counter()
        self.class_feature_counts = {0: Counter(), 1: Counter()}
        self.class_total_features = Counter()
        self.vocabulary = set()

    def load_model(self):
        self.model = {
            "class_doc_counts": self.class_doc_counts,
            "class_feature_counts": self.class_feature_counts,
            "class_total_features": self.class_total_features,
            "vocabulary": self.vocabulary,
        }

    def unload_model(self):
        self.model = None
        super().unload_model()

    def fit(self, examples):
        self.class_doc_counts = Counter()
        self.class_feature_counts = {0: Counter(), 1: Counter()}
        self.class_total_features = Counter()
        self.vocabulary = set()

        for example in examples:
            label = int(example.label)
            features = self._extract_features(example.text)
            self.class_doc_counts[label] += 1
            self.class_feature_counts[label].update(features)
            self.class_total_features[label] += sum(features.values())
            self.vocabulary.update(features.keys())

        self.load_model()
        return self

    def predict(self, inputs, **kwargs):
        if isinstance(inputs, str):
            return self.detect(inputs)
        if hasattr(inputs, "__iter__"):
            return [self.detect(text) for text in inputs]
        return self._result([], 0.0, 0.0)

    def detect(self, text: str) -> PromptInjectionResult:
        if sum(self.class_doc_counts.values()) == 0:
            raise RuntimeError("Detector is not trained. Call fit() before predict().")

        features = self._extract_features(text)
        positive_score, evidence = self._positive_probability(features)
        return self._result(features, positive_score, evidence)

    def _normalize(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text.strip().lower())
        return f" {normalized} "

    def _extract_features(self, text: str) -> Counter:
        normalized = self._normalize(text)
        features = Counter()
        for n in range(self.min_n, self.max_n + 1):
            if len(normalized) < n:
                continue
            for index in range(len(normalized) - n + 1):
                gram = normalized[index : index + n]
                features[gram] += 1
        return features

    def _positive_probability(self, features: Counter) -> tuple[float, list[dict]]:
        total_docs = sum(self.class_doc_counts.values())
        if total_docs == 0:
            return 0.0, []

        vocab_size = max(1, len(self.vocabulary))
        log_probs = {}
        contributions = []
        for label in (0, 1):
            prior = (self.class_doc_counts[label] + self.smoothing) / (
                total_docs + 2 * self.smoothing
            )
            log_prob = math.log(prior)
            denom = self.class_total_features[label] + self.smoothing * vocab_size
            for gram, count in features.items():
                numerator = self.class_feature_counts[label][gram] + self.smoothing
                weight = count * math.log(numerator / denom)
                log_prob += weight
                if label == 1 and gram in self.vocabulary:
                    contributions.append(
                        {
                            "ngram": gram,
                            "count": count,
                            "positive_count": self.class_feature_counts[1][gram],
                            "negative_count": self.class_feature_counts[0][gram],
                            "weight": round(weight, 6),
                        }
                    )
            log_probs[label] = log_prob

        max_log = max(log_probs.values())
        exp_negative = math.exp(log_probs[0] - max_log)
        exp_positive = math.exp(log_probs[1] - max_log)
        positive_probability = exp_positive / (exp_positive + exp_negative)

        evidence = [
            {
                "feature": item["ngram"],
                "count": item["count"],
                "positive_count": item["positive_count"],
                "negative_count": item["negative_count"],
                "weight": item["weight"],
            }
            for item in sorted(contributions, key=lambda item: item["weight"], reverse=True)[:8]
            if item["positive_count"] > item["negative_count"]
        ]
        return round(positive_probability, 6), evidence

    def _result(
        self,
        features: Counter,
        score: float,
        evidence: list[dict],
    ) -> PromptInjectionResult:
        if score >= self.block_threshold:
            action = "block"
        elif score >= self.warn_threshold:
            action = "review"
        else:
            action = "allow"

        categories = ["model_based"]
        matched_rules = []
        if evidence:
            matched_rules = [f"char_ngram:{item['feature']}" for item in evidence[:3]]

        return PromptInjectionResult(
            is_injection=score >= self.warn_threshold,
            score=score,
            action=action,
            matched_rules=matched_rules,
            categories=categories,
            evidence=evidence,
        )
