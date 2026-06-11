import json

import pandas as pd
from presidio_analyzer import AnalysisExplanation, RecognizerResult

from src.pipeline.Evaluator import PIIEvaluator
from src.pipeline.BasePipeline import PIIPipeline
import src.pipeline.Pipelines.evaluation as pipeline_evaluation
from src.pipeline.Pipelines import (
    BaselinePresidioPipeline,
    HybridRegexPipeline,
    RegexOnlyPipeline,
    RegexRecallPipeline,
    RegexRecallViePiiPipeline,
    UndertheseaNerPipeline,
    UndertheseaRegexPipeline,
    UndertheseaRegexRecallPipeline,
    UndertheseaRegexRecallResolvedPipeline,
    get_pipeline,
    get_pipeline_class,
)
from src.pipeline.Pipelines.evaluation import PipelineEvaluationConfig, PipelineEvaluationRunner
from src.pipeline.NERWrappers.UndertheseaNER import UndertheseaNER
from src.pipeline.Recognizers.CustomPatternRecognizer import CustomPatternRecognizer
from src.pipeline.Resolvers import DeterministicResolver


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_pipeline_registry_returns_expected_classes():
    assert get_pipeline_class("baseline_presidio") is BaselinePresidioPipeline
    assert get_pipeline_class("regex_only") is RegexOnlyPipeline
    assert get_pipeline_class("regex_recall") is RegexRecallPipeline
    assert get_pipeline_class("regex_recall_vie_pii") is RegexRecallViePiiPipeline
    assert get_pipeline_class("underthesea_ner") is UndertheseaNerPipeline
    assert get_pipeline_class("underthesea_regex") is UndertheseaRegexPipeline
    assert get_pipeline_class("underthesea_regex_recall") is UndertheseaRegexRecallPipeline
    assert get_pipeline_class("underthesea_regex_recall_resolved") is UndertheseaRegexRecallResolvedPipeline
    assert get_pipeline_class("hybrid_regex") is HybridRegexPipeline
    assert isinstance(get_pipeline("regex_recall", prediction_log_path=None), RegexRecallPipeline)
    assert isinstance(get_pipeline("regex_recall_vie_pii", prediction_log_path=None), RegexRecallViePiiPipeline)
    assert isinstance(get_pipeline("underthesea_ner", prediction_log_path=None), UndertheseaNerPipeline)
    assert isinstance(get_pipeline("underthesea_regex", prediction_log_path=None), UndertheseaRegexPipeline)
    assert isinstance(
        get_pipeline("underthesea_regex_recall", prediction_log_path=None),
        UndertheseaRegexRecallPipeline,
    )
    assert isinstance(
        get_pipeline("underthesea_regex_recall_resolved", prediction_log_path=None),
        UndertheseaRegexRecallResolvedPipeline,
    )
    assert isinstance(get_pipeline("regex_only", prediction_log_path=None), RegexOnlyPipeline)
    assert RegexOnlyPipeline.__module__ == "src.pipeline.Pipelines.Models.RegexOnlyPipeline"


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


def test_underthesea_wrapper_returns_original_offsets():
    text = "Tôi là Nguyễn Văn An ở Hà Nội."
    results = UndertheseaNER(min_score=0.0).predict_entities(text)

    by_text = {result["word"]: result for result in results}
    assert by_text["Nguyễn Văn An"]["entity_type"] == "PERSON"
    assert text[by_text["Nguyễn Văn An"]["start"]:by_text["Nguyễn Văn An"]["end"]] == "Nguyễn Văn An"
    assert by_text["Hà Nội"]["entity_type"] == "LOCATION"


def test_regex_pipeline_rejects_bare_numeric_false_positives():
    text = "Số dư khả dụng: 2766000000 CL$. Mã đơn hàng 987654321 đã giao."
    results = get_pipeline("regex_only", prediction_log_path=None).predict(text)

    assert results == []


def test_regex_pipeline_uses_context_for_bank_and_id_numbers():
    text = "STK 123456789 tại Vietcombank. Số CCCD: 012345678901."
    results = get_pipeline("regex_only", prediction_log_path=None).predict(text)
    by_type = {result.entity_type: text[result.start:result.end] for result in results}

    assert by_type["BANK_ACCOUNT"] == "123456789"
    assert by_type["ID"] == "012345678901"


