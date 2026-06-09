import json

import pandas as pd

from src.pipeline.Evaluator import PIIEvaluator
from src.pipeline.BasePipeline import PIIPipeline
from src.pipeline.Pipelines import (
    BaselinePresidioPipeline,
    HybridRegexPipeline,
    RegexOnlyPipeline,
    get_pipeline,
    get_pipeline_class,
)
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_pipeline_registry_returns_expected_classes():
    assert get_pipeline_class("baseline_presidio") is BaselinePresidioPipeline
    assert get_pipeline_class("regex_only") is RegexOnlyPipeline
    assert get_pipeline_class("hybrid_regex") is HybridRegexPipeline
    assert isinstance(get_pipeline("regex_only", prediction_log_path=None), RegexOnlyPipeline)


def test_lightweight_vietnamese_pipelines_predict_small_text():
    text = "Liên hệ qua email user@example.com hoặc số 0912345678."

    for name in ["baseline_presidio", "regex_only", "hybrid_regex"]:
        pipeline = get_pipeline(name, prediction_log_path=None)
        results = pipeline.predict(text)
        assert isinstance(results, list)
        assert pipeline.default_language == "vi"

    regex_results = get_pipeline("regex_only", prediction_log_path=None).predict(text)
    entity_types = {result.entity_type for result in regex_results}
    assert "EMAIL_ADDRESS" in entity_types
    assert "PHONE_NUMBER" in entity_types


def test_bare_pipeline_fallback_is_vietnamese_offline_regex():
    pipeline = PIIPipeline(
        recognizers=[CustomPatternRecognizer()],
        prediction_log_path=None,
    )

    results = pipeline.predict("Email user@example.com")

    assert pipeline.default_language == "vi"
    assert {result.entity_type for result in results} == {"EMAIL_ADDRESS"}


def test_evaluator_works_with_pipeline_class():
    df_eval = pd.DataFrame(
        [
            {
                "input_id": "row-001",
                "source_text": "Email user@example.com",
                "privacy_mask": [
                    {"start": 6, "end": 22, "label": "DIA_CHI_EMAIL"},
                ],
            }
        ]
    )
    pipeline = get_pipeline("regex_only", prediction_log_path=None)

    overall, per_entity = PIIEvaluator().evaluate_presidio(
        df_eval,
        pipeline,
        language="vi",
        use_type_mapping=True,
        return_per_entity=True,
    )

    assert overall["tp"] == 1
    assert overall["fp"] == 0
    assert overall["fn"] == 0
    assert per_entity["EMAIL_ADDRESS"]["tp"] == 1


def test_evaluator_pipeline_logging_records_ids_results_and_ground_truth(tmp_path):
    log_path = tmp_path / "predictions.jsonl"
    df_eval = pd.DataFrame(
        [
            {
                "input_id": "row-001",
                "source_text": "Email user@example.com",
                "privacy_mask": [
                    {"start": 6, "end": 22, "label": "DIA_CHI_EMAIL"},
                ],
            }
        ]
    )
    pipeline = get_pipeline(
        "regex_only",
        prediction_log_path=log_path,
        run_id="run-registry-test",
    )

    PIIEvaluator().evaluate_presidio(
        df_eval,
        pipeline,
        language="vi",
        score_threshold=0.4,
        use_type_mapping=True,
    )

    records = read_jsonl(log_path)
    assert len(records) == 1
    assert records[0]["pipeline_name"] == "regex_only"
    assert records[0]["run_id"] == "run-registry-test"
    assert records[0]["input_id"] == "row-001"
    assert records[0]["language"] == "vi"
    assert records[0]["score_threshold"] == 0.4
    assert records[0]["ground_truth"] == [
        {"start": 6, "end": 22, "label": "DIA_CHI_EMAIL"},
    ]
    assert records[0]["results"][0]["entity_type"] == "EMAIL_ADDRESS"
