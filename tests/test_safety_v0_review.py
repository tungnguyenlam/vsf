"""Tests for the webdemo safety_v0 review helpers (no Flask, no real data root)."""

import json

import pytest

from src.pipeline.Datasets.safety_v0_schema import new_row
from webdemo import safety_v0_review as review


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect the review module's roots into a temporary data tree."""
    root = tmp_path / "safety_v0"
    (root / "samples" / "demo").mkdir(parents=True)
    data_file = root / "samples" / "demo" / "x.jsonl"
    rows = [
        new_row("safety_v0_demo_000001", "demo", has_text=True, input_text="hi"),
        new_row("safety_v0_demo_000002", "demo", has_text=True, input_text="yo"),
    ]
    data_file.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def fake_shared_dir(kind, *, root=None, create=False):
        target = data_file.parents[2] / kind  # = <root>/<kind>
        if create:
            target.mkdir(parents=True, exist_ok=True)
        return target

    monkeypatch.setattr(review, "DATA_ROOT", root)
    monkeypatch.setattr(review, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(review, "shared_dir", fake_shared_dir)
    return tmp_path, root, data_file


def test_list_and_resolve(sandbox):
    repo_root, root, data_file = sandbox
    (root / "ocr" / "webpii").mkdir(parents=True)
    (root / "redacted" / "webpii").mkdir(parents=True)
    (root / "ocr" / "webpii" / "ocr.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "redacted" / "webpii" / "redacted.jsonl").write_text("{}\n", encoding="utf-8")

    files = review.list_canonical_files(root)
    assert any(f["path"].endswith("samples/demo/x.jsonl") for f in files)
    assert any(f["label"].startswith("[ocr]") for f in files)
    assert any(f["label"].startswith("[redacted]") for f in files)
    rel = data_file.relative_to(repo_root).as_posix()
    assert review.resolve_data_file(rel) == data_file.resolve()


def test_resolve_blocks_traversal(sandbox):
    assert review.resolve_data_file("../../etc/passwd") is None
    assert review.resolve_image("../../etc/passwd") is None
    assert review.resolve_image(None) is None


def test_load_rows_and_override_roundtrip(sandbox):
    repo_root, root, data_file = sandbox
    rows, stats = review.load_rows(data_file)
    assert stats["total"] == 2 and stats["reviewed"] == 0
    assert all("_label_mask" in r for r in rows)

    review.save_override(
        data_file,
        "safety_v0_demo_000001",
        {"action": "reject", "prompt_injection": True, "violence": None,
         "pii_visible": False, "sexual": None, "blood_gore": None,
         "political": False, "religious": False},
        {"status": "human_reviewed", "notes": "attack"},
        reviewer="tester",
    )
    rows2, stats2 = review.load_rows(data_file)
    assert stats2["reviewed"] == 1
    r0 = next(r for r in rows2 if r["input_id"] == "safety_v0_demo_000001")
    assert r0["labels"]["action"] == "reject"
    assert r0["labels"]["prompt_injection"] is True
    assert r0["label_source"]["action"] == "human"
    assert r0["label_source"]["violence"] is None  # unknown stays unsourced
    assert r0["review"]["notes"] == "attack"
    assert r0["_label_mask"]["violence"] == 0 and r0["_label_mask"]["action"] == 1


def test_latest_override_wins(sandbox):
    repo_root, root, data_file = sandbox
    base = {"pii_visible": None, "prompt_injection": None, "sexual": None,
            "violence": None, "blood_gore": None, "political": None, "religious": None}
    review.save_override(data_file, "safety_v0_demo_000002", {**base, "action": "safe"}, {"status": "human_reviewed"})
    review.save_override(data_file, "safety_v0_demo_000002", {**base, "action": "unsure"}, {"status": "needs_review"})
    rows, _ = review.load_rows(data_file)
    r = next(r for r in rows if r["input_id"] == "safety_v0_demo_000002")
    assert r["labels"]["action"] == "unsure"
    assert r["review"]["status"] == "needs_review"


def test_api_labels_are_base_layer_under_human(sandbox):
    repo_root, root, data_file = sandbox
    # Router/API layer marks row 1 needs_review with action=reject (label_source api).
    api_path = review.api_labels_path_for(data_file)
    api_path.parent.mkdir(parents=True, exist_ok=True)
    api_path.write_text(json.dumps({
        "input_id": "safety_v0_demo_000001",
        "labels": {"action": "reject", "violence": True, "pii_visible": None,
                   "prompt_injection": None, "sexual": None, "blood_gore": None,
                   "political": None, "religious": None},
        "label_source": {"action": "api", "violence": "api"},
        "review": {"status": "needs_review", "reviewer": "router:gemini_flash", "notes": ""},
    }) + "\n", encoding="utf-8")

    rows, stats = review.load_rows(data_file)
    assert stats["routed"] == 1 and stats["reviewed"] == 0
    r1 = next(r for r in rows if r["input_id"] == "safety_v0_demo_000001")
    assert r1["labels"]["action"] == "reject"
    assert r1["label_source"]["action"] == "api"
    assert r1["labels"]["violence"] is True
    assert r1["review"]["status"] == "needs_review"
    assert r1.get("_routed") is True

    # A human override then wins on top of the API layer.
    review.save_override(
        data_file, "safety_v0_demo_000001",
        {"action": "safe", "violence": False, "pii_visible": None, "prompt_injection": None,
         "sexual": None, "blood_gore": None, "political": None, "religious": None},
        {"status": "human_reviewed"},
    )
    rows2, stats2 = review.load_rows(data_file)
    r1b = next(r for r in rows2 if r["input_id"] == "safety_v0_demo_000001")
    assert r1b["labels"]["action"] == "safe"
    assert r1b["label_source"]["action"] == "human"
    assert stats2["reviewed"] == 1


def test_coerce_label_rejects_bad_values(sandbox):
    _, _, data_file = sandbox
    with pytest.raises(ValueError):
        review.save_override(data_file, "x", {"action": "allow"}, {})
    with pytest.raises(ValueError):
        review.save_override(data_file, "x", {"violence": "maybe"}, {})


# --- manual span / box annotation -------------------------------------------
from src.pipeline.Datasets.safety_v0_schema import (  # noqa: E402
    new_pii_span,
    validate_row,
)


@pytest.fixture
def span_sandbox(tmp_path, monkeypatch):
    """A sandbox whose row carries real text and one pre-existing gold PII span."""
    root = tmp_path / "safety_v0"
    (root / "converted" / "demo").mkdir(parents=True)
    data_file = root / "converted" / "demo" / "source_canonical.jsonl"
    row = new_row(
        "safety_v0_demo_000001", "demo", has_text=True,
        input_text="Lien he Nguyen Van An, ma so 12345.",
        sanitized_text="Lien he Nguyen Van An, ma so 12345.",
    )
    # Pre-existing gold span: the name (offsets into input_text).
    text = row["content"]["input_text"]
    start = text.index("Nguyen Van An")
    row["detections"]["pii_spans"].append(
        new_pii_span("gold_0001", "PERSON", start, start + len("Nguyen Van An"),
                     "Nguyen Van An", score=1.0, detector="source_gold")
    )
    data_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

    def fake_shared_dir(kind, *, root=None, create=False):
        target = data_file.parents[2] / kind
        if create:
            target.mkdir(parents=True, exist_ok=True)
        return target

    monkeypatch.setattr(review, "DATA_ROOT", root)
    monkeypatch.setattr(review, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(review, "shared_dir", fake_shared_dir)
    return tmp_path, root, data_file


def _no_labels():
    return {f: None for f in ("action", "pii_visible", "prompt_injection", "sexual",
                              "violence", "blood_gore", "political", "religious")}


def test_add_pii_span_reanonymizes(span_sandbox):
    _, _, data_file = span_sandbox
    text = "Lien he Nguyen Van An, ma so 12345."
    s = text.index("12345")
    review.save_override(
        data_file, "safety_v0_demo_000001", _no_labels(), {"status": "human_reviewed"},
        span_edits={"pii_spans": {"added": [
            {"entity_type": "ID", "start": s, "end": s + 5, "text": "12345"}]}},
    )
    rows, _ = review.load_rows(data_file)
    r = rows[0]
    spans = r["detections"]["pii_spans"]
    human = [sp for sp in spans if sp["detector"] == "human"]
    assert len(human) == 1 and human[0]["entity_type"] == "ID"
    assert human[0]["score"] == 1.0 and human[0]["span_id"].startswith("human_pii_")
    # gold span preserved, sanitized text now masks both name and the new ID.
    assert any(sp["detector"] == "source_gold" for sp in spans)
    assert r["content"]["sanitized_text"] == "Lien he <PERSON>, ma so <ID>."


def test_delete_existing_span(span_sandbox):
    _, _, data_file = span_sandbox
    text = "Lien he Nguyen Van An, ma so 12345."
    start = text.index("Nguyen Van An")
    review.save_override(
        data_file, "safety_v0_demo_000001", _no_labels(), {"status": "human_reviewed"},
        span_edits={"pii_spans": {"deleted": [[start, start + 13, "PERSON"]]}},
    )
    rows, _ = review.load_rows(data_file)
    spans = rows[0]["detections"]["pii_spans"]
    assert spans == []  # gold span removed by its (start,end,type) key
    # sanitized text recomputed with no spans == original input text.
    assert rows[0]["content"]["sanitized_text"] == text


def test_add_injection_span(span_sandbox):
    _, _, data_file = span_sandbox
    review.save_override(
        data_file, "safety_v0_demo_000001", _no_labels(), {"status": "human_reviewed"},
        span_edits={"prompt_injection_spans": {"added": [
            {"attack_type": "instruction_override", "start": 0, "end": 7, "text": "Lien he"}]}},
    )
    rows, _ = review.load_rows(data_file)
    pi = rows[0]["detections"]["prompt_injection_spans"]
    assert len(pi) == 1 and pi[0]["attack_type"] == "instruction_override"
    assert pi[0]["detector"] == "human"


def test_add_image_box_to_source_pii_boxes(span_sandbox):
    _, _, data_file = span_sandbox
    review.save_override(
        data_file, "safety_v0_demo_000001", _no_labels(), {"status": "human_reviewed"},
        span_edits={"boxes": {"added": [
            {"entity_type": "PERSON", "box": [10, 20, 110, 60], "text": ""}]}},
    )
    rows, _ = review.load_rows(data_file)
    boxes = rows[0]["geometry"].get("source_pii_boxes") or []
    assert len(boxes) == 1
    assert boxes[0]["entity_type"] == "PERSON" and boxes[0]["detector"] == "human"
    assert boxes[0]["box_id"].startswith("human_box_")
    assert boxes[0]["box"] == [10.0, 20.0, 110.0, 60.0]


def test_merged_row_with_human_box_still_validates(span_sandbox):
    """Baking a human box (source_pii_boxes) must keep the row schema-valid."""
    _, _, data_file = span_sandbox
    review.save_override(
        data_file, "safety_v0_demo_000001", _no_labels(), {"status": "human_reviewed"},
        span_edits={"boxes": {"added": [
            {"entity_type": "PERSON", "box": [10, 20, 110, 60], "text": ""}]}},
    )
    rows, _ = review.load_rows(data_file)
    merged = {k: v for k, v in rows[0].items() if not k.startswith("_")}
    assert validate_row(merged) == []


def test_span_edit_idempotent_on_reapply(span_sandbox):
    _, _, data_file = span_sandbox
    text = "Lien he Nguyen Van An, ma so 12345."
    s = text.index("12345")
    edit = {"pii_spans": {"added": [
        {"entity_type": "ID", "start": s, "end": s + 5, "text": "12345"}]}}
    # Latest override wins; re-saving the same edit must not duplicate spans.
    review.save_override(data_file, "safety_v0_demo_000001", _no_labels(),
                         {"status": "human_reviewed"}, span_edits=edit)
    review.save_override(data_file, "safety_v0_demo_000001", _no_labels(),
                         {"status": "human_reviewed"}, span_edits=edit)
    rows, _ = review.load_rows(data_file)
    human = [sp for sp in rows[0]["detections"]["pii_spans"] if sp["detector"] == "human"]
    assert len(human) == 1


def test_clean_span_edits_rejects_bad_input(span_sandbox):
    _, _, data_file = span_sandbox
    with pytest.raises(ValueError):  # end past text length
        review.save_override(data_file, "safety_v0_demo_000001", _no_labels(), {},
                             span_edits={"pii_spans": {"added": [
                                 {"entity_type": "ID", "start": 0, "end": 9999, "text": "x"}]}})
    with pytest.raises(ValueError):  # missing entity_type
        review.save_override(data_file, "safety_v0_demo_000001", _no_labels(), {},
                             span_edits={"pii_spans": {"added": [
                                 {"entity_type": "", "start": 0, "end": 4, "text": "Lien"}]}})
    with pytest.raises(ValueError):  # malformed box
        review.save_override(data_file, "safety_v0_demo_000001", _no_labels(), {},
                             span_edits={"boxes": {"added": [
                                 {"entity_type": "PERSON", "box": [1, 2, 3]}]}})
