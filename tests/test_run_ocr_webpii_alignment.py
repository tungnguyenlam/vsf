"""Tests for WebPII source-box alignment during the OCR stage."""

import importlib.util
from pathlib import Path

from src.pipeline.Datasets.safety_v0_schema import new_row, validate_row
from src.pipeline.Image.ocr import OcrResult, OcrSegment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_run_ocr():
    path = PROJECT_ROOT / "scripts" / "safety_v0" / "run_ocr.py"
    spec = importlib.util.spec_from_file_location("run_ocr", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ocr_boxes():
    return [
        {"box_id": "box_0001", "text": "Nguyen", "start": 0, "end": 6, "box": [10, 10, 60, 25]},
        {"box_id": "box_0002", "text": "Van", "start": 7, "end": 10, "box": [62, 10, 90, 25]},
        {"box_id": "box_0003", "text": "A", "start": 11, "end": 12, "box": [92, 10, 104, 25]},
        {"box_id": "box_0004", "text": "Order", "start": 13, "end": 18, "box": [10, 50, 55, 64]},
    ]


def test_source_box_ocr_matches_uses_ocr_box_coverage():
    mod = _load_run_ocr()
    source_box = {
        "box_id": "source_pii_box_0001",
        "text": "Nguyen Van A",
        "box": [5, 5, 110, 32],
    }

    matches = mod.source_box_ocr_matches(source_box, _ocr_boxes(), min_ocr_coverage=0.5)

    assert [m["box_id"] for m in matches] == ["box_0001", "box_0002", "box_0003"]


def test_source_box_ocr_matches_prefers_text_compatible_overlap():
    mod = _load_run_ocr()
    source_box = {
        "box_id": "source_pii_box_0001",
        "text": "Nguyen Van A",
        "box": [5, 5, 110, 70],
    }

    matches = mod.source_box_ocr_matches(source_box, _ocr_boxes(), min_ocr_coverage=0.5)

    assert [m["box_id"] for m in matches] == ["box_0001", "box_0002", "box_0003"]


def test_source_box_ocr_matches_falls_back_to_geometry_for_noisy_ocr_text():
    mod = _load_run_ocr()
    source_box = {
        "box_id": "source_pii_box_0001",
        "text": "Nguyen Van A",
        "box": [5, 5, 110, 32],
    }
    boxes = [
        {"box_id": "box_0001", "text": "Nqvven", "start": 0, "end": 6, "box": [10, 10, 60, 25]},
        {"box_id": "box_0002", "text": "V4n", "start": 7, "end": 10, "box": [62, 10, 90, 25]},
    ]

    matches = mod.source_box_ocr_matches(source_box, boxes, min_ocr_coverage=0.5)

    assert [m["box_id"] for m in matches] == ["box_0001", "box_0002"]


def test_align_source_pii_spans_creates_source_provenance_spans():
    mod = _load_run_ocr()
    row = new_row(
        "safety_v0_webpii_000001",
        "WebPII/webpii",
        has_image=True,
        has_ocr=True,
        original_image_path="data/safety_v0/converted/webpii/images/x.png",
        ocr_text="Nguyen Van A Order",
    )
    row["geometry"]["ocr_boxes"] = _ocr_boxes()
    row["geometry"]["source_pii_boxes"] = [
        {
            "box_id": "source_pii_box_0001",
            "source_key": "PII_FULLNAME",
            "entity_type": "PERSON",
            "text": "Nguyen Van A",
            "box": [5, 5, 110, 32],
        },
        {
            "box_id": "source_pii_box_0002",
            "source_key": "PII_EMAIL",
            "entity_type": "EMAIL_ADDRESS",
            "text": "missing@example.com",
            "box": [200, 200, 300, 230],
        },
    ]

    out = mod.align_source_pii_spans(row)

    assert validate_row(out) == []
    assert out["source_labels"]["source_aligned_pii_span_count"] == 1
    assert out["detections"]["pii_spans"] == [
        {
            "span_id": "source_pii_0001",
            "entity_type": "PERSON",
            "start": 0,
            "end": 12,
            "text": "Nguyen Van A",
            "score": 1.0,
            "box_ids": ["box_0001", "box_0002", "box_0003"],
            "detector": mod.SOURCE_PII_ALIGNMENT_DETECTOR,
            "source_box_id": "source_pii_box_0001",
            "source_key": "PII_FULLNAME",
            "source_text": "Nguyen Van A",
        }
    ]


class FakeAdapter:
    def run(self, image_path):
        assert Path(image_path).exists()
        return OcrResult(
            full_text="Nguyen Van A",
            segments=[
                OcrSegment("Nguyen", 0, 6, [10, 10, 60, 25], 0.9),
                OcrSegment("Van", 7, 10, [62, 10, 90, 25], 0.9),
                OcrSegment("A", 11, 12, [92, 10, 104, 25], 0.9),
            ],
        )


def test_ocr_row_runs_adapter_and_aligns_source_boxes(tmp_path):
    mod = _load_run_ocr()
    image = tmp_path / "doc.png"
    image.write_bytes(b"not a real image; fake adapter only checks existence")
    row = new_row(
        "safety_v0_webpii_000002",
        "WebPII/webpii",
        has_image=True,
        has_ocr=False,
        original_image_path=str(image),
    )
    row["geometry"]["source_pii_boxes"] = [
        {
            "box_id": "source_pii_box_0001",
            "source_key": "PII_FULLNAME",
            "entity_type": "PERSON",
            "text": "Nguyen Van A",
            "box": [5, 5, 110, 32],
        }
    ]

    out = mod.ocr_row(row, FakeAdapter())

    assert out["modality"]["has_ocr"] is True
    assert out["content"]["ocr_text"] == "Nguyen Van A"
    assert [box["box_id"] for box in out["geometry"]["ocr_boxes"]] == [
        "box_0001",
        "box_0002",
        "box_0003",
    ]
    assert out["detections"]["pii_spans"][0]["box_ids"] == ["box_0001", "box_0002", "box_0003"]
    assert validate_row(out) == []
