"""Tests for the balanced Vietnamese PI eval-set builder.

Uses synthetic canonical rows so the tests do not require the downloaded sources.
"""

import importlib.util
from pathlib import Path

import pytest

from src.pipeline.Datasets.safety_v0_schema import new_row, validate_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "safety_v0" / "build_pi_vi_eval.py"


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("build_pi_vi_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _local(idx, text, *, pi):
    row = new_row(
        f"safety_v0_local_vi_prompt_injection_{idx:06d}",
        "local_vietnamese_seed",
        has_text=True,
        input_text=text,
        sanitized_text=text,
    )
    row["labels"]["prompt_injection"] = pi
    row["label_source"]["prompt_injection"] = "source_gold"
    return row


def _vihsd(idx, text):
    row = new_row(
        f"safety_v0_vihsd_topic_safety_{idx:06d}",
        "uitnlp/vihsd",
        has_text=True,
        input_text=text,
        sanitized_text=text,
    )
    row["labels"]["prompt_injection"] = False
    row["label_source"]["prompt_injection"] = "source_assumption"
    return row


def test_balance_uses_just_enough_vihsd(build):
    local = (
        [_local(i, f"attack {i}", pi=True) for i in range(1, 6)]  # 5 positives
        + [_local(i, f"benign {i}", pi=False) for i in range(6, 8)]  # 2 benign seeds
    )
    vihsd = [_vihsd(i, f"comment {i}") for i in range(1, 11)]  # 10 available
    rows = build.select_rows(local, vihsd, vihsd_negatives=None, seed=42)
    buckets = {}
    for r in rows:
        buckets[r["eval"]["bucket"]] = buckets.get(r["eval"]["bucket"], 0) + 1
    # 5 positives need 5 negatives; 2 come from seeds, 3 from vihsd.
    assert buckets == {"attack": 5, "benign_seed": 2, "benign_vihsd": 3}
    pos = [r for r in rows if r["eval"]["label"]]
    neg = [r for r in rows if not r["eval"]["label"]]
    assert len(pos) == len(neg) == 5


def test_explicit_vihsd_count_respected(build):
    local = [_local(1, "attack", pi=True), _local(2, "benign", pi=False)]
    vihsd = [_vihsd(i, f"c{i}") for i in range(1, 11)]
    rows = build.select_rows(local, vihsd, vihsd_negatives=7, seed=42)
    vihsd_rows = [r for r in rows if r["eval"]["bucket"] == "benign_vihsd"]
    assert len(vihsd_rows) == 7


def test_eval_block_and_provenance(build):
    local = [_local(1, "attack", pi=True), _local(2, "benign", pi=False)]
    vihsd = [_vihsd(1, "comment")]
    rows = build.select_rows(local, vihsd, vihsd_negatives=1, seed=42)
    by_bucket = {r["eval"]["bucket"]: r for r in rows}
    assert by_bucket["attack"]["eval"] == {"label": True, "bucket": "attack", "gold": True}
    assert by_bucket["benign_seed"]["eval"]["gold"] is True
    # vihsd negatives are source_assumption -> trustworthy negative but not gold.
    assert by_bucket["benign_vihsd"]["eval"] == {
        "label": False,
        "bucket": "benign_vihsd",
        "gold": False,
    }
    for r in rows:
        assert validate_row(r) == []


def test_tag_does_not_mutate_original(build):
    src = _local(1, "attack", pi=True)
    tagged = build._tag(src, label=True, bucket="attack", gold=True)
    assert "eval" not in src
    assert tagged["eval"]["bucket"] == "attack"


def test_deterministic_sample(build):
    local = [_local(1, "attack", pi=True)]
    vihsd = [_vihsd(i, f"c{i}") for i in range(1, 21)]
    a = build.select_rows(local, vihsd, vihsd_negatives=5, seed=42)
    b = build.select_rows(local, vihsd, vihsd_negatives=5, seed=42)
    ids_a = [r["input_id"] for r in a if r["eval"]["bucket"] == "benign_vihsd"]
    ids_b = [r["input_id"] for r in b if r["eval"]["bucket"] == "benign_vihsd"]
    assert ids_a == ids_b
