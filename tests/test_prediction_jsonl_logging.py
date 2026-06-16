import json

from presidio_analyzer import AnalysisExplanation, RecognizerResult

import src.pipeline.BasePipeline as base_pipeline
from src.pipeline.BasePipeline import PIIPipeline
from src.pipeline.Resolvers import DeterministicResolver


class FakeAnalyzer:
    def __init__(self):
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        text = kwargs["text"]
        start = text.find("user@example.com")
        if start == -1:
            return []

        explanation = None
        metadata = None
        if kwargs.get("return_decision_process"):
            explanation = AnalysisExplanation(
                recognizer="email_pattern",
                original_score=0.55,
                pattern_name="email_pattern",
                pattern=r"\S+@\S+",
                validation_result=None,
                textual_explanation="matched email",
            )
            explanation.score = 0.9
            explanation.score_context_improvement = 0.35
            explanation.supportive_context_word = "email"
            metadata = {"recognizer_name": "email_pattern"}

        return [
            RecognizerResult(
                entity_type="EMAIL_ADDRESS",
                start=start,
                end=start + len("user@example.com"),
                score=0.9,
                analysis_explanation=explanation,
                recognition_metadata=metadata,
            )
        ]


class FakeUndertheseaPersonAnalyzer:
    def __init__(self):
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        text = kwargs["text"]
        start = text.index("Bạch Mai")
        explanation = AnalysisExplanation(
            recognizer="DeepLearning_UndertheseaNER",
            original_score=0.8,
            textual_explanation="Detected by UndertheseaNER",
        )
        result = RecognizerResult(
            entity_type="PERSON",
            start=start,
            end=start + len("Bạch Mai"),
            score=0.8,
            analysis_explanation=explanation,
        )
        result.recognition_metadata = {
            RecognizerResult.RECOGNIZER_NAME_KEY: "DeepLearning_UndertheseaNER",
        }
        return [result]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_default_log_path_writes_to_output_folder(tmp_path, monkeypatch):
    log_dir = tmp_path / "output" / "predictions"
    monkeypatch.setattr(base_pipeline, "DEFAULT_PREDICTION_LOG_DIR", log_dir)

    pipeline = PIIPipeline(analyzer=FakeAnalyzer(), run_id="run-default")

    pipeline.predict("email user@example.com", language="vi")

    log_path = log_dir / "run-default" / "predictions.jsonl"
    records = read_jsonl(log_path)
    assert len(records) == 1
    assert records[0]["run_id"] == "run-default"
    assert records[0]["pipeline_name"] == "pii_pipeline"


def test_logging_can_be_disabled_explicitly():
    analyzer = FakeAnalyzer()
    pipeline = PIIPipeline(analyzer=analyzer, prediction_log_path=None)

    results = pipeline.predict("email user@example.com", language="vi", score_threshold=0.4)

    assert len(results) == 1
    assert "return_decision_process" not in analyzer.calls[0]
    assert results[0].entity_type == "EMAIL_ADDRESS"


def test_single_input_writes_jsonl_record(tmp_path):
    log_path = tmp_path / "audit" / "predictions.jsonl"
    pipeline = PIIPipeline(
        analyzer=FakeAnalyzer(),
        prediction_log_path=log_path,
        pipeline_name="regex_only",
        run_id="run-001",
    )

    pipeline.predict(
        "email user@example.com",
        language="vi",
        score_threshold=0.4,
        input_ids="row-001",
        ground_truth=[{"entity_type": "EMAIL_ADDRESS"}],
    )

    records = read_jsonl(log_path)
    assert len(records) == 1
    record = records[0]
    assert record["record_version"] == 2
    assert record["run_id"] == "run-001"
    assert record["pipeline_name"] == "regex_only"
    assert record["input_id"] == "row-001"
    assert record["language"] == "vi"
    assert record["score_threshold"] == 0.4
    assert record["source_text"] is None
    assert record["ground_truth"] == [{"entity_type": "EMAIL_ADDRESS"}]
    assert record["anonymized_text"] == "email <EMAIL_ADDRESS>"
    assert record["resolver_audit"] is None

    result = record["results"][0]
    assert result["entity_type"] == "EMAIL_ADDRESS"
    assert result["text"] == "user@example.com"
    assert result["recognizer"] == "email_pattern"
    assert result["pattern"] == "email_pattern"
    assert result["original_score"] == 0.55
    assert result["explanation_score"] == 0.9
    assert result["score_context_improvement"] == 0.35
    assert result["supportive_context"] == "email"
    assert result["validation"] is None

    readable_path = log_path.with_suffix(".readable.json")
    readable_records = json.loads(readable_path.read_text(encoding="utf-8"))
    assert readable_records == records
    assert "\n  {" in readable_path.read_text(encoding="utf-8")

    audit_text = log_path.with_suffix(".audit.md").read_text(encoding="utf-8")
    assert "# PII Prediction Audit" in audit_text
    assert "Final Spans" in audit_text
    assert "user@example.com" in audit_text


