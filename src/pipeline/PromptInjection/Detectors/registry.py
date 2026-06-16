from src.pipeline.PromptInjection.Detectors.CharNgramPromptInjectionDetector import (
    CharNgramPromptInjectionDetector,
)
from src.pipeline.PromptInjection.Detectors.RuleBasedPromptInjectionDetector import (
    RuleBasedPromptInjectionDetector,
)


DETECTOR_REGISTRY = {
    "rule_based_prompt_injection": RuleBasedPromptInjectionDetector,
    "char_ngram_prompt_injection": CharNgramPromptInjectionDetector,
}


def list_prompt_injection_detector_names() -> list[str]:
    return sorted(DETECTOR_REGISTRY)


def get_prompt_injection_detector(name: str, **kwargs):
    try:
        detector_cls = DETECTOR_REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(list_prompt_injection_detector_names())
        raise ValueError(
            f"Unknown prompt-injection detector {name!r}. Available detectors: {available}"
        ) from exc
    return detector_cls(**kwargs)
