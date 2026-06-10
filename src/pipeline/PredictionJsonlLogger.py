import json
from pathlib import Path


class PredictionJsonlLogger:
    """Append self-contained PII prediction audit records as JSONL."""

    record_version = 1

    def __init__(self, path):
        self.path = Path(path)
        self.readable_path = self.path.with_suffix(".readable.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log_prediction(
        self,
        *,
        run_id,
        pipeline_name,
        input_id,
        language,
        score_threshold,
        source_text,
        results,
        anonymized_text,
        ground_truth,
        include_source_text=False,
        include_detected_text=True,
    ):
        record = self.build_record(
            run_id=run_id,
            pipeline_name=pipeline_name,
            input_id=input_id,
            language=language,
            score_threshold=score_threshold,
            source_text=source_text,
            results=results,
            anonymized_text=anonymized_text,
            ground_truth=ground_truth,
            include_source_text=include_source_text,
            include_detected_text=include_detected_text,
        )
        self.log_record(record)
        return record

    def log_record(self, record):
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._write_readable_record(record)

    def _write_readable_record(self, record):
        records = []
        if self.readable_path.exists():
            with self.readable_path.open(encoding="utf-8") as handle:
                records = json.load(handle)
        records.append(record)
        with self.readable_path.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def build_record(
        self,
        *,
        run_id,
        pipeline_name,
        input_id,
        language,
        score_threshold,
        source_text,
        results,
        anonymized_text,
        ground_truth,
        include_source_text=False,
        include_detected_text=True,
    ):
        return {
            "record_version": self.record_version,
            "run_id": run_id,
            "pipeline_name": pipeline_name,
            "input_id": input_id,
            "language": language,
            "score_threshold": score_threshold,
            "source_text": source_text if include_source_text else None,
            "results": [
                self._serialize_result(
                    result,
                    source_text=source_text,
                    include_detected_text=include_detected_text,
                )
                for result in results
            ],
            "anonymized_text": anonymized_text,
            "ground_truth": ground_truth if ground_truth is not None else [],
        }

    def _serialize_result(self, result, *, source_text, include_detected_text):
        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        explanation = result_dict.get("analysis_explanation") or {}
        metadata = result_dict.get("recognition_metadata") or {}

        start = getattr(result, "start", result_dict.get("start"))
        end = getattr(result, "end", result_dict.get("end"))
        detected_text = None
        if include_detected_text and start is not None and end is not None:
            detected_text = source_text[start:end]

        return {
            "entity_type": getattr(result, "entity_type", result_dict.get("entity_type")),
            "start": start,
            "end": end,
            "text": detected_text,
            "score": getattr(result, "score", result_dict.get("score")),
            "recognizer": self._field(explanation, "recognizer") or self._field(metadata, "recognizer_name"),
            "pattern": self._field(explanation, "pattern_name") or self._field(explanation, "pattern"),
            "original_score": self._field(explanation, "original_score"),
            "explanation_score": self._field(explanation, "score"),
            "score_context_improvement": self._field(explanation, "score_context_improvement"),
            "supportive_context": self._field(explanation, "supportive_context_word"),
            "validation": self._field(explanation, "validation_result"),
        }

    def _field(self, data, name):
        if isinstance(data, dict):
            return data.get(name)
        return getattr(data, name, None)
