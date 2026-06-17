"""Tests for the image OCR + redaction stages (no PaddleOCR dependency)."""

import importlib.util
from pathlib import Path

import pytest

from src.pipeline.Image.ocr import (
    OcrSegment,
    PaddleOcrAdapter,
    build_full_text,
    get_ocr_adapter,
    list_ocr_adapter_names,
    quad_to_aabb,
)
from src.pipeline.Image.redaction import (
    image_size,
    map_span_to_box,
    map_spans_to_boxes,
    recompute_redactions,
    redact_image,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# --- OCR normalization -------------------------------------------------------
def test_build_full_text_offsets_are_exact():
    result = build_full_text([
        ("Ho", [0, 0, 10, 10], 0.9),
        ("ten", [12, 0, 30, 10], 0.8),
        ("An", [32, 0, 45, 10], 0.95),
    ])
    assert result.full_text == "Ho ten An"
    # Each segment's offsets slice back to its own text.
    for seg in result.segments:
        assert result.full_text[seg.start:seg.end] == seg.text
    assert result.segments[1].start == 3 and result.segments[1].end == 6


def test_quad_to_aabb():
    assert quad_to_aabb([[10, 5], [40, 7], [42, 22], [9, 20]]) == [9, 5, 42, 22]


def test_paddle_normalize_without_engine():
    raw = [[
        [[[0, 0], [20, 0], [20, 10], [0, 10]], ("0987654321", 0.99)],
        [[[25, 0], [40, 0], [40, 10], [25, 10]], ("xyz", 0.8)],
    ]]
    result = PaddleOcrAdapter._normalize(raw)
    assert result.full_text == "0987654321 xyz"
    assert result.segments[0].box == [0, 0, 20, 10]
    assert result.segments[0].confidence == 0.99


def test_paddle_normalize_v3_dict_output():
    import numpy as np

    raw = [{
        "rec_texts": ["Nguyen", "Van A"],
        "rec_scores": [0.98, 0.97],
        "rec_polys": [
            np.array([[0, 0], [50, 0], [50, 12], [0, 12]]),
            np.array([[55, 0], [100, 0], [100, 12], [55, 12]]),
        ],
    }]
    result = PaddleOcrAdapter._normalize(raw)
    assert result.full_text == "Nguyen Van A"
    assert result.segments[1].box == [55, 0, 100, 12]
    assert result.segments[1].confidence == 0.97


def test_registry():
    assert "paddleocr" in list_ocr_adapter_names()
    assert isinstance(get_ocr_adapter("paddleocr"), PaddleOcrAdapter)
    with pytest.raises(ValueError):
        get_ocr_adapter("nope")


# --- span -> box mapping -----------------------------------------------------
def _segments():
    # "Ho ten Nguyen 0987654321"
    return [
        OcrSegment("Ho", 0, 2, [0, 0, 20, 12]),
        OcrSegment("ten", 3, 6, [22, 0, 50, 12]),
        OcrSegment("Nguyen", 7, 13, [52, 0, 110, 12]),
        OcrSegment("0987654321", 14, 24, [0, 20, 120, 34]),
    ]


def test_map_span_single_segment():
    box = map_span_to_box({"start": 14, "end": 24}, _segments(), padding=0)
    assert box is not None
    assert box.segment_indices == [3]
    assert box.box == [0, 20, 120, 34]


def test_map_span_merges_multiple_segments_with_padding_and_clamp():
    # span covers "ten Nguyen"
    box = map_span_to_box({"start": 3, "end": 13}, _segments(), padding=5, image_size=(60, 60))
    assert box.segment_indices == [1, 2]
    # merged [22,0,110,12] padded by 5 then clamped to (60,60)
    assert box.box == [17, 0, 60, 17]


def test_map_span_clips_partial_selection_within_one_box():
    # OCR line box covers chars [0,21] across pixels x in [10,180]; select "2522"
    # (chars 10..14) -> only the proportional horizontal slice is redacted, y kept.
    segs = [OcrSegment("ending in 2522 Change", 0, 21, [10, 10, 180, 30])]
    box = map_span_to_box({"start": 10, "end": 14}, segs, padding=0)
    assert box.segment_indices == [0]
    x0, y0, x1, y1 = box.box
    assert y0 == 10 and y1 == 30                      # full line height
    assert abs(x0 - (10 + 10 / 21 * 170)) < 1e-6      # left edge at char 10
    assert abs(x1 - (10 + 14 / 21 * 170)) < 1e-6      # right edge at char 14
    assert 10 < x0 < x1 < 180                          # strictly inside the box


def test_map_span_no_overlap_returns_none():
    assert map_span_to_box({"start": 100, "end": 110}, _segments()) is None


def test_map_spans_to_boxes_skips_unmapped():
    spans = [{"start": 0, "end": 2}, {"start": 100, "end": 110}]
    boxes = map_spans_to_boxes(spans, _segments(), padding=0)
    assert len(boxes) == 1


# --- image redaction ---------------------------------------------------------
def _make_image(path: Path):
    from PIL import Image
    Image.new("RGB", (120, 40), "white").save(path)


def test_redact_image_blur_and_fill(tmp_path):
    src = tmp_path / "src.png"
    _make_image(src)
    assert image_size(src) == [120, 40]

    out_fill = tmp_path / "fill.png"
    redact_image(src, out_fill, [[0, 0, 20, 10]], method="fill")
    from PIL import Image
    assert Image.open(out_fill).getpixel((5, 5)) == (0, 0, 0)

    out_blur = tmp_path / "blur.png"
    redact_image(src, out_blur, [[0, 0, 20, 10]], method="blur")
    assert out_blur.exists()


def test_redact_image_empty_boxes_still_writes(tmp_path):
    src = tmp_path / "src.png"
    _make_image(src)
    out = tmp_path / "out.png"
    redact_image(src, out, [], method="blur")
    assert out.exists()


def test_redact_image_bad_method(tmp_path):
    src = tmp_path / "src.png"
    _make_image(src)
    with pytest.raises(ValueError):
        redact_image(src, tmp_path / "x.png", [], method="pixelate")


# --- recompute_redactions (shared core: batch + webdemo live preview) --------
def test_recompute_redactions_maps_span_and_human_box(tmp_path):
    from src.pipeline.Datasets.safety_v0_schema import new_ocr_box, new_pii_span, new_row

    src = tmp_path / "doc.png"
    _make_image(src)
    row = new_row(
        "safety_v0_demo_000077", "demo/webpii",
        has_image=True, has_ocr=True,
        original_image_path=str(src),
        ocr_text="So dien thoai 0987654321",
    )
    row["geometry"]["ocr_boxes"] = [
        new_ocr_box("box_0004", "0987654321", 14, 24, [0, 20, 120, 34], 0.9),
    ]
    # One OCR-aligned span (box_ids start empty -> filled by recompute) and one
    # human image-drawn box with no OCR offsets.
    row["detections"]["pii_spans"] = [
        new_pii_span("p1", "PHONE_NUMBER", 14, 24, "0987654321", 1.0, [], detector="human"),
    ]
    row["geometry"]["source_pii_boxes"] = [
        {"box_id": "hb1", "entity_type": "PERSON", "text": "", "box": [5, 5, 40, 15], "detector": "human"},
    ]

    out = tmp_path / "red.png"
    result = recompute_redactions(row, src_image=src, dst_path=out, method="fill")

    # span got its box_ids filled from the overlapping OCR box
    assert row["detections"]["pii_spans"][0]["box_ids"] == ["box_0004"]
    # two regions: the span and the human image box
    kinds = {(r["entity_type"], r["detector"], bool(r["box_ids"])) for r in result["regions"]}
    assert ("PHONE_NUMBER", "human", True) in kinds
    assert ("PERSON", "human", False) in kinds
    assert len(result["redaction_metadata"]) == 2
    assert out.exists()


def test_recompute_redactions_no_image_skips_render(tmp_path):
    from src.pipeline.Datasets.safety_v0_schema import new_ocr_box, new_pii_span, new_row

    row = new_row("x", "demo/webpii", has_image=True, has_ocr=True,
                  original_image_path="missing.png", ocr_text="abc 0987654321")
    row["geometry"]["ocr_boxes"] = [new_ocr_box("box_0001", "0987654321", 4, 14, [0, 0, 50, 10], 0.9)]
    row["detections"]["pii_spans"] = [new_pii_span("p1", "PHONE_NUMBER", 4, 14, "0987654321", 1.0, [])]
    out = tmp_path / "none.png"
    result = recompute_redactions(row, src_image=None, dst_path=out, method="fill")
    assert not out.exists()  # no source image -> nothing rendered
    assert result["regions"][0]["box_ids"] == ["box_0001"]


# --- end-to-end stage scripts on a synthetic row -----------------------------
def _load_script(name: str):
    path = PROJECT_ROOT / "scripts" / "safety_v0" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_redact_row_fills_detections(tmp_path):
    """redact_row maps a phone span to its box, writes a redacted image, and
    never touches labels."""
    from presidio_anonymizer import AnonymizerEngine

    from src.pipeline.Datasets.safety_v0_schema import new_ocr_box, new_row, validate_row
    from src.pipeline.Pipelines import get_pipeline

    redaction_mod = _load_script("run_pii_redaction.py")

    src = tmp_path / "doc.png"
    _make_image(src)
    rel = src.relative_to(redaction_mod.PROJECT_ROOT) if str(redaction_mod.PROJECT_ROOT) in str(src) else src

    row = new_row(
        "safety_v0_demo_000099", "demo/webpii",
        has_image=True, has_ocr=True,
        original_image_path=str(src),
        ocr_text="So dien thoai 0987654321",
    )
    row["geometry"]["ocr_boxes"] = [
        new_ocr_box("box_0001", "So", 0, 2, [0, 0, 18, 12], 0.9),
        new_ocr_box("box_0002", "dien", 3, 7, [20, 0, 50, 12], 0.9),
        new_ocr_box("box_0003", "thoai", 8, 13, [52, 0, 90, 12], 0.9),
        new_ocr_box("box_0004", "0987654321", 14, 24, [0, 20, 120, 34], 0.9),
    ]

    pipeline = get_pipeline("regex_recall", prediction_log_path=None)
    out = redaction_mod.redact_row(
        row, pipeline, AnonymizerEngine(), images_dir=tmp_path / "red", method="fill"
    )

    assert validate_row(out) == []
    assert out["labels"]["pii_visible"] is None  # labels untouched
    phone_spans = [s for s in out["detections"]["pii_spans"] if "0987654321" in s["text"]]
    assert phone_spans, "phone number should be detected by regex_recall"
    assert phone_spans[0]["box_ids"] == ["box_0004"]
    assert out["detections"]["redaction_metadata"]
    assert out["content"]["redacted_image_path"]


def test_redact_row_preserves_and_redacts_existing_source_spans(tmp_path):
    from presidio_anonymizer import AnonymizerEngine

    from src.pipeline.Datasets.safety_v0_schema import new_ocr_box, new_pii_span, new_row, validate_row

    redaction_mod = _load_script("run_pii_redaction.py")

    class EmptyPipeline:
        def predict(self, text):
            return []

    src = tmp_path / "doc.png"
    _make_image(src)
    row = new_row(
        "safety_v0_webpii_000001",
        "WebPII/webpii",
        has_image=True,
        has_ocr=True,
        original_image_path=str(src),
        ocr_text="Nguyen Van A",
    )
    row["geometry"]["ocr_boxes"] = [
        new_ocr_box("box_0001", "Nguyen", 0, 6, [0, 0, 50, 12], 0.9),
        new_ocr_box("box_0002", "Van", 7, 10, [52, 0, 80, 12], 0.9),
        new_ocr_box("box_0003", "A", 11, 12, [82, 0, 95, 12], 0.9),
    ]
    row["detections"]["pii_spans"] = [
        new_pii_span(
            "source_pii_0001",
            "PERSON",
            0,
            12,
            "Nguyen Van A",
            1.0,
            ["box_0001", "box_0002", "box_0003"],
            detector="source_webpii_ocr_alignment",
        )
    ]

    out = redaction_mod.redact_row(
        row,
        EmptyPipeline(),
        AnonymizerEngine(),
        images_dir=tmp_path / "red",
        method="fill",
        padding=0,
    )

    assert validate_row(out) == []
    assert out["detections"]["pii_spans"][0]["span_id"] == "source_pii_0001"
    assert out["detections"]["redaction_metadata"][0]["source_span_ids"] == ["source_pii_0001"]
    assert out["content"]["sanitized_ocr_text"] == "<PERSON>"
    from PIL import Image
    assert Image.open(out["content"]["redacted_image_path"]).getpixel((5, 5)) == (0, 0, 0)
