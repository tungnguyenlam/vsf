"""Tests for the Vietnamese PI eval-set evaluator.

A fake detector keeps the metric math independent of the live rule set.
"""

import importlib.util
from pathlib import Path

import pytest

from src.pipeline.Datasets.safety_v0_schema import new_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "safety_v0" / "evaluate_pi_vi.py"


@pytest.fixture(scope="module")
def ev():
    spec = importlib.util.spec_from_file_location("evaluate_pi_vi", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeResult:
    def __init__(self, is_injection):
        self.is_injection = is_injection
        self.score = 0.9 if is_injection else 0.1
        self.matched_rules = ["fake_rule"] if is_injection else []


class _FakeDetector:
    """Fires when the text contains the marker word 'ATTACK'."""

    def detect(self, text):
        return _FakeResult("ATTACK" in text)


def _eval_row(idx, text, *, label, bucket):
    row = new_row(
        f"safety_v0_pi_{idx:06d}",
        "local_vietnamese_seed",
        has_text=True,
        input_text=text,
        sanitized_text=text,
    )
    row["eval"] = {"label": label, "bucket": bucket, "gold": True}
    return row


def test_predict_fires_on_marker(ev):
    det = _FakeDetector()
    assert ev.predict(det, _eval_row(1, "ATTACK now", label=True, bucket="attack")) is True
    assert ev.predict(det, _eval_row(2, "hello", label=False, bucket="benign_seed")) is False


def test_confusion_and_scores(ev):
    rows = [
        _eval_row(1, "ATTACK a", label=True, bucket="attack"),   # tp
        _eval_row(2, "ATTACK b", label=True, bucket="attack"),   # tp
        _eval_row(3, "benign c", label=True, bucket="attack"),   # fn (gold attack, no fire)
        _eval_row(4, "ATTACK d", label=False, bucket="benign_seed"),  # fp
        _eval_row(5, "benign e", label=False, bucket="benign_vihsd"),  # tn
    ]
    m = ev.evaluate(_FakeDetector(), rows)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 1)
    assert m["precision"] == round(2 / 3, 4)
    assert m["recall"] == round(2 / 3, 4)
    assert m["accuracy"] == round(3 / 5, 4)
    assert m["n"] == 5


def test_per_bucket_breakdown(ev):
    rows = [
        _eval_row(1, "ATTACK a", label=True, bucket="attack"),
        _eval_row(2, "ATTACK d", label=False, bucket="benign_seed"),
        _eval_row(3, "benign e", label=False, bucket="benign_vihsd"),
    ]
    m = ev.evaluate(_FakeDetector(), rows)
    assert m["per_bucket"]["attack"]["tp"] == 1
    assert m["per_bucket"]["benign_seed"]["fp"] == 1
    assert m["per_bucket"]["benign_vihsd"]["tn"] == 1


def test_error_records_captured(ev):
    rows = [
        _eval_row(1, "ATTACK d", label=False, bucket="benign_seed"),  # fp
        _eval_row(2, "benign c", label=True, bucket="attack"),        # fn
    ]
    m = ev.evaluate(_FakeDetector(), rows)
    kinds = {e["kind"] for e in m["errors"]}
    assert kinds == {"false_positive", "false_negative"}
    fp = next(e for e in m["errors"] if e["kind"] == "false_positive")
    assert fp["matched_rules"] == ["fake_rule"]
    assert fp["bucket"] == "benign_seed"
