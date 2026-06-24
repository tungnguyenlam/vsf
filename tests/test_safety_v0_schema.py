"""Tests for the canonical `safety_v0` row schema and validator.

Covers the Step-1 checklist in DATA_PLAN.md: required keys, unique IDs within a
row, span `box_ids` referencing existing OCR boxes, redaction `source_span_ids`
referencing existing spans, label value constraints, and the `null = unknown`
rule for derived masks.
"""

import copy

import pytest

from src.pipeline.Datasets.safety_v0_schema import (
    ACTION_VALUES,
    LABEL_FIELDS,
    RISK_FIELDS,
    derive_label_mask,
    is_valid_row,
    model_target,
    new_ocr_box,
    new_pii_span,
    new_prompt_injection_span,
    new_redaction,
    new_row,
    validate_row,
)


def make_full_row():
    """A valid image+text row exercising boxes, spans, and redaction refs."""
    row = new_row(
        "safety_v0_demo_000001",
        "demo/source",
        has_image=True,
        has_ocr=True,
        original_image_path="data/safety_v0/raw/demo/1.png",
        ocr_text="Nguyen Van A 0987654321",
    )
    row["geometry"]["ocr_boxes"] = [
        new_ocr_box("box_0001", "Nguyen Van A", 0, 12, [120, 80, 260, 112], 0.94),
        new_ocr_box("box_0002", "0987654321", 13, 23, [120, 120, 240, 150], 0.9),
    ]
    row["detections"]["pii_spans"] = [
        new_pii_span("pii_0001", "PERSON", 0, 12, "Nguyen Van A", 0.91, ["box_0001"]),
        new_pii_span("pii_0002", "PHONE_NUMBER", 13, 23, "0987654321", 0.99, ["box_0002"]),
    ]
    row["detections"]["prompt_injection_spans"] = [
        new_prompt_injection_span("pi_0001", "instruction_override", 0, 5, "abcde", 0.8, ["box_0001"]),
    ]
    row["detections"]["redaction_metadata"] = [
        new_redaction("redact_0001", ["pii_0001"], ["box_0001"], [116, 76, 264, 116]),
    ]
    row["labels"]["pii_visible"] = True
    row["label_source"]["pii_visible"] = "pipeline"
    return row


def test_new_row_is_valid_and_all_labels_unknown():
    row = new_row("safety_v0_demo_1", "demo/source", has_text=True, input_text="hello")
    assert validate_row(row) == []
    assert all(row["labels"][f] is None for f in LABEL_FIELDS)
    assert row["review"]["status"] == "unreviewed"


def test_full_row_is_valid():
    assert validate_row(make_full_row()) == []
    assert is_valid_row(make_full_row())


def test_missing_top_level_key_detected():
    row = make_full_row()
    del row["detections"]
    errors = validate_row(row)
    assert any("detections" in e for e in errors)


def test_duplicate_box_id_detected():
    row = make_full_row()
    row["geometry"]["ocr_boxes"][1]["box_id"] = "box_0001"
    assert any("duplicate box_id" in e for e in validate_row(row))


def test_span_referencing_unknown_box_id_detected():
    row = make_full_row()
    row["detections"]["pii_spans"][0]["box_ids"] = ["box_9999"]
    assert any("unknown box_id 'box_9999'" in e for e in validate_row(row))


def test_redaction_referencing_unknown_span_id_detected():
    row = make_full_row()
    row["detections"]["redaction_metadata"][0]["source_span_ids"] = ["pii_nope"]
    assert any("unknown span_id 'pii_nope'" in e for e in validate_row(row))


def test_redaction_referencing_unknown_box_id_detected():
    row = make_full_row()
    row["detections"]["redaction_metadata"][0]["box_ids"] = ["box_zzz"]
    assert any("unknown box_id 'box_zzz'" in e for e in validate_row(row))


def test_pii_and_pi_span_id_collision_detected():
    row = make_full_row()
    row["detections"]["prompt_injection_spans"][0]["span_id"] = "pii_0001"
    assert any("duplicate span_id" in e for e in validate_row(row))


@pytest.mark.parametrize("bad_action", ["allow", "block", "flag", 1, True])
def test_invalid_action_value_detected(bad_action):
    row = make_full_row()
    row["labels"]["action"] = bad_action
    assert any("labels.action" in e for e in validate_row(row))


@pytest.mark.parametrize("action", list(ACTION_VALUES) + [None])
def test_allowed_action_values_pass(action):
    row = make_full_row()
    row["labels"]["action"] = action
    assert validate_row(row) == []


def test_non_bool_risk_label_detected():
    row = make_full_row()
    row["labels"]["violence"] = "yes"
    assert any("labels.violence" in e for e in validate_row(row))


def test_unknown_label_field_detected():
    row = make_full_row()
    row["labels"]["nsfw"] = True
    assert any("unknown fields" in e for e in validate_row(row))


def test_bad_box_geometry_detected():
    row = make_full_row()
    row["geometry"]["ocr_boxes"][0]["box"] = [1, 2, 3]  # only 3 coords
    assert any("[x0,y0,x1,y1]" in e for e in validate_row(row))


def test_invalid_review_status_detected():
    row = make_full_row()
    row["review"]["status"] = "done"
    assert any("review.status" in e for e in validate_row(row))


def test_derive_label_mask_follows_null_is_unknown():
    row = new_row("x", "demo/source")
    row["labels"]["pii_visible"] = True
    row["labels"]["violence"] = False  # known-false is still a known label
    mask = derive_label_mask(row)
    assert mask["pii_visible"] == 1
    assert mask["violence"] == 1
    assert mask["sexual"] == 0  # still None -> unknown -> masked out
    assert all(k in mask for k in LABEL_FIELDS)


def test_model_target_collapses_unknown_to_false_without_touching_row():
    row = new_row("x", "demo/source")
    row["labels"]["action"] = "reject"
    row["labels"]["violence"] = True
    target = model_target(row)
    assert target["action"] == "reject"
    assert target["violence"] is True
    assert target["sexual"] is False  # unknown collapses in the target view only
    # The underlying row is untouched: still None (unknown).
    assert row["labels"]["sexual"] is None


def test_model_target_defaults_action_to_unsure_when_unknown():
    row = new_row("x", "demo/source")
    assert model_target(row)["action"] == "unsure"
    assert set(model_target(row)) == set(("action",) + tuple(RISK_FIELDS))


def test_builders_do_not_share_mutable_state():
    a = new_row("a", "demo/source")
    b = new_row("b", "demo/source")
    a["labels"]["violence"] = True
    a["geometry"]["ocr_boxes"].append(new_ocr_box("box_0001", "x", 0, 1, [0, 0, 1, 1]))
    assert b["labels"]["violence"] is None
    assert b["geometry"]["ocr_boxes"] == []


def test_validate_row_does_not_mutate_input():
    row = make_full_row()
    before = copy.deepcopy(row)
    validate_row(row)
    assert row == before
