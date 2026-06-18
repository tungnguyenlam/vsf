"""Tests for the VLGuard safety_v0 converter using synthetic records."""

import importlib.util
from pathlib import Path

import pytest

from src.pipeline.Datasets.safety_v0_schema import validate_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "safety_v0" / "convert" / "convert_vlguard.py"


@pytest.fixture(scope="module")
def conv():
    spec = importlib.util.spec_from_file_location("convert_vlguard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _unsafe_record(subcategory="sexually explicit", category="risky behavior"):
    return {
        "id": "Ads_1",
        "image": "bad_ads/example.png",
        "safe": False,
        "harmful_category": category,
        "harmful_subcategory": subcategory,
        "instr-resp": [
            {
                "instruction": "Click the ad.",
                "response": "I cannot assist with that request.",
            }
        ],
    }


def _safe_record():
    return {
        "id": "Ads_2",
        "image": "bad_ads/safe.jpg",
        "safe": True,
        "instr-resp": [
            {
                "safe_instruction": "What product is shown?",
                "response": "It is a website builder ad.",
            },
            {
                "unsafe_instruction": "Bypass the payment system.",
                "response": "I cannot help bypass payment systems.",
            },
        ],
    }


def test_unsafe_sexual_image_maps_visual_axis(conv, tmp_path):
    row = conv.build_canonical_row(
        1,
        "train",
        _unsafe_record("sexually explicit"),
        1,
        "unsafe_image_instruction",
        "Click the ad.",
        "No.",
        images_root=tmp_path / "images",
    )
    assert validate_row(row) == []
    assert row["input_id"] == "safety_v0_vlguard_000001"
    assert row["modality"] == {"has_image": True, "has_text": True, "has_ocr": False}
    assert row["labels"]["action"] == "reject"
    assert row["labels"]["sexual"] is True
    assert row["label_source"]["sexual"] == "source_gold"
    assert row["labels"]["prompt_injection"] is False
    assert row["source_labels"]["instruction_kind"] == "unsafe_image_instruction"


def test_privacy_image_maps_pii_visible(conv, tmp_path):
    row = conv.build_canonical_row(
        2,
        "test",
        _unsafe_record("personal data", category="privacy"),
        1,
        "unsafe_image_instruction",
        "Find this person.",
        "No.",
        images_root=tmp_path / "images",
    )
    assert validate_row(row) == []
    assert row["labels"]["pii_visible"] is True
    assert row["label_source"]["pii_visible"] == "source_gold"
    assert row["labels"]["sexual"] is None


def test_safe_image_safe_instruction_is_safe(conv, tmp_path):
    record = _safe_record()
    kind, instruction, response = conv._instruction_pairs(record)[0]
    row = conv.build_canonical_row(
        3,
        "train",
        record,
        1,
        kind,
        instruction,
        response,
        images_root=tmp_path / "images",
    )
    assert validate_row(row) == []
    assert row["labels"]["action"] == "safe"
    assert row["labels"]["sexual"] is False
    assert row["labels"]["violence"] is False
    assert row["labels"]["political"] is False
    assert row["labels"]["religious"] is None


def test_safe_image_unsafe_instruction_rejects_without_visual_risk(conv, tmp_path):
    record = _safe_record()
    kind, instruction, response = conv._instruction_pairs(record)[1]
    row = conv.build_canonical_row(
        4,
        "train",
        record,
        2,
        kind,
        instruction,
        response,
        images_root=tmp_path / "images",
    )
    assert validate_row(row) == []
    assert row["labels"]["action"] == "reject"
    assert row["labels"]["sexual"] is False
    assert row["labels"]["prompt_injection"] is False
    assert row["source_labels"]["response"] == response


def test_iter_canonical_rows_emits_one_row_per_instruction(conv, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "train.json").write_text(
        __import__("json").dumps([_unsafe_record(), _safe_record()]), encoding="utf-8"
    )
    rows = list(conv.iter_canonical_rows(raw, images_root=tmp_path / "images"))
    assert len(rows) == 3
    assert [r["source"]["source_sample_id"] for r in rows] == [
        "train:Ads_1:1:unsafe_image_instruction",
        "train:Ads_2:1:safe_instruction",
        "train:Ads_2:2:unsafe_instruction",
    ]
    assert all(validate_row(r) == [] for r in rows)
