"""Tests for the existing-repo-PII converter logic (no dataset download).

Loads the converter script by path and exercises its pure functions on
synthetic rows, then validates the produced canonical rows.
"""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline.Datasets.safety_v0_schema import derive_label_mask, validate_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "safety_v0" / "convert" / "convert_existing_repo_pii.py"


@pytest.fixture(scope="module")
def conv():
    spec = importlib.util.spec_from_file_location("convert_existing_repo_pii", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LABEL_MAP = {"human_name": "PERSON", "phone_number": "PHONE_NUMBER"}


def test_map_pii_spans_maps_known_and_drops_unknown(conv):
    text = "Toi la Nguyen Van A, sdt 0987654321 ma 999"
    mask = [
        {"start": 7, "end": 19, "label": "human_name"},
        {"start": 25, "end": 35, "label": "phone_number"},
        {"start": 39, "end": 42, "label": "order_code"},  # unmapped -> dropped
    ]
    spans = conv.map_pii_spans(text, mask, LABEL_MAP)
    assert [s["entity_type"] for s in spans] == ["PERSON", "PHONE_NUMBER"]
    assert spans[0]["text"] == "Nguyen Van A"
    assert spans[1]["text"] == "0987654321"
    assert spans[0]["span_id"] == "pii_0001" and spans[1]["span_id"] == "pii_0002"
    assert all(s["detector"] == "source_gold" for s in spans)


def test_map_pii_spans_drops_out_of_range(conv):
    text = "short"
    mask = [{"start": 2, "end": 999, "label": "human_name"}]
    assert conv.map_pii_spans(text, mask, LABEL_MAP) == []


def test_expanded_taxonomy_maps_previously_dropped_labels():
    """Labels that used to be dropped now map to the expanded target types and
    are therefore redacted by the safety converter."""
    from src.pipeline.Datasets import VI_PII_DROPPED_LABELS, VI_PII_LABEL_TO_PRESIDIO as M

    assert M["MA_PIN"] == "CREDENTIAL"
    assert M["DIA_CHI_IP"] == "IP_ADDRESS"
    assert M["SO_THE_TIN_DUNG"] == "CREDIT_CARD"
    assert M["CHAN_DOAN"] == "MEDICAL"
    assert M["SO_GIAY_PHEP_LAI_XE"] == "ID"  # ID-like numbers fold into ID
    assert M["BIEN_SO_XE"] == "VEHICLE"
    # Genuinely non-personal tokens stay out of the mapping.
    assert "LOAI_TIEN_TE" not in M and "LOAI_TIEN_TE" in VI_PII_DROPPED_LABELS


def test_anonymize_replaces_spans_and_keeps_rest(conv):
    text = "Toi la Nguyen Van A, sdt 0987654321 ok"
    mask = [
        {"start": 7, "end": 19, "label": "human_name"},
        {"start": 25, "end": 35, "label": "phone_number"},
    ]
    spans = conv.map_pii_spans(text, mask, LABEL_MAP)
    sanitized = conv.anonymize(text, spans)
    assert sanitized == "Toi la <PERSON>, sdt <PHONE_NUMBER> ok"
    assert "Nguyen Van A" not in sanitized
    assert "0987654321" not in sanitized


def test_pii_only_labels_policy(conv):
    labels, source = conv.pii_only_text_labels()
    assert labels["action"] == "safe"
    assert labels["pii_visible"] is False
    assert labels["prompt_injection"] is False
    assert labels["political"] is False and labels["religious"] is False
    # Ordinary PII text: all content risk axes asserted absent (not unknown).
    assert labels["sexual"] is False
    assert labels["violence"] is False
    assert labels["blood_gore"] is False
    assert source["pii_visible"] == "source_gold"
    assert source["sexual"] == "source_assumption"


def test_build_canonical_row_is_valid_and_masks_visual_out(conv):
    text = "Lien he Nguyen Van A"
    mask = [{"start": 8, "end": 20, "label": "human_name"}]
    row = conv.build_canonical_row(
        index=1,
        dataset_name="hoangha_vie_pii",
        split="train",
        source_sample_id="hoangha_vie_pii:train:5",
        source_text=text,
        privacy_mask=mask,
        label_to_presidio=LABEL_MAP,
    )
    assert validate_row(row) == []
    assert row["input_id"] == "safety_v0_existing_repo_pii_000001"
    assert row["source"]["name"] == "hoangha_vie_pii"
    assert row["modality"]["has_text"] is True and row["modality"]["has_image"] is False
    assert row["content"]["sanitized_text"] == "Lien he <PERSON>"
    assert len(row["detections"]["pii_spans"]) == 1
    mask_view = derive_label_mask(row)
    # Ordinary text: every axis is supervised (content known), none masked out.
    assert mask_view["sexual"] == 1 and mask_view["pii_visible"] == 1
    assert row["source_labels"] == {"gold_span_count": 1, "mapped_pii_count": 1}


def test_iter_canonical_rows_increments_ids_and_validates(conv):
    df = pd.DataFrame(
        [
            {"source_text": "A Nguyen Van A", "privacy_mask": [{"start": 2, "end": 14, "label": "human_name"}], "split": "train", "input_id": "x:0"},
            {"source_text": "no pii here", "privacy_mask": [], "split": "train", "input_id": "x:1"},
        ]
    )
    rows = list(conv.iter_canonical_rows(df, "pii_masking_95k", LABEL_MAP, start_index=1))
    assert [r["input_id"] for r in rows] == [
        "safety_v0_existing_repo_pii_000001",
        "safety_v0_existing_repo_pii_000002",
    ]
    assert all(validate_row(r) == [] for r in rows)
    # Row with no PII still gets the safe PII-only policy.
    assert rows[1]["detections"]["pii_spans"] == []
    assert rows[1]["labels"]["action"] == "safe"
