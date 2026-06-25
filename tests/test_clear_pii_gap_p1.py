"""Tests for the P1 pii-gap bulk-clear script."""

import json
from pathlib import Path

import importlib.util

from webdemo import safety_v0_review as review

_SPEC = importlib.util.spec_from_file_location(
    "clear_pii_gap_p1",
    Path(__file__).resolve().parents[1] / "scripts" / "safety_v0" / "clear_pii_gap_p1.py",
)
clear_pii_gap_p1 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(clear_pii_gap_p1)


def _row(iid, *, pii_spans, pii_visible, action="reject"):
    return {
        "input_id": iid,
        "labels": {"action": action, "pii_visible": pii_visible},
        "label_source": {"action": "source_gold", "pii_visible": None},
        "detections": {"pii_spans": pii_spans},
        "review": {"status": "needs_review", "notes": ""},
    }


def _write_queue(tmp_path, rows):
    qp = tmp_path / "queue.jsonl"
    with open(qp, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return qp


def test_is_pii_gap_row():
    assert clear_pii_gap_p1.is_pii_gap_row(_row("a", pii_spans=[{"x": 1}], pii_visible=None))
    assert clear_pii_gap_p1.is_pii_gap_row(_row("a", pii_spans=[{"x": 1}], pii_visible=False))
    # already true -> not a gap
    assert not clear_pii_gap_p1.is_pii_gap_row(_row("a", pii_spans=[{"x": 1}], pii_visible=True))
    # no spans -> not a gap
    assert not clear_pii_gap_p1.is_pii_gap_row(_row("a", pii_spans=[], pii_visible=None))


def _override_dir(tmp_path):
    d = tmp_path / "overrides"
    d.mkdir(exist_ok=True)
    return d


def _isolate(tmp_path, monkeypatch):
    # route override storage into tmp and rebase REPO_ROOT so load_rows' stats
    # (which take relative_to(REPO_ROOT)) resolve against tmp, not the real repo.
    monkeypatch.setattr(review, "shared_dir", lambda kind, create=False: _override_dir(tmp_path))
    monkeypatch.setattr(review, "REPO_ROOT", tmp_path)


def test_clears_only_gap_rows_and_preserves_provenance(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    qp = _write_queue(
        tmp_path,
        [
            _row("gap1", pii_spans=[{"start": 0, "end": 3}], pii_visible=None),
            _row("notgap", pii_spans=[], pii_visible=None),
            _row("already", pii_spans=[{"start": 0, "end": 3}], pii_visible=True),
        ],
    )

    rc = clear_pii_gap_p1.main(["--input", str(qp)])
    assert rc == 0

    rows, stats = review.load_rows(qp)
    by_id = {r["input_id"]: r for r in rows}
    assert by_id["gap1"]["labels"]["pii_visible"] is True
    assert by_id["gap1"]["label_source"]["pii_visible"] == "human"
    assert by_id["gap1"]["review"]["status"] == "human_reviewed"
    # action provenance untouched (only pii_visible was set).
    assert by_id["gap1"]["label_source"]["action"] == "source_gold"
    # non-gap rows stay needs_review.
    assert by_id["notgap"]["review"]["status"] == "needs_review"
    assert by_id["already"]["review"].get("status") == "needs_review"


def test_idempotent(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    qp = _write_queue(tmp_path, [_row("gap1", pii_spans=[{"start": 0, "end": 3}], pii_visible=None)])

    clear_pii_gap_p1.main(["--input", str(qp)])
    override_lines = sum(1 for _ in open(review.override_path_for(qp)))
    clear_pii_gap_p1.main(["--input", str(qp)])
    # second run writes nothing new.
    assert sum(1 for _ in open(review.override_path_for(qp))) == override_lines
