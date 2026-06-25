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


def test_makefile_smoke_pii_target_runs_end_to_end(tmp_path):
    # Run the actual CLI as a subprocess so `make smoke-pii` is exercised from
    # CI: a 5-row run on pii_masking_95k proves the real HF data path + the
    # regex_only pipeline agree on the script wrapper. Cheap, deterministic, no
    # NER model download.
    import subprocess

    metrics_path = tmp_path / "smoke_pii_metrics.json"
    result = subprocess.run(
        [
            "python",
            "scripts/evaluate_pipeline.py",
            "--pipeline",
            "regex_only",
            "--split",
            "train",
            "--limit",
            "5",
            "--no-log",
            "--log-path",
            "/tmp/smoke_pii_predictions.jsonl",
        ],
        check=True,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": ".", "PATH": __import__("os").environ["PATH"]},
    )

    metrics_path.write_text(result.stdout, encoding="utf-8")
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert payload["pipeline"] == "regex_only"
    assert payload["rows"] == 5
    assert "overall" in payload
    assert {"precision", "recall", "f1"} <= set(payload["overall"])


def test_pinned_pii_reproducer_is_deterministic(tmp_path):
    # The 500-row val manifest is the cheapest deterministic sample we can pin
    # for the PII report's regex_recall row. Two back-to-back runs must agree
    # byte-for-byte on the metrics the report cites; otherwise the report
    # numbers are no longer reproducible from the committed manifest.
    import subprocess
    from src.pipeline.Datasets import resolve_dataset_key

    manifest = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "data"
        / "sample_ids"
        / "pii_masking_95k__validation__writeup_pin_500.json"
    )
    assert manifest.exists(), f"pinned manifest missing: {manifest}"
    assert resolve_dataset_key("nguyenlamtung/pii-masking-95k-preencoded") == "pii_masking_95k"

    env = {"PYTHONPATH": ".", "PATH": __import__("os").environ["PATH"]}
    cmd = [
        "python",
        "scripts/evaluate_pipeline.py",
        "--pipeline",
        "regex_recall",
        "--split",
        "val",
        "--input-ids-file",
        str(manifest),
        "--no-log",
        "--log-path",
        str(tmp_path / "pinned.jsonl"),
    ]

    payloads = []
    for _ in range(2):
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
        payloads.append(json.loads(result.stdout))

    first, second = payloads
    assert first["rows"] == 500
    assert first.get("input_ids_matched") == 500
    assert first.get("input_ids_requested") == 500
    assert first["split"] == "val"
    assert first["pipeline"] == "regex_recall"
    # Only stable metric fields must be byte-identical between runs.
    assert first["overall"] == second["overall"]
    assert first["per_entity"] == second["per_entity"]


def test_pinned_pii_reproducer_pins_reported_metrics(tmp_path):
    # Pin a small set of regex_recall per-entity numbers on the 500-row val
    # sample. These are NOT the report's headline numbers (those come from the
    # full ~9500-row val set with NER), but they are the deterministic slice
    # `make reproduce-pii` recomputes. If the HF dataset is re-uploaded and the
    # slice moves, this test fails loudly so the report is updated deliberately
    # rather than silently.
    import subprocess

    manifest = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "data"
        / "sample_ids"
        / "pii_masking_95k__validation__writeup_pin_500.json"
    )
    env = {"PYTHONPATH": ".", "PATH": __import__("os").environ["PATH"]}
    result = subprocess.run(
        [
            "python",
            "scripts/evaluate_pipeline.py",
            "--pipeline",
            "regex_recall",
            "--split",
            "val",
            "--input-ids-file",
            str(manifest),
            "--no-log",
            "--log-path",
            str(tmp_path / "pinned.jsonl"),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    payload = json.loads(result.stdout)
    assert payload["rows"] == 500

    # Per-entity F1s to 4 decimal places. Update this block deliberately whenever
    # the HF dataset is re-uploaded or the pinned manifest is regenerated.
    expected_f1 = {
        "PHONE_NUMBER": 1.0,
        "IP_ADDRESS": 1.0,
        "EMAIL_ADDRESS": 1.0,
        "URL": 1.0,
        "CRYPTO": 0.9677,
        "LOCATION": 0.9361,
        "CREDIT_CARD": 0.9032,
        "DATE_TIME": 0.8225,
        "ID": 0.6686,
        "PERSON": 0.6626,
        "BANK_ACCOUNT": 0.6222,
        "ORGANIZATION": 0.6362,
    }
    for entity, expected in expected_f1.items():
        actual = round(payload["per_entity"][entity]["f1"], 4)
        assert actual == expected, (
            f"{entity} F1 drift: expected {expected}, got {actual}. "
            "If the HF dataset was re-uploaded or the manifest regenerated, "
            "update the pin deliberately and refresh the report table."
        )
