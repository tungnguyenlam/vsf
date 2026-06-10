from src.pipeline.Pipelines.Models import (
    BaselinePresidioPipeline,
    HybridRegexPipeline,
    RegexOnlyPipeline,
    RegexRecallPipeline,
    UndertheseaNerPipeline,
    UndertheseaRegexPipeline,
    UndertheseaRegexRecallPipeline,
)


PIPELINE_REGISTRY = {
    "baseline_presidio": BaselinePresidioPipeline,
    "regex_only": RegexOnlyPipeline,
    "regex_recall": RegexRecallPipeline,
    "underthesea_ner": UndertheseaNerPipeline,
    "underthesea_regex": UndertheseaRegexPipeline,
    "underthesea_regex_recall": UndertheseaRegexRecallPipeline,
    "hybrid_regex": HybridRegexPipeline,
}


def list_pipeline_names():
    return sorted(PIPELINE_REGISTRY)


def get_pipeline_class(name: str):
    try:
        return PIPELINE_REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(list_pipeline_names())
        raise ValueError(f"Unknown pipeline {name!r}. Available pipelines: {available}") from exc


def get_pipeline(name: str, **kwargs):
    return get_pipeline_class(name)(**kwargs)