def test_regex_pipeline_covers_contextual_date_location_person_and_org():
    text = (
        "Họ và tên: Nguyễn Văn An Ngày sinh: 12/05/1990 "
        "Địa chỉ: Số 12, Đường Lê Lợi, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh "
        "Tên tổ chức: Đại học Huế Mã giao dịch: PAYRT612345 Hộ chiếu số C6967287"
    )
    results = get_pipeline("regex_only", prediction_log_path=None).predict(text)
    spans_by_type = {}
    for result in results:
        spans_by_type.setdefault(result.entity_type, set()).add(text[result.start:result.end])

    assert "Nguyễn Văn An" in spans_by_type["PERSON"]
    assert "12/05/1990" in spans_by_type["DATE_TIME"]
    assert "Đại học Huế" in spans_by_type["ORGANIZATION"]
    assert {"Số 12", "Đường Lê Lợi", "Phường Bến Nghé", "Quận 1", "TP. Hồ Chí Minh"}.issubset(
        spans_by_type["LOCATION"]
    )
    assert {"PAYRT612345", "C6967287"}.issubset(spans_by_type["ID"])


def test_deterministic_resolver_drops_underthesea_person_in_org_context():
    text = "Bệnh viện Bạch Mai tiếp nhận hồ sơ. Họ và tên: Nguyễn Văn An."
    hospital_start = text.index("Bạch Mai")
    person_start = text.index("Nguyễn Văn An")
    results = [
        _underthesea_person(hospital_start, hospital_start + len("Bạch Mai")),
        _underthesea_person(person_start, person_start + len("Nguyễn Văn An")),
    ]

    resolved = DeterministicResolver().resolve(text, results)

    assert [text[result.start:result.end] for result in resolved] == ["Nguyễn Văn An"]


def _underthesea_person(start, end):
    explanation = AnalysisExplanation(
        recognizer="DeepLearning_UndertheseaNER",
        original_score=0.8,
        textual_explanation="Detected by UndertheseaNER",
    )
    result = RecognizerResult(
        entity_type="PERSON",
        start=start,
        end=end,
        score=0.8,
        analysis_explanation=explanation,
    )
    result.recognition_metadata = {
        RecognizerResult.RECOGNIZER_NAME_KEY: "DeepLearning_UndertheseaNER",
    }
    return result


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


def test_pipeline_evaluation_writes_metrics_and_predictions_to_run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_evaluation, "DEFAULT_EVALUATION_OUTPUT_DIR", tmp_path / "evaluations")
    runner = PipelineEvaluationRunner(
        PipelineEvaluationConfig(
            pipeline="regex_only",
            dataset="pii_masking_95k",
            split="train_val",
        )
    )
    runner.run_id = "eval-run-001"
    runner._load_dataset = lambda: pd.DataFrame(
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

    output = runner.run()

    run_dir = tmp_path / "evaluations" / "regex_only" / "eval-run-001"
    metrics_path = run_dir / "metrics.json"
    log_path = run_dir / "predictions.jsonl"

    assert output["run_id"] == "eval-run-001"
    assert output["output_dir"] == str(run_dir)
    assert output["metrics_path"] == str(metrics_path)
    assert output["log_path"] == str(log_path)
    assert metrics_path.exists()
    assert log_path.exists()

    saved_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert saved_metrics == output
    assert read_jsonl(log_path)[0]["run_id"] == "eval-run-001"


def test_pipeline_evaluation_writes_metrics_when_prediction_logging_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_evaluation, "DEFAULT_EVALUATION_OUTPUT_DIR", tmp_path / "evaluations")
    runner = PipelineEvaluationRunner(
        PipelineEvaluationConfig(
            pipeline="regex_only",
            dataset="pii_masking_95k",
            split="train_val",
            no_log=True,
        )
    )
    runner.run_id = "eval-no-log"
    runner._load_dataset = lambda: pd.DataFrame(
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

    output = runner.run()

    metrics_path = tmp_path / "evaluations" / "regex_only" / "eval-no-log" / "metrics.json"
    assert output["log_path"] is None
    assert output["metrics_path"] == str(metrics_path)
    assert metrics_path.exists()