def test_batch_input_writes_one_record_per_input(tmp_path):
    log_path = tmp_path / "predictions.jsonl"
    pipeline = PIIPipeline(
        analyzer=FakeAnalyzer(),
        prediction_log_path=log_path,
        pipeline_name="batch_pipeline",
        run_id="run-002",
    )

    pipeline.predict(
        ["email user@example.com", "no pii here"],
        language="vi",
        input_ids=["row-001", "row-002"],
        ground_truth=[[{"label": "EMAIL"}], []],
    )

    records = read_jsonl(log_path)
    assert len(records) == 2
    assert [record["input_id"] for record in records] == ["row-001", "row-002"]
    assert [len(record["results"]) for record in records] == [1, 0]
    assert [record["ground_truth"] for record in records] == [[{"label": "EMAIL"}], []]


def test_detected_text_can_be_disabled(tmp_path):
    log_path = tmp_path / "predictions.jsonl"
    pipeline = PIIPipeline(
        analyzer=FakeAnalyzer(),
        prediction_log_path=log_path,
        include_detected_text=False,
        run_id="run-003",
    )

    pipeline.predict("email user@example.com", language="vi")

    result = read_jsonl(log_path)[0]["results"][0]
    assert result["text"] is None


def test_source_text_is_opt_in(tmp_path):
    log_path = tmp_path / "predictions.jsonl"
    pipeline = PIIPipeline(
        analyzer=FakeAnalyzer(),
        prediction_log_path=log_path,
        include_source_text=True,
        run_id="run-004",
    )

    pipeline.predict("email user@example.com", language="vi")

    assert read_jsonl(log_path)[0]["source_text"] == "email user@example.com"


def test_multiple_pipelines_append_to_shared_file(tmp_path):
    log_path = tmp_path / "predictions.jsonl"
    first = PIIPipeline(
        analyzer=FakeAnalyzer(),
        prediction_log_path=log_path,
        pipeline_name="regex_only",
        run_id="run-005",
    )
    second = PIIPipeline(
        analyzer=FakeAnalyzer(),
        prediction_log_path=log_path,
        pipeline_name="full_hybrid_pipeline",
        run_id="run-005",
    )

    first.predict("email user@example.com", language="vi")
    second.predict("email user@example.com", language="vi")

    records = read_jsonl(log_path)
    assert [record["pipeline_name"] for record in records] == [
        "regex_only",
        "full_hybrid_pipeline",
    ]


def test_resolver_audit_logs_dropped_candidate_and_markdown(tmp_path):
    log_path = tmp_path / "predictions.jsonl"
    pipeline = PIIPipeline(
        analyzer=FakeUndertheseaPersonAnalyzer(),
        resolver=DeterministicResolver(),
        prediction_log_path=log_path,
        include_source_text=True,
        run_id="run-resolver-audit",
    )

    results = pipeline.predict(
        "Bệnh viện Bạch Mai tiếp nhận hồ sơ.",
        language="vi",
        input_ids="row-org-001",
    )

    assert results == []
    record = read_jsonl(log_path)[0]
    audit = record["resolver_audit"]
    assert audit["resolver"] == "DeterministicResolver"
    assert audit["input_count"] == 1
    assert audit["output_count"] == 0
    assert audit["decisions"] == [
        {
            "candidate_id": 0,
            "action": "drop",
            "reason": "left context indicates an organization",
            "entity_type": "PERSON",
            "start": 10,
            "end": 18,
            "text": "Bạch Mai",
            "score": 0.8,
            "recognizer": "DeepLearning_UndertheseaNER",
            "left_context": "Bệnh viện ",
            "right_context": " tiếp nhận hồ sơ.",
        }
    ]

    audit_text = log_path.with_suffix(".audit.md").read_text(encoding="utf-8")
    assert "row-org-001" in audit_text
    assert "Resolver Decisions" in audit_text
    assert "drop" in audit_text
    assert "left context indicates an organization" in audit_text
    assert "Bạch Mai" in audit_text
