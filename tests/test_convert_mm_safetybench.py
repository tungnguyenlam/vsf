"""Tests for the MM-SafetyBench safety_v0 converter label mapping."""

import importlib.util
from pathlib import Path

import pytest

from src.pipeline.Datasets.safety_v0_schema import validate_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "safety_v0" / "convert" / "convert_mm_safetybench.py"


@pytest.fixture(scope="module")
def conv():
    spec = importlib.util.spec_from_file_location("convert_mm_safetybench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sex_maps_sexual_and_reject(conv):
    labels, label_source = conv.category_labels("Sex")
    assert labels["action"] == "reject"
    assert labels["sexual"] is True
    assert label_source["sexual"] == "source_gold"
    assert label_source["action"] == "source_derived"


def test_physical_harm_maps_violence(conv):
    labels, _ = conv.category_labels("Physical_Harm")
    assert labels["action"] == "reject"
    assert labels["violence"] is True
    assert labels["sexual"] is None


def test_political_categories_map_political_but_defer_action(conv):
    for category in ("Political_Lobbying", "Gov_Decision"):
        labels, _ = conv.category_labels(category)
        assert labels["political"] is True
        # refusal is policy-dependent for these -> action unknown
        assert labels["action"] is None


def test_professional_advice_action_is_null(conv):
    for category in ("Financial_Advice", "Legal_Opinion", "Health_Consultation"):
        labels, _ = conv.category_labels(category)
        assert labels["action"] is None
        assert labels["sexual"] is None
        assert labels["violence"] is None


def test_hate_and_illegal_reject_without_boolean_axis(conv):
    for category in ("HateSpeech", "Illegal_Activitiy", "Fraud", "Malware_Generation"):
        labels, _ = conv.category_labels(category)
        assert labels["action"] == "reject"
        # no canonical boolean axis for these
        assert labels["sexual"] is None
        assert labels["violence"] is None
        assert labels["political"] is None


def test_privacy_violence_is_not_pii_visible(conv):
    labels, _ = conv.category_labels("Privacy_Violence")
    assert labels["action"] == "reject"
    # category is about privacy-violating intent, not literal PII printed in the
    # image; pii_visible is only set later by the OCR/PII detector.
    assert labels["pii_visible"] is None


def test_prompt_injection_always_null(conv):
    for category in conv.CATEGORIES:
        labels, label_source = conv.category_labels(category)
        assert labels["prompt_injection"] is None
        assert label_source["prompt_injection"] is None


def test_build_canonical_row_is_valid(conv):
    row = conv.build_canonical_row(1, "Sex", "0", "Describe explicit content.")
    assert validate_row(row) == []
    assert row["input_id"] == "safety_v0_mm_safetybench_000001"
    assert row["source"]["license_status"] == "cc_by_nc_4.0"
    assert row["modality"] == {"has_image": False, "has_text": True, "has_ocr": False}
    assert row["source_labels"]["category"] == "Sex"
    assert row["source_labels"]["original_question"] == "Describe explicit content."
