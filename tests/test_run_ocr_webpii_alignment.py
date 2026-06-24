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


def test_source_box_ocr_matches_recovers_tight_source_box_in_wide_ocr_line():
    """A tight PII source box inside a wide OCR line (e.g. card last-4 in
    "ending in 2522 Change") has low OCR-coverage but ~full source-coverage, so
    it must still match — the regression that left 2522 un-redacted."""
    mod = _load_run_ocr()
    source_box = {
        "box_id": "source_pii_box_0001",
        "source_key": "PII_CARD_LAST4",
        "text": "2522",
        "box": [502, 180, 533, 194],
    }
    boxes = [
        {"box_id": "box_0017", "text": "ending in 2522 Change", "start": 0, "end": 21,
         "box": [422, 178, 585, 195]},
    ]

    # OCR-coverage of the tiny source box over the wide line is ~0.15 (< 0.5),
    # but source-coverage is ~1.0, so the match is accepted.
    matches = mod.source_box_ocr_matches(source_box, boxes, min_ocr_coverage=0.5)
    assert [m["box_id"] for m in matches] == ["box_0017"]


def test_narrow_to_source_text_clips_name_inside_wide_block():
    """A tight PII source box aligned to a wide OCR block must narrow to the
    occurrence of the source text, not the whole block (the over-redaction that
    masked "FREE Two-Day Shipping ... Alexa Copeland ... on this order by")."""
    mod = _load_run_ocr()
    block = "FREE Two-Day Shipping on this Order: Alexa Copeland, you can save"
    start, end = mod._narrow_to_source_text(block, 0, len(block), "Alexa Copeland")
    assert block[start:end] == "Alexa Copeland"


def test_narrow_to_source_text_whitespace_flexible():
    mod = _load_run_ocr()
    block = "Order:\nAlexa   Copeland here"
    start, end = mod._narrow_to_source_text(block, 0, len(block), "Alexa Copeland")
    assert block[start:end] == "Alexa   Copeland"


def test_narrow_to_source_text_falls_back_when_absent():
    mod = _load_run_ocr()
    block = "ending in 2522 Change"
    # Source text not literally present -> keep full range (safe over-redact).
    assert mod._narrow_to_source_text(block, 0, len(block), "unrelated") == (0, len(block))


def test_align_source_pii_spans_narrows_span_to_source_text_in_block():
    mod = _load_run_ocr()
    block = "FREE Two-Day Shipping on this Order: Alexa Copeland, you can save"
    row = new_row(
        "safety_v0_webpii_000003",
        "WebPII/webpii",
        has_image=True,
        has_ocr=True,
        original_image_path="data/safety_v0/converted/webpii/images/x.png",
        ocr_text=block,
    )
    row["geometry"]["ocr_boxes"] = [
        {"box_id": "box_0010", "text": block, "start": 0, "end": len(block),
         "box": [40, 250, 940, 268]},
    ]
    row["geometry"]["source_pii_boxes"] = [
        {
            "box_id": "source_pii_box_0001",
            "source_key": "PII_FULLNAME",
            "entity_type": "PERSON",
            "text": "Alexa Copeland",
            "box": [300, 250, 460, 268]},
    ]

    out = mod.align_source_pii_spans(row)

    span = out["detections"]["pii_spans"][0]
    assert span["text"] == "Alexa Copeland"
    assert block[span["start"]:span["end"]] == "Alexa Copeland"
    assert span["box_ids"] == ["box_0010"]
    assert validate_row(out) == []


def test_align_skips_free_text_misc_fields():
    """Whole free-text fields (PII_GIFT_MESSAGE / PII_DELIVERY_INSTRUCTIONS ->
    MISC) must not become redaction spans; their embedded PII (name, address) is
    boxed separately. Otherwise the whole personalized message gets masked."""
    mod = _load_run_ocr()
    block = "Hey James, I came across these lovely earrings Enjoy! Suzanne"
    row = new_row(
        "safety_v0_webpii_000004",
        "WebPII/webpii",
        has_image=True,
        has_ocr=True,
        original_image_path="data/safety_v0/converted/webpii/images/x.png",
        ocr_text=block,
    )
    row["geometry"]["ocr_boxes"] = [
        {"box_id": "box_0001", "text": block, "start": 0, "end": len(block),
         "box": [40, 250, 940, 268]},
    ]
    row["geometry"]["source_pii_boxes"] = [
        {"box_id": "source_pii_box_0001", "source_key": "PII_GIFT_MESSAGE",
         "entity_type": "MISC", "text": block, "box": [40, 250, 940, 268]},
        {"box_id": "source_pii_box_0002", "source_key": "PII_GIFT_FULLNAME",
         "entity_type": "PERSON", "text": "James", "box": [70, 250, 110, 268]},
    ]

    out = mod.align_source_pii_spans(row)

    spans = out["detections"]["pii_spans"]
    assert [s["entity_type"] for s in spans] == ["PERSON"]
    assert all(s.get("source_key") != "PII_GIFT_MESSAGE" for s in spans)
    assert out["source_labels"]["source_aligned_pii_span_count"] == 1
    assert validate_row(out) == []


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
