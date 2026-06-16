"""Tests for safety_v0 source registry and path helpers."""

from pathlib import Path

import pytest

from src.pipeline.Datasets import safety_v0_sources as sv


def test_registry_has_workqueue_sources_in_order():
    slugs = sv.list_source_slugs()
    assert slugs[0] == "existing_repo_pii"
    assert slugs[1] == "webpii"
    assert "vihsd_topic_safety" in slugs
    assert "unsafebench" in slugs
    # Slugs are unique.
    assert len(slugs) == len(set(slugs))


def test_get_source_and_unknown_raises():
    src = sv.get_source("webpii")
    assert src.name == "WebPII/webpii"
    assert src.has_images is True
    with pytest.raises(ValueError):
        sv.get_source("does_not_exist")


def test_format_input_id_is_zero_padded_and_validated():
    assert sv.format_input_id("webpii", 1) == "safety_v0_webpii_000001"
    assert sv.format_input_id("existing_repo_pii", 42) == "safety_v0_existing_repo_pii_000042"
    with pytest.raises(ValueError):
        sv.format_input_id("nope", 1)


def test_per_source_paths(tmp_path):
    root = tmp_path / "safety_v0"
    conv = sv.converted_path("webpii", root=root)
    assert conv == root / "converted" / "webpii" / "source_canonical.jsonl"
    weak = sv.weak_path("webpii", root=root)
    assert weak == root / "weak" / "webpii" / "weak_labeled.jsonl"
    # Not created unless asked.
    assert not conv.parent.exists()


def test_create_flag_makes_directories(tmp_path):
    root = tmp_path / "safety_v0"
    conv = sv.converted_path("webpii", root=root, create=True)
    assert conv.parent.is_dir()


def test_human_overrides_path_per_source(tmp_path):
    root = tmp_path / "safety_v0"
    p = sv.human_overrides_path("vlguard", root=root)
    assert p == root / "review" / "human_overrides" / "vlguard.jsonl"


def test_shared_dirs(tmp_path):
    root = tmp_path / "safety_v0"
    assert sv.final_dir(root=root) == root / "final"
    assert sv.manifests_dir(root=root) == root / "manifests"
    assert sv.review_queue_dir(root=root) == root / "review" / "queue"
    assert sv.api_labels_dir(root=root) == root / "review" / "api_labels"


def test_unknown_kinds_raise(tmp_path):
    with pytest.raises(ValueError):
        sv.source_dir("bogus", "webpii", root=tmp_path)
    with pytest.raises(ValueError):
        sv.shared_dir("bogus", root=tmp_path)


def test_default_data_root_points_into_repo():
    assert sv.DEFAULT_DATA_ROOT.parts[-2:] == ("data", "safety_v0")
    assert isinstance(sv.data_root(), Path)
