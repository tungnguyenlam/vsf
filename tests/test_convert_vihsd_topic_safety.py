"""Tests for the vihsd-topic-safety safety_v0 converter.

Uses synthetic records so the tests do not require the downloaded sample.
"""

import importlib.util
from pathlib import Path

import pytest

from src.pipeline.Datasets.safety_v0_schema import validate_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "safety_v0" / "convert" / "convert_vihsd_topic_safety.py"


@pytest.fixture(scope="module")
def conv():
    spec = importlib.util.spec_from_file_location("convert_vihsd_topic_safety", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hate_row_keeps_topic_axes_unknown(conv):
    row = conv.build_canonical_row(1, "train", {"free_text": "noi dung ghet bo", "label_id": 2})
    assert validate_row(row) == []
    assert row["input_id"] == "safety_v0_vihsd_topic_safety_000001"
    assert row["modality"] == {"has_image": False, "has_text": True, "has_ocr": False}
    # Source assumptions: not a PI/image dataset.
    assert row["labels"]["prompt_injection"] is False
    assert row["label_source"]["prompt_injection"] == "source_assumption"
    assert row["labels"]["pii_visible"] is False
    # Topic axes + action stay unknown — hate does not map onto them.
    for field in ("sexual", "violence", "blood_gore", "political", "religious", "action"):
        assert row["labels"][field] is None
        assert row["label_source"][field] is None
    # Original label preserved for later mapping / teacher.
    assert row["source_labels"] == {"label_id": 2, "label_name": "HATE", "split": "train"}


def test_clean_and_offensive_label_names(conv):
    clean = conv.build_canonical_row(1, "train", {"free_text": "binh thuong", "label_id": 0})
    off = conv.build_canonical_row(2, "dev", {"free_text": "tho tuc", "label_id": 1})
    assert clean["source_labels"]["label_name"] == "CLEAN"
    assert off["source_labels"]["label_name"] == "OFFENSIVE"
    assert off["source"]["split"] == "dev"


def test_text_is_carried_into_input_and_sanitized(conv):
    row = conv.build_canonical_row(5, "test", {"free_text": "xin chao", "label_id": 0})
    assert row["content"]["input_text"] == "xin chao"
    assert row["content"]["sanitized_text"] == "xin chao"
    assert row["source"]["name"] == "uitnlp/vihsd"  # canonical, not the mirror


def test_empty_text_still_valid(conv):
    row = conv.build_canonical_row(1, "train", {"free_text": "", "label_id": 0})
    assert validate_row(row) == []
    assert row["detections"]["prompt_injection_spans"] == []
