"""Tests for the UnsafeBench safety_v0 converter using a synthetic parquet.

No network, no DUA token, no image decode -- a tiny in-memory DataFrame stands
in for the gated parquet so the mapping contract in
docs/datasets/unsafebench.md is pinned without access to the real data.
"""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline.Datasets.safety_v0_schema import validate_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "safety_v0" / "convert" / "convert_unsafebench.py"


@pytest.fixture(scope="module")
def conv():
    spec = importlib.util.spec_from_file_location("convert_unsafebench", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- map_labels: the documented per-category contract ------------------------


def test_safe_row_sets_every_axis_false(conv):
    # A Safe image in any category bucket is a safe row with all axes false.
    labels, source = conv.map_labels("Safe", "Sexual")
    assert labels["action"] == "safe"
    assert all(labels[a] is False for a in conv.ALL_AXES)
    assert labels["pii_visible"] is False and labels["prompt_injection"] is False
    assert source["action"] == "source_gold"
    assert source["sexual"] == "source_gold"
    # text-derived axes are assumptions, not gold, for safe rows
    assert source["pii_visible"] == "source_assumption"
    assert source["prompt_injection"] == "source_assumption"


def test_na_row_is_all_unknown(conv):
    labels, source = conv.map_labels("N/A", "Hate")
    assert all(v is None for v in labels.values())
    assert all(v is None for v in source.values())


def test_unsafe_sexual_sets_sexual_true(conv):
    labels, source = conv.map_labels("Unsafe", "Sexual")
    assert labels["action"] == "reject"
    assert labels["sexual"] is True
    assert labels["violence"] is False
    assert source["sexual"] == "source_gold"
    # text-derived axes stay unknown for unsafe rows
    assert labels["pii_visible"] is None and labels["prompt_injection"] is None
    assert source["pii_visible"] is None and source["prompt_injection"] is None


def test_unsafe_violence_leaves_blood_gore_null(conv):
    labels, _ = conv.map_labels("Unsafe", "Violence")
    assert labels["action"] == "reject"
    assert labels["violence"] is True
    assert labels["blood_gore"] is None  # UnsafeBench does not sub-label gore


def test_unsafe_no_axis_category_rejects_without_axes(conv):
    # Hate / Harassment / Self-harm / Shocking / Illegal activity / Deception
    for category in ("Hate", "Harassment", "Self-harm", "Shocking",
                     "Illegal activity", "Deception"):
        labels, source = conv.map_labels("Unsafe", category)
        assert labels["action"] == "reject", category
        assert all(labels[a] is None for a in conv.ALL_AXES), category
        assert all(source[a] is None for a in conv.ALL_AXES), category


def test_unsafe_political_defers_action_but_sets_topic(conv):
    labels, source = conv.map_labels("Unsafe", "Political")
    assert labels["action"] is None  # policy-debatable -> review
    assert source["action"] is None
    assert labels["political"] is True
    assert source["political"] == "source_gold"


def test_unsafe_health_and_spam_defer_action_all_axes_false(conv):
    for category in ("Public and personal health", "Spam"):
        labels, _ = conv.map_labels("Unsafe", category)
        assert labels["action"] is None, category
        assert labels["political"] is False, category
        assert labels["sexual"] is False, category


def test_category_match_is_case_insensitive(conv):
    # Real parquet uses lowercased forms ("Self-harm"); paper uses "Self-Harm".
    a, _ = conv.map_labels("Unsafe", "self-harm")
    b, _ = conv.map_labels("Unsafe", "SELF-HARM")
    assert a == b


# --- build_canonical_row + iter over a synthetic parquet ---------------------


def _synthetic_df():
    return pd.DataFrame(
        [
            {"image": b"", "safety_label": "Safe", "category": "Sexual",
             "source": "Lexica", "text": "a cat"},
            {"image": b"", "safety_label": "Unsafe", "category": "Sexual",
             "source": "Laion5B", "text": ""},
            {"image": b"", "safety_label": "Unsafe", "category": "Violence",
             "source": "Laion5B", "text": "fight scene"},
            {"image": b"", "safety_label": "N/A", "category": "Hate",
             "source": "Lexica", "text": "xxx"},
        ]
    )


def test_build_canonical_row_shape(conv, tmp_path):
    record = {"safety_label": "Unsafe", "category": "Sexual",
              "source": "Laion5B", "text": "caption"}
    row = conv.build_canonical_row(
        1, "test", 0, record, images_root=tmp_path / "images"
    )
    assert validate_row(row) == []
    assert row["input_id"] == "safety_v0_unsafebench_000001"
    assert row["source"]["license_status"] == "dua_research"
    assert row["modality"] == {"has_image": True, "has_text": False, "has_ocr": False}
    assert row["content"]["original_image_path"].endswith(
        "images/safety_v0_unsafebench_000001.jpg"
    )
    # text is audit-only metadata, never content
    assert row["content"]["input_text"] == ""
    assert row["source_labels"]["text"] == "caption"
    assert row["source_labels"]["parquet_row"] == 0


def test_iter_canonical_rows_one_per_image_all_valid(conv, tmp_path):
    parquet = tmp_path / "test.parquet"
    _synthetic_df().to_parquet(parquet, index=False)
    rows = list(
        conv.iter_canonical_rows(
            parquet, split="test", images_root=tmp_path / "images"
        )
    )
    assert len(rows) == 4  # one row per image, no instruction pairing
    assert all(validate_row(r) == [] for r in rows)
    ids = [r["input_id"] for r in rows]
    assert ids == [f"safety_v0_unsafebench_{i:06d}" for i in range(1, 5)]
    actions = [r["labels"]["action"] for r in rows]
    assert actions == ["safe", "reject", "reject", None]


def test_iter_respects_limit(conv, tmp_path):
    parquet = tmp_path / "test.parquet"
    _synthetic_df().to_parquet(parquet, index=False)
    rows = list(
        conv.iter_canonical_rows(
            parquet, split="test", images_root=tmp_path / "images", limit=2
        )
    )
    assert len(rows) == 2
