"""Tests for the source-agnostic review-queue builder.

Synthetic canonical rows exercise each DATA_PLAN selector, priority ordering,
the limit cap, schema-validity of queued rows, and the CLI end-to-end. No
network, no real data files.
"""

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "safety_v0" / "build_review_queue.py"

from src.pipeline.Datasets.safety_v0_schema import new_row, validate_row  # noqa: E402


@pytest.fixture(scope="module")
def bq():
    spec = importlib.util.spec_from_file_location("build_review_queue", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(idx, **over):
    row = new_row(
        input_id=f"safety_v0_unsafebench_{idx:06d}",
        source_name="yiting/UnsafeBench",
        split="test",
    )
    labels = over.pop("labels", {})
    row["labels"].update(labels)
    det = over.pop("detections", {})
    row["detections"].update(det)
    return row


def test_action_null_is_selected_priority_2(bq):
    row = _row(1, labels={"action": None})
    reasons = bq.selection_reasons(row, has_images=True)
    assert (2, "action is null") in reasons


def test_pii_spans_without_pii_visible_is_conflict_priority_1(bq):
    row = _row(2, labels={"action": "reject", "pii_visible": None},
               detections={"pii_spans": [{"span_id": "pii_0001"}],
                           "redaction_metadata": [{"redaction_id": "r1"}]})
    reasons = bq.selection_reasons(row, has_images=True)
    ranks = {r for r, _ in reasons}
    # both the conflict (1) and the redaction selector (4) fire
    assert 1 in ranks and 4 in ranks


def test_reject_with_null_visual_axes_priority_3(bq):
    row = _row(3, labels={"action": "reject"})  # all axes null
    reasons = bq.selection_reasons(row, has_images=True)
    assert (3, "image rejected but all visual axes are null") in reasons
    # text-only source should NOT get the visual-mapping reason
    assert not bq.selection_reasons(row, has_images=False)


def test_safe_with_true_risk_is_conflict(bq):
    row = _row(4, labels={"action": "safe", "sexual": True})
    reasons = bq.selection_reasons(row, has_images=True)
    assert any(r == 1 and "action=safe" in note for r, note in reasons)


def test_clean_safe_row_not_selected(bq):
    row = _row(5, labels={"action": "safe", "sexual": False, "violence": False,
                          "blood_gore": False, "pii_visible": False,
                          "prompt_injection": False})
    assert bq.selection_reasons(row, has_images=True) == []


def test_build_queue_orders_by_priority_and_caps(bq):
    rows = [
        _row(10, labels={"action": None}),                       # P2
        _row(11, labels={"action": "reject"}),                   # P3 (image)
        _row(12, labels={"action": "reject"},
             detections={"pii_spans": [{"span_id": "p"}],
                         "redaction_metadata": [{"redaction_id": "r"}]}),  # P1
    ]
    queued, stats = bq.build_queue(rows, has_images=True, limit=None)
    assert stats["selected"] == 3 and stats["queued"] == 3
    # P1 row first, then P2, then P3
    assert queued[0]["input_id"].endswith("000012")
    assert queued[1]["input_id"].endswith("000010")
    assert queued[2]["input_id"].endswith("000011")
    assert all(r["review"]["status"] == "needs_review" for r in queued)
    assert all(validate_row(r) == [] for r in queued)

    capped, cstats = bq.build_queue(rows, has_images=True, limit=2)
    assert cstats["queued"] == 2 and cstats["dropped_by_limit"] == 1


def test_cli_end_to_end(bq, tmp_path, capsys):
    in_path = tmp_path / "weak.jsonl"
    out_path = tmp_path / "queue.jsonl"
    rows = [
        _row(20, labels={"action": "safe", "sexual": False, "violence": False,
                         "blood_gore": False, "pii_visible": False,
                         "prompt_injection": False}),  # not selected
        _row(21, labels={"action": None}),             # selected P2
    ]
    with open(in_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    rc = bq.main(["--input", str(in_path), "--output", str(out_path), "--has-images", "true"])
    assert rc == 0
    written = [json.loads(l) for l in open(out_path) if l.strip()]
    assert len(written) == 1
    assert written[0]["input_id"].endswith("000021")
    assert "auto-queued P2" in written[0]["review"]["notes"]
