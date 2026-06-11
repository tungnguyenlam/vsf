import json
from pathlib import Path


class PromptInjectionDecisionJsonlLogger:
    record_version = 1

    def __init__(self, path):
        self.path = Path(path)
        self.readable_path = self.path.with_suffix(".readable.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        with self.readable_path.open("w", encoding="utf-8") as handle:
            json.dump([], handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def log_decision(
        self,
        *,
        run_id,
        detector_name,
        example,
        result,
        include_source_text=False,
    ):
        record = {
            "record_version": self.record_version,
            "run_id": run_id,
            "detector_name": detector_name,
            "input_id": example.input_id,
            "source": example.source,
            "language": example.language,
            "category": example.category,
            "source_text": example.text if include_source_text else None,
            "ground_truth": {
                "label": example.label,
                "is_injection": example.is_injection,
                "expected_action": example.expected_action,
            },
            "prediction": result.to_dict(),
        }
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
