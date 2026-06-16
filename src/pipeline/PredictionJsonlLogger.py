import json
from pathlib import Path


class PredictionJsonlLogger:
    """Append self-contained PII prediction audit records as JSONL."""

    record_version = 2

    def __init__(self, path):
        self.path = Path(path)
        self.readable_path = self.path.with_suffix(".readable.json")
        self.audit_path = self.path.with_suffix(".audit.md")
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
        resolver_audit=None,
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
            resolver_audit=resolver_audit,
        )
        self.log_record(record)
        return record

    def log_record(self, record):
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._write_readable_record(record)
        self._write_audit_markdown()

    def _write_readable_record(self, record):
        records = []
        if self.readable_path.exists():
            with self.readable_path.open(encoding="utf-8") as handle:
                records = json.load(handle)
        records.append(record)
        with self.readable_path.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def _write_audit_markdown(self):
        records = []
        if self.readable_path.exists():
            with self.readable_path.open(encoding="utf-8") as handle:
                records = json.load(handle)

        lines = [
            "# PII Prediction Audit",
            "",
            "This file is generated from `predictions.jsonl` for quick human review.",
            "",
        ]
        for record in records:
            lines.extend(self._record_markdown(record))

        with self.audit_path.open("w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")

    def _record_markdown(self, record):
        input_id = record.get("input_id") or "(none)"
        run_id = record.get("run_id") or "(none)"
        pipeline_name = record.get("pipeline_name") or "(unknown)"
        source_text = record.get("source_text")
        anonymized_text = record.get("anonymized_text")
        resolver_audit = record.get("resolver_audit") or {}
        decisions = resolver_audit.get("decisions") or []
        dropped = [decision for decision in decisions if decision.get("action") == "drop"]

        lines = [
            f"## {self._md(input_id)}",
            "",
            f"- Run: `{self._md(run_id)}`",
            f"- Pipeline: `{self._md(pipeline_name)}`",
            f"- Final spans: {len(record.get('results') or [])}",
            f"- Resolver drops: {len(dropped)}",
            "",
        ]
        if source_text is not None:
            lines.extend(["### Source Text", "", self._md_block(source_text), ""])
        if anonymized_text is not None:
            lines.extend(["### Anonymized Text", "", self._md_block(anonymized_text), ""])

        lines.extend(["### Final Spans", ""])
        results = record.get("results") or []
        if results:
            lines.extend(
                [
                    "| Type | Text | Span | Score | Recognizer |",
                    "| --- | --- | --- | --- | --- |",
                ]
            )
            for result in results:
                lines.append(
                    "| "
                    f"{self._md(result.get('entity_type'))} | "
                    f"{self._md(result.get('text'))} | "
                    f"{self._md(self._span(result))} | "
                    f"{self._md(result.get('score'))} | "
                    f"{self._md(result.get('recognizer'))} |"
                )
        else:
            lines.append("No final spans.")
        lines.append("")

        if resolver_audit:
            lines.extend(
                [
                    "### Resolver Decisions",
                    "",
                    "| Action | Type | Text | Span | Reason | Left Context | Recognizer |",
                    "| --- | --- | --- | --- | --- | --- | --- |",
                ]
            )
            for decision in decisions:
                lines.append(
                    "| "
                    f"{self._md(decision.get('action'))} | "
                    f"{self._md(decision.get('entity_type'))} | "
                    f"{self._md(decision.get('text'))} | "
                    f"{self._md(self._span(decision))} | "
                    f"{self._md(decision.get('reason'))} | "
                    f"{self._md(decision.get('left_context'))} | "
                    f"{self._md(decision.get('recognizer'))} |"
                )
            lines.append("")
        return lines

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
        resolver_audit=None,
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
            "resolver_audit": resolver_audit,
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

    def _span(self, data):
        return f"{data.get('start')}:{data.get('end')}"

    def _md(self, value):
        if value is None:
            return ""
        return str(value).replace("|", "\\|").replace("\n", " ")

    def _md_block(self, value):
        return "```text\n" + str(value).replace("```", "'''") + "\n```"
